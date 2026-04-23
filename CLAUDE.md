# TSX Stock Analyst Agent

## Purpose
This is an automated stock analysis agent that screens TSX-listed stocks using Warren Buffett's intrinsic value model and recommends the top 5 undervalued investment ideas.

## Tech Stack
- **Python 3.10+** with yfinance, openai (for Perplexity)
- **Perplexity Sonar API** for web-grounded qualitative research
- **yfinance** for financial data (no API key needed)

## How to Run

### Routine Mode (default — for Claude Code Routines, no Anthropic key needed)
```bash
python -m src.main
```
This runs phases 1-6 (data collection, valuation, health scoring, Perplexity research) and outputs a structured JSON file to `reports/YYYY-MM-DD_candidates.json`. Claude Code (you) should then read this JSON, select the top 5 picks, write a detailed narrative writeup for each, and generate the final markdown report.

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

## Routine Instructions (for Claude Code)

When this routine runs, you should:

1. **Run the pipeline**: Execute `python -m src.main` (defaults to routine mode)
2. **Read the output JSON** from the file path printed at the end (look for `[ROUTINE_OUTPUT]` line)
3. **Select the Top 5** stocks from the candidates based on:
   - Highest composite scores
   - Strongest margin of safety
   - Best Perplexity research results (moat, management, industry outlook)
   - Apply Warren Buffett's investment philosophy
4. **For each of the Top 5**, write:
   - A conviction level (High/Medium/Low)
   - A 2-3 sentence investment thesis
   - A detailed 3-4 paragraph narrative writeup explaining WHY you recommend it
   - Bull case and bear case (2-3 sentences each)
   - Top 3 key risks
   - Upcoming catalysts
   - Suggested portfolio allocation (% of $100K)
5. **Generate the report** by calling:
   ```python
   python -c "
   from src.reporting.report_generator import generate_report
   import json
   claude_analysis = {your_analysis_json}
   # ... generate report
   "
   ```
   Or write the markdown report directly to `reports/YYYY-MM-DD_tsx_analysis.md`

## Important Rules
- Never modify the `.env` file — it contains API keys
- Always use the `src.config` module for parameters, never hardcode values
- Reports must include the disclaimer at the bottom
- Default mode is `routine` — no Anthropic API key needed
