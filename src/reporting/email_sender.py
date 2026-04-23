"""
Email Sender Module.

Sends the analysis report via Gmail SMTP using an App Password.
No external email service required — uses Python's built-in smtplib.

Setup:
1. Go to https://myaccount.google.com/apppasswords
2. Generate an App Password for "Mail"
3. Add to .env: GMAIL_ADDRESS and GMAIL_APP_PASSWORD
"""

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import (
    EMAIL_RECIPIENT,
    EMAIL_SUBJECT_TEMPLATE,
    FINAL_TOP_PICKS,
    GMAIL_ADDRESS,
    GMAIL_APP_PASSWORD,
)

logger = logging.getLogger(__name__)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def _markdown_to_html(md_content: str) -> str:
    """
    Convert markdown report to a simple, readable HTML email.
    Handles headings, tables, bold, lists, and blockquotes.
    """
    import re

    lines = md_content.split("\n")
    html_lines = []
    in_table = False
    in_list = False
    in_code_block = False

    # Email-friendly CSS
    html_lines.append("""
    <html>
    <head>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
               color: #1a1a2e; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; }
        h1 { color: #0f3460; border-bottom: 2px solid #e94560; padding-bottom: 8px; }
        h2 { color: #16213e; margin-top: 30px; border-bottom: 1px solid #ddd; padding-bottom: 5px; }
        h3 { color: #0f3460; }
        table { border-collapse: collapse; width: 100%; margin: 15px 0; }
        th { background-color: #0f3460; color: white; padding: 10px 12px; text-align: left; }
        td { padding: 8px 12px; border-bottom: 1px solid #ddd; }
        tr:nth-child(even) { background-color: #f8f9fa; }
        blockquote { border-left: 4px solid #e94560; margin: 15px 0; padding: 10px 20px; 
                     background: #fff3f5; color: #333; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
        pre { background: #1a1a2e; color: #e0e0e0; padding: 15px; border-radius: 5px; 
              overflow-x: auto; }
        .pass { color: #27ae60; } .fail { color: #e74c3c; }
        hr { border: none; border-top: 1px solid #ddd; margin: 25px 0; }
        ul { padding-left: 20px; }
        li { margin: 4px 0; }
        strong { color: #0f3460; }
        .disclaimer { font-size: 0.85em; color: #666; font-style: italic; margin-top: 30px; 
                      padding: 15px; background: #f9f9f9; border-radius: 5px; }
    </style>
    </head>
    <body>
    """)

    for line in lines:
        stripped = line.strip()

        # Code blocks
        if stripped.startswith("```"):
            if in_code_block:
                html_lines.append("</pre>")
                in_code_block = False
            else:
                html_lines.append("<pre>")
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(line)
            continue

        # Empty lines
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            if in_table:
                html_lines.append("</table>")
                in_table = False
            continue

        # Headings
        if stripped.startswith("# "):
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
            continue
        if stripped.startswith("## "):
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
            continue
        if stripped.startswith("### "):
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
            continue

        # Horizontal rules
        if stripped == "---":
            html_lines.append("<hr>")
            continue

        # Tables
        if "|" in stripped and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]

            # Skip separator rows
            if all(c.replace("-", "").replace(":", "") == "" for c in cells):
                continue

            if not in_table:
                html_lines.append("<table>")
                in_table = True
                # First row is header
                html_lines.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
            else:
                # Apply pass/fail styling
                styled_cells = []
                for c in cells:
                    if "✅" in c:
                        styled_cells.append(f'<td class="pass">{c}</td>')
                    elif "❌" in c:
                        styled_cells.append(f'<td class="fail">{c}</td>')
                    else:
                        styled_cells.append(f"<td>{c}</td>")
                html_lines.append("<tr>" + "".join(styled_cells) + "</tr>")
            continue

        # Close table if we're past it
        if in_table and "|" not in stripped:
            html_lines.append("</table>")
            in_table = False

        # Lists
        if stripped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{stripped[2:]}</li>")
            continue

        # Blockquotes
        if stripped.startswith("> "):
            html_lines.append(f"<blockquote>{stripped[2:]}</blockquote>")
            continue

        # Disclaimer section
        if stripped.startswith("*This report is generated") or stripped.startswith("*"):
            html_lines.append(f'<div class="disclaimer">{stripped}</div>')
            continue

        # Regular paragraphs — apply bold/italic formatting
        import re
        text = stripped
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        html_lines.append(f"<p>{text}</p>")

    # Close any open elements
    if in_table:
        html_lines.append("</table>")
    if in_list:
        html_lines.append("</ul>")
    if in_code_block:
        html_lines.append("</pre>")

    html_lines.append("</body></html>")
    return "\n".join(html_lines)


def send_report_email(
    report_path: str,
    report_content: Optional[str] = None,
) -> bool:
    """
    Send the analysis report via Gmail SMTP.

    Args:
        report_path: Path to the markdown report file.
        report_content: Optional pre-loaded report content. If None, reads from report_path.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        logger.error(
            "Email not configured. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env. "
            "Get an App Password at https://myaccount.google.com/apppasswords"
        )
        return False

    if not EMAIL_RECIPIENT:
        logger.error("No email recipient configured. Set EMAIL_RECIPIENT in config.py")
        return False

    # Load report content
    if report_content is None:
        try:
            report_content = Path(report_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.error(f"Report file not found: {report_path}")
            return False

    # Build email
    today = datetime.now().strftime("%B %d, %Y")
    subject = EMAIL_SUBJECT_TEMPLATE.format(n=FINAL_TOP_PICKS, date=today)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = EMAIL_RECIPIENT

    # Plain text version (the raw markdown)
    plain_part = MIMEText(report_content, "plain", "utf-8")
    msg.attach(plain_part)

    # HTML version (formatted)
    html_content = _markdown_to_html(report_content)
    html_part = MIMEText(html_content, "html", "utf-8")
    msg.attach(html_part)

    # Send via Gmail SMTP
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, EMAIL_RECIPIENT, msg.as_string())

        logger.info(f"✉️  Report emailed to {EMAIL_RECIPIENT}")
        logger.info(f"   Subject: {subject}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. Make sure you're using an App Password, "
            "not your regular password. Get one at https://myaccount.google.com/apppasswords"
        )
        return False
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False
