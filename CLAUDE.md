# TSX Stock Analyst Agent

## Purpose
This is an automated stock analysis agent that screens TSX-listed stocks using Warren Buffett's intrinsic value model and recommends the top 5 undervalued investment ideas. Results are emailed daily.

## Tech Stack
- **Python 3.10+** with yfinance, openai (for Perplexity)
- **Perplexity Sonar API** for web-grounded qualitative research
- **yfinance** for financial data (no API key needed)
- **Gmail connector** for email delivery

## How to Run

### Routine Mode (default — for Claude Code Routines, no Anthropic key needed)
```bash
python -m src.main
```
This runs phases 1-6 (data collection, valuation, health scoring, Perplexity research) and outputs a structured JSON file to `reports/YYYY-MM-DD_candidates.json`. Claude Code (you) should then read this JSON, select the top 5 picks, write a detailed narrative writeup for each, generate the final markdown report, and email it.

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
- **Routine mode**: `reports/YYYY-MM-DD_candidates.json` (for Claude Code to process)
- **Full mode**: `reports/YYYY-MM-DD_tsx_analysis.md`

---

## 📧 Routine Instructions (for Claude Code)

When this routine runs, follow these steps IN ORDER:

### Step 1: Run the pipeline
```bash
python -m src.main
```
Wait for it to complete. Look for the `[ROUTINE_OUTPUT]` line in the output — it contains the path to the candidate JSON file.

### Step 2: Read the output JSON
Read the JSON file from the path printed in Step 1. It contains all the scored and researched candidates.

### Step 3: Select the Top 5
From the candidates, select the top 5 most compelling stocks using Warren Buffett's investment philosophy:
- Prioritize highest composite scores
- Favor stocks with the strongest margin of safety
- Weight the Perplexity research results (moat, management, industry outlook)
- Prefer businesses you'd be comfortable owning for 10+ years

### Step 4: Write the analysis
For each of the Top 5, write:
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

### Step 5: Generate the report
Write the full analysis as a markdown report and save it to `reports/YYYY-MM-DD_tsx_analysis.md`. Use the report format from `src/reporting/report_generator.py` as a reference — include the executive summary table, per-stock deep dives, methodology notes, and disclaimer.

### Step 6: Email the report
Use the **Gmail connector** to send the report via email:
- **To**: jeff.gabrielson@outlook.com
- **Subject**: "📊 TSX Value Report — Top 5 Picks for [today's date]"
- **Body**: Include the full report content formatted as a clean, readable email. Key sections to include:
  1. A quick summary table of the top 5 picks (ticker, company, price, intrinsic value, margin of safety, conviction)
  2. The detailed writeup for each stock
  3. Market commentary
  4. A brief methodology note
  5. The disclaimer

Make the email professional and scannable — use clear headings and formatting.

---

## Important Rules
- Never modify the `.env` file — it contains API keys
- Always use the `src.config` module for parameters, never hardcode values
- Reports must include the disclaimer at the bottom
- Default mode is `routine` — no Anthropic API key needed
- ALWAYS send the email after generating the report — this is the primary delivery method
