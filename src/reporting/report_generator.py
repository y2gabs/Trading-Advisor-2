"""
Report Generator.

Produces professional markdown reports summarizing the stock analysis,
including top picks, detailed valuations, and methodology notes.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from src.analysis.scoring import ScoredStock
from src.config import (
    REPORTS_DIR,
    DISCOUNT_RATE,
    TERMINAL_GROWTH_RATE,
    DCF_PROJECTION_YEARS,
    MAINTENANCE_CAPEX_RATIO,
    MARGIN_OF_SAFETY_THRESHOLD,
    FINAL_TOP_PICKS,
)

logger = logging.getLogger(__name__)


def _format_currency(value: float) -> str:
    """Format a number as currency."""
    if abs(value) >= 1e9:
        return f"${value/1e9:.2f}B"
    elif abs(value) >= 1e6:
        return f"${value/1e6:.1f}M"
    elif abs(value) >= 1e3:
        return f"${value/1e3:.1f}K"
    else:
        return f"${value:.2f}"


def _format_pct(value: float) -> str:
    """Format a decimal as percentage."""
    return f"{value:.1%}"


def _conviction_emoji(conviction: str) -> str:
    """Map conviction level to visual indicator."""
    return {
        "High": "🟢",
        "Medium": "🟡",
        "Low": "🔴",
    }.get(conviction, "⚪")


def generate_report(
    claude_analysis: Dict[str, Any],
    candidates: List[ScoredStock],
    universe_size: int,
    stocks_analyzed: int,
    undervalued_count: int,
    run_duration_seconds: float = 0,
) -> str:
    """
    Generate a comprehensive markdown report.

    Args:
        claude_analysis: Output from claude_analyst.analyze_and_select_top_picks()
        candidates: The top N ScoredStock objects that were researched
        universe_size: Total stocks in the TSX universe
        stocks_analyzed: Stocks with sufficient data for analysis
        undervalued_count: Stocks that passed the undervaluation filter
        run_duration_seconds: How long the full pipeline took

    Returns:
        Path to the saved report file.
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%I:%M %p ET")

    top_picks = claude_analysis.get("top_picks", [])
    market_commentary = claude_analysis.get("market_commentary", "N/A")
    sector_themes = claude_analysis.get("sector_themes", "N/A")

    # Build a lookup for candidates by ticker
    candidate_lookup = {c.ticker: c for c in candidates}

    # ── Build the report ────────────────────────────────────────────────────
    lines = []

    # Header
    lines.append(f"# 📊 TSX Value Investing Report")
    lines.append(f"### {now.strftime('%B %d, %Y')} | Generated at {time_str}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Pipeline summary
    lines.append("## 🔍 Analysis Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| **TSX Universe** | {universe_size} stocks |")
    lines.append(f"| **Stocks Analyzed** | {stocks_analyzed} (sufficient financial data) |")
    lines.append(f"| **Undervalued (Buffett Model)** | {undervalued_count} stocks |")
    lines.append(f"| **Deep-Researched** | {len(candidates)} candidates |")
    lines.append(f"| **Final Picks** | {len(top_picks)} top recommendations |")
    if run_duration_seconds > 0:
        minutes = int(run_duration_seconds // 60)
        seconds = int(run_duration_seconds % 60)
        lines.append(f"| **Analysis Duration** | {minutes}m {seconds}s |")
    lines.append("")

    # Market commentary
    lines.append("## 🌎 Market Commentary")
    lines.append("")
    lines.append(market_commentary)
    lines.append("")

    if sector_themes and sector_themes != "N/A":
        lines.append("### Sector Themes")
        lines.append("")
        lines.append(sector_themes)
        lines.append("")

    lines.append("---")
    lines.append("")

    # Executive summary — Top picks at a glance
    lines.append(f"## 🏆 Top {len(top_picks)} Undervalued TSX Stocks")
    lines.append("")
    lines.append(f"| Rank | Ticker | Company | Conviction | Price | Intrinsic Value | Margin of Safety | Position |")
    lines.append(f"|------|--------|---------|------------|-------|-----------------|------------------|----------|")

    for pick in top_picks:
        ticker = pick.get("ticker", "?")
        candidate = candidate_lookup.get(ticker)
        iv = candidate.valuation.intrinsic_value_per_share if candidate and candidate.valuation else 0
        mos = candidate.valuation.margin_of_safety if candidate and candidate.valuation else 0
        price = candidate.valuation.current_price if candidate and candidate.valuation else 0
        conviction = pick.get("conviction", "?")
        emoji = _conviction_emoji(conviction)

        lines.append(
            f"| #{pick.get('rank', '?')} "
            f"| **{ticker}** "
            f"| {pick.get('name', '?')} "
            f"| {emoji} {conviction} "
            f"| ${price:.2f} "
            f"| ${iv:.2f} "
            f"| {_format_pct(mos)} "
            f"| {pick.get('position_size_pct', 0):.0f}% |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    # Detailed analysis for each pick
    for pick in top_picks:
        ticker = pick.get("ticker", "?")
        candidate = candidate_lookup.get(ticker)
        rank = pick.get("rank", "?")

        lines.append(f"## #{rank}. {pick.get('name', ticker)} ({ticker})")
        lines.append("")

        # Conviction & thesis
        conviction = pick.get("conviction", "?")
        lines.append(f"**Conviction:** {_conviction_emoji(conviction)} {conviction}")
        lines.append(f"**Suggested Position:** {pick.get('position_size_pct', 0):.0f}% of portfolio")
        lines.append("")

        lines.append(f"### Investment Thesis")
        lines.append(pick.get("thesis", "N/A"))
        lines.append("")

        # Analyst writeup — narrative explanation of why we recommend this stock
        writeup = pick.get("writeup", "")
        if writeup:
            lines.append("### 📝 Why We Recommend This Stock")
            lines.append("")
            # Split on newlines to preserve paragraph breaks from Claude
            for paragraph in writeup.split("\n"):
                paragraph = paragraph.strip()
                if paragraph:
                    lines.append(paragraph)
                    lines.append("")

        # Valuation details
        if candidate and candidate.valuation:
            v = candidate.valuation
            s = candidate.stock_data
            lines.append(f"### Valuation")
            lines.append("")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Current Price | **${v.current_price:.2f}** |")
            lines.append(f"| Intrinsic Value (Base) | **${v.intrinsic_value_per_share:.2f}** |")
            lines.append(f"| Intrinsic Value (Conservative) | ${v.intrinsic_value_conservative:.2f} |")
            lines.append(f"| Margin of Safety (Base) | **{_format_pct(v.margin_of_safety)}** |")
            lines.append(f"| Margin of Safety (Conservative) | {_format_pct(v.margin_of_safety_conservative)} |")
            lines.append(f"| Growth Rate Used | {_format_pct(v.estimated_growth_rate)} |")
            lines.append(f"| Avg Owner Earnings (3yr) | {_format_currency(v.avg_owner_earnings)} |")
            lines.append(f"| Confidence | {v.valuation_confidence.title()} |")
            lines.append("")

        # Financial health
        if candidate and candidate.health:
            h = candidate.health
            lines.append(f"### Financial Health — Grade: **{h.grade}** ({h.overall_score:.0%})")
            lines.append("")
            lines.append(f"| Check | Result | Score | Detail |")
            lines.append(f"|-------|--------|-------|--------|")
            for check in h.checks:
                status = "✅" if check.passed else "❌"
                lines.append(
                    f"| {check.name} | {status} | {check.score:.0%} | {check.detail} |"
                )
            lines.append("")

        # Key financials
        if candidate and candidate.stock_data:
            s = candidate.stock_data
            lines.append(f"### Key Financials")
            lines.append("")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Market Cap | {_format_currency(s.market_cap)} |")
            lines.append(f"| P/E Ratio | {s.pe_ratio:.1f} |")
            lines.append(f"| P/B Ratio | {s.pb_ratio:.1f} |")
            lines.append(f"| ROE (Avg) | {_format_pct(s.avg_roe)} |")
            lines.append(f"| Debt/Equity | {s.debt_to_equity:.2f} |")
            lines.append(f"| Current Ratio | {s.current_ratio:.2f} |")
            lines.append(f"| Dividend Yield | {_format_pct(s.dividend_yield)} |")
            lines.append(f"| Sector | {s.sector} |")
            lines.append(f"| Industry | {s.industry} |")
            lines.append("")

        # Qualitative research
        research = candidate.perplexity_research if candidate else None
        if research and "error" not in research:
            lines.append(f"### Qualitative Research")
            lines.append("")
            lines.append(f"**Competitive Moat:** {research.get('moat_rating', 'N/A')}")
            if research.get("moat_analysis"):
                lines.append(f"> {research['moat_analysis']}")
            lines.append("")

            lines.append(f"**Management:** {research.get('management_quality', 'N/A')}")
            if research.get("management_detail"):
                lines.append(f"> {research['management_detail']}")
            lines.append("")

            lines.append(f"**Industry Outlook:** {research.get('industry_outlook', 'N/A')}")
            if research.get("industry_detail"):
                lines.append(f"> {research['industry_detail']}")
            lines.append("")

            if research.get("recent_news"):
                lines.append(f"**Recent News:** {research['recent_news']}")
                lines.append("")

        # Bull/Bear case
        lines.append("### Bull Case 📈")
        lines.append(pick.get("bull_case", "N/A"))
        lines.append("")
        lines.append("### Bear Case 📉")
        lines.append(pick.get("bear_case", "N/A"))
        lines.append("")

        # Risks & catalysts
        risks = pick.get("key_risks", [])
        if risks:
            lines.append("### Key Risks ⚠️")
            for risk in risks:
                lines.append(f"- {risk}")
            lines.append("")

        catalysts = pick.get("catalysts", [])
        if catalysts:
            lines.append("### Catalysts 🚀")
            for catalyst in catalysts:
                lines.append(f"- {catalyst}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Methodology
    lines.append("## 📐 Methodology")
    lines.append("")
    lines.append("This analysis uses **Warren Buffett's Owner Earnings DCF Model**:")
    lines.append("")
    lines.append("```")
    lines.append("Owner Earnings = Net Income + D&A - Maintenance CapEx")
    lines.append(f"Maintenance CapEx = {MAINTENANCE_CAPEX_RATIO:.0%} of Total CapEx")
    lines.append("")
    lines.append(f"Intrinsic Value = Σ (Owner Earnings × (1+g)^t) / (1+r)^t + Terminal Value")
    lines.append(f"  Discount Rate (r): {DISCOUNT_RATE:.0%}")
    lines.append(f"  Terminal Growth: {TERMINAL_GROWTH_RATE:.1%}")
    lines.append(f"  Projection Period: {DCF_PROJECTION_YEARS} years")
    lines.append(f"  Minimum Margin of Safety: {MARGIN_OF_SAFETY_THRESHOLD:.0%}")
    lines.append("```")
    lines.append("")
    lines.append("**Scoring Weights:**")
    lines.append("- 40% — Margin of Safety (valuation discount)")
    lines.append("- 30% — Financial Health (8 quality checks)")
    lines.append("- 30% — Qualitative Analysis (moat, management, industry)")
    lines.append("")

    # Disclaimer
    lines.append("## ⚠️ Disclaimer")
    lines.append("")
    lines.append(
        "*This report is generated by an automated analysis system for educational "
        "and informational purposes only. It does not constitute investment advice, "
        "a recommendation, or a solicitation to buy or sell any securities. Past "
        "performance is not indicative of future results. All investments carry risk, "
        "including the possible loss of principal. Always conduct your own research "
        "and consult with a qualified financial advisor before making investment decisions.*"
    )
    lines.append("")
    lines.append(f"---")
    lines.append(f"*Report generated on {now.strftime('%B %d, %Y at %I:%M %p ET')} "
                 f"by TSX Stock Analyst Agent v1.0*")

    # ── Save the report ─────────────────────────────────────────────────────
    report_content = "\n".join(lines)
    report_path = REPORTS_DIR / f"{date_str}_tsx_analysis.md"

    # If a report already exists for today, add a timestamp suffix
    if report_path.exists():
        timestamp = now.strftime("%H%M%S")
        report_path = REPORTS_DIR / f"{date_str}_{timestamp}_tsx_analysis.md"

    report_path.write_text(report_content, encoding="utf-8")
    logger.info(f"Report saved to {report_path}")

    return str(report_path)
