# 📊 TSX Stock Analyst Agent

An autonomous stock analysis agent that uses **Warren Buffett's intrinsic value model** to identify the top 5 most undervalued stocks on the Toronto Stock Exchange (TSX).

## ✨ Features

- **Warren Buffett's Owner Earnings DCF** — Calculates intrinsic value using owner earnings, not standard accounting metrics
- **8-Factor Financial Health Scoring** — Earnings consistency, ROE, debt levels, margin stability, FCF, and more
- **AI-Powered Research** — Uses Perplexity Sonar API for real-time web-grounded qualitative analysis (moat, management, industry outlook)
- **Intelligent Synthesis** — Claude AI evaluates all data through a Buffett investment lens to select the final top 5
- **Professional Reports** — Generates comprehensive markdown reports with detailed analysis per stock
- **Automated Scheduling** — Runs weekly via Claude Code Routines (cloud-based, works offline)

## 🏗 Architecture

```
TSX Universe → Financial Data → Buffett DCF → Health Scoring → 
Composite Ranking → Perplexity Research → Claude Analysis → Report
```

The pipeline analyzes ~230 S&P/TSX Composite stocks and narrows down to the top 5 most compelling undervalued picks.

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- [Perplexity API Key](https://www.perplexity.ai/)
- [Anthropic Claude API Key](https://console.anthropic.com)

### Setup

```bash
# 1. Navigate to project
cd "Trading Bot"

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys
copy .env.example .env
# Edit .env and add your API keys

# 5. Run analysis
python -m src.main
```

### Command Line Options

```bash
python -m src.main              # Full analysis
python -m src.main --refresh    # Force refresh TSX ticker cache
python -m src.main --debug      # Enable debug logging
```

## 📄 Output

Reports are saved to `reports/YYYY-MM-DD_tsx_analysis.md` and include:
- Executive summary with top 5 picks
- Detailed valuation breakdown per stock
- Financial health scorecard
- Qualitative research (moat, management, risks)
- Bull/bear cases and catalysts
- Methodology notes and disclaimer

## 🔄 Automated Scheduling (Claude Code Routines)

To schedule weekly runs via Claude Code:

1. Open Claude Code in this project directory
2. Run `/schedule` and configure:
   - **Cadence:** Weekly (Sunday at 8 PM)
   - **Prompt:** "Run the TSX stock analysis: `python -m src.main`"
   - **Execution:** Remote (cloud-based)

Or manage via the web UI at [claude.ai/code/routines](https://claude.ai/code/routines).

## ⚠️ Disclaimer

This tool is for educational and informational purposes only. It does not constitute investment advice. Always conduct your own research and consult a qualified financial advisor before making investment decisions.
