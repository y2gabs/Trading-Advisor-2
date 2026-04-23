# TSX Stock Analyst Agent

## Purpose
This is an automated stock analysis agent that screens TSX-listed stocks using Warren Buffett's intrinsic value model and recommends the top 5 undervalued investment ideas. Results are emailed daily.

## Tech Stack
- **Python 3.10+** with yfinance, openai (for Perplexity)
- **Perplexity Sonar API** for web-grounded qualitative research
- **yfinance** for financial data (no API key needed)
- **Gmail SMTP** for email delivery (via Python smtplib + App Password)

## Environment Variables (REQUIRED for routine)
The following must be set as environment variables in the routine settings at claude.ai/code/routines:
```
PERPLEXITY_API_KEY=pplx-xxxxx
GMAIL_ADDRESS=your.email@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```
To get a Gmail App Password: https://myaccount.google.com/apppasswords
(Requires 2-Step Verification enabled on the Google account)

## How to Run

### Routine Mode (default)
```bash
python -m src.main
```

### Full Mode (standalone, needs Anthropic API key)
```bash
python -m src.main --mode full
```

### Other Options
```bash
python -m src.main --refresh    # Force refresh the TSX ticker cache
python -m src.main --debug      # Enable debug logging
```

## Key Files
- `src/main.py` — Main orchestrator (entry point)
- `src/config.py` — All configuration and parameters
- `src/data/tsx_universe.py` — TSX stock universe loader
- `src/data/financial_data.py` — yfinance data collector
- `src/analysis/buffett_valuation.py` — Owner Earnings DCF engine
- `src/analysis/financial_health.py` — Buffett quality filters
- `src/analysis/scoring.py` — Composite scoring & ranking
- `src/research/perplexity_agent.py` — Perplexity Sonar research
- `src/research/claude_analyst.py` — Claude synthesis engine (full mode only)
- `src/reporting/report_generator.py` — Markdown report generator

## Output
- **Routine mode**: `reports/YYYY-MM-DD_candidates.json`
- **Full mode**: `reports/YYYY-MM-DD_tsx_analysis.md`

---

## 📧 Routine Instructions (for Claude Code)

### IMPORTANT: Handling API Failures

If `python -m src.main` fails due to HTTP 403 errors, blocked APIs, or missing `.env` file, DO NOT give up. Instead, follow the **Fallback Procedure** below.

### Primary Flow (if Python pipeline works)

1. Run `python -m src.main`
2. Read the output JSON
3. Select top 5, write analysis, generate report, and save to `reports/`
4. Send the email by running:
   ```python
   from src.reporting.email_sender import send_report_email
   send_report_email("reports/YYYY-MM-DD_tsx_analysis.md")
   ```

### Fallback Procedure (if Python pipeline fails)

If yfinance or Perplexity APIs are blocked or the pipeline fails for any reason:

1. **Use Perplexity directly** (if available as a tool/connector) to research current TSX stock data:
   - Search for: "TSX stocks with lowest P/E ratios and highest ROE 2025"
   - Search for: "Most undervalued Canadian stocks Warren Buffett criteria"
   - Search for: "S&P TSX Composite stocks financial data earnings growth"
   - For each promising candidate, search for detailed financials, moat analysis, and recent news

2. **If Perplexity is also unavailable**, use your trained knowledge of TSX fundamentals to identify the top 5 undervalued stocks. Focus on:
   - Companies with consistent earnings growth
   - Strong ROE (>15%)
   - Low debt-to-equity
   - Durable competitive moats
   - Trading below estimated intrinsic value
   - **Be explicit that data is from training knowledge, not live data**

3. **Apply the Buffett valuation framework** regardless of data source:
   - Owner Earnings = Net Income + D&A - Maintenance CapEx
   - DCF with 10% discount rate, 2.5% terminal growth, 10-year projection
   - Require 30%+ margin of safety
   - Score financial health on 8 criteria

### Step-by-Step: Write the Analysis

For each of the Top 5 picks, write:
- **Conviction level**: High, Medium, or Low
- **Investment thesis**: 2-3 sentence summary
- **Detailed writeup**: 3-4 paragraph narrative explaining WHY you recommend this stock. Cover: what the company does, why it's undervalued, the competitive moat, management quality, and forward outlook. Use specific numbers.
- **Bull case**: Best-case scenario (2-3 sentences)
- **Bear case**: Worst-case scenario (2-3 sentences)
- **Key risks**: Top 3 specific risks
- **Catalysts**: What could unlock value in 12-24 months
- **Position sizing**: Suggested % of a $100K portfolio

Also write:
- **Market commentary**: 2-3 sentences on the current TSX environment
- **Sector themes**: Notable sector-level observations

### Step: Save the Report

Save the full markdown report to `reports/YYYY-MM-DD_tsx_analysis.md` with:
1. Executive summary table of top 5
2. Per-stock deep dives with writeups
3. Market commentary
4. Methodology notes
5. Data source disclaimer (indicate if live data or training knowledge was used)
6. Standard investment disclaimer

### Step: Email the Report

Send the email using the built-in Python email sender:
```python
from src.reporting.email_sender import send_report_email
send_report_email("reports/YYYY-MM-DD_tsx_analysis.md")
```
This will:
- Read the report markdown
- Convert it to a styled HTML email
- Send it via Gmail SMTP to jeff.gabrielson@outlook.com
- Subject line: "📊 TSX Value Report — Top 5 Picks for [today's date]"

If the report was generated from training knowledge (not live data), include a prominent note:
> ⚠️ Note: This analysis was generated using historical training data, not live market data. Prices and financials may not reflect current values. Please verify all data before making investment decisions.

---

## Important Rules
- Never modify the `.env` file — it contains API keys
- Always use the `src.config` module for parameters, never hardcode values
- Reports must include the disclaimer at the bottom
- Default mode is `routine` — no Anthropic API key needed
- ALWAYS send the email after generating the report — this is the primary delivery method
- ALWAYS attempt the Python pipeline first before falling back
- If using fallback data, ALWAYS disclose the data source clearly
