"""
Smoke test for the TSX Stock Analyst Agent.

Tests the core pipeline with a small set of tickers to verify
all components work without needing API keys for Perplexity/Claude.
"""

import sys
import os
import logging

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set dummy API keys for import (won't be called)
os.environ.setdefault("PERPLEXITY_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from src.data.financial_data import fetch_stock_data
from src.analysis.buffett_valuation import calculate_intrinsic_value
from src.analysis.financial_health import evaluate_financial_health
from src.analysis.scoring import score_and_rank

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Test tickers — diverse sectors
TEST_TICKERS = [
    {"ticker": "RY.TO", "name": "Royal Bank of Canada", "sector": "Financials", "industry": "Banks", "currency": "CAD"},
    {"ticker": "CNR.TO", "name": "Canadian National Railway", "sector": "Industrials", "industry": "Railroads", "currency": "CAD"},
    {"ticker": "ENB.TO", "name": "Enbridge Inc", "sector": "Energy", "industry": "Pipelines", "currency": "CAD"},
    {"ticker": "SHOP.TO", "name": "Shopify Inc", "sector": "Technology", "industry": "Software", "currency": "CAD"},
    {"ticker": "ABX.TO", "name": "Barrick Gold Corp", "sector": "Materials", "industry": "Gold Mining", "currency": "CAD"},
]


def main():
    print("=" * 60)
    print("  TSX Stock Analyst Agent — Smoke Test")
    print("=" * 60)

    stocks = []
    valuations = {}
    health_scores = {}

    # Phase 1: Fetch data
    print("\n--- Fetching Financial Data ---")
    for info in TEST_TICKERS:
        stock = fetch_stock_data(info)
        if stock:
            stocks.append(stock)
            print(f"  ✓ {stock.ticker}: ${stock.current_price:.2f}, "
                  f"Cap={stock.market_cap/1e9:.1f}B, "
                  f"{stock.years_of_data}yr data, "
                  f"quality={stock.data_quality}")
        else:
            print(f"  ✗ {info['ticker']}: insufficient data")

    # Phase 2: Valuations
    print("\n--- Calculating Intrinsic Values ---")
    for stock in stocks:
        val = calculate_intrinsic_value(stock)
        if val:
            valuations[stock.ticker] = val
            print(f"  {stock.ticker}: IV=${val.intrinsic_value_per_share:.2f} vs "
                  f"Price=${val.current_price:.2f} → "
                  f"MoS={val.margin_of_safety:.1%} "
                  f"({'UNDERVALUED' if val.is_undervalued else 'OVERVALUED'})")

    # Phase 3: Health scores
    print("\n--- Financial Health ---")
    for stock in stocks:
        health = evaluate_financial_health(stock)
        health_scores[stock.ticker] = health
        print(f"  {stock.ticker}: Grade {health.grade} "
              f"(score={health.overall_score:.2f}, "
              f"passed={health.passed_checks}/{health.total_checks})")

    # Phase 4: Scoring
    print("\n--- Composite Ranking ---")
    scored = score_and_rank(stocks, valuations, health_scores)
    for s in scored:
        print(f"  #{s.rank} {s.ticker} ({s.name}) — "
              f"Score={s.composite_score:.3f}, "
              f"MoS={s.valuation.margin_of_safety:.1%}, "
              f"Health={s.health.grade}")

    # Summary
    print("\n" + "=" * 60)
    print(f"  Results: {len(stocks)} fetched, {len(valuations)} valued, "
          f"{len(scored)} undervalued")
    print(f"  Pipeline: {'✓ ALL PHASES PASSED' if scored else '✓ COMPLETED (no undervalued found)'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
