"""
Configuration module for the TSX Stock Analyst Agent.

Centralizes all environment variables, model settings, and
analysis parameters used throughout the pipeline.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Load environment variables ──────────────────────────────────────────────
load_dotenv()

# ── API Keys ────────────────────────────────────────────────────────────────
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")  # Only needed for --mode full

# ── Paths ───────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
TICKER_CACHE_FILE = DATA_DIR / "tsx_tickers.json"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Model Configuration ────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-20250514"
PERPLEXITY_MODEL = "sonar"  # Perplexity's web-grounded model

# ── TSX Universe Filters ────────────────────────────────────────────────────
MIN_MARKET_CAP = 500_000_000          # $500M CAD minimum
MIN_AVG_VOLUME = 50_000               # Minimum average daily volume
TICKER_CACHE_MAX_AGE_DAYS = 7         # Refresh ticker list weekly

# ── Buffett Valuation Parameters ────────────────────────────────────────────
DISCOUNT_RATE = 0.10                  # 10% — Buffett's typical hurdle rate
TERMINAL_GROWTH_RATE = 0.025          # 2.5% — long-term GDP-like growth
DCF_PROJECTION_YEARS = 10            # 10-year DCF projection
MAINTENANCE_CAPEX_RATIO = 0.65        # Assume 65% of total CapEx is maintenance
MARGIN_OF_SAFETY_THRESHOLD = 0.30     # 30% minimum margin of safety

# ── Financial Health Thresholds ─────────────────────────────────────────────
MIN_ROE = 0.15                        # 15% minimum average ROE
MAX_DEBT_TO_EQUITY = 1.0              # Maximum debt-to-equity ratio
PREFERRED_DEBT_TO_EQUITY = 0.5        # Preferred (lower) debt-to-equity
MIN_CURRENT_RATIO = 1.5               # Minimum current ratio
MIN_YEARS_FINANCIALS = 3              # Need at least 3 years of data

# ── Scoring Weights ─────────────────────────────────────────────────────────
WEIGHT_MARGIN_OF_SAFETY = 0.40
WEIGHT_FINANCIAL_HEALTH = 0.30
WEIGHT_QUALITATIVE = 0.30

# ── Pipeline Configuration ──────────────────────────────────────────────────
TOP_CANDIDATES_FOR_RESEARCH = 20      # Deep-research top N candidates
FINAL_TOP_PICKS = 5                   # Number of final recommendations
YFINANCE_RATE_LIMIT_DELAY = 0.5       # Seconds between yfinance calls
PERPLEXITY_RATE_LIMIT_DELAY = 1.0     # Seconds between Perplexity calls

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
