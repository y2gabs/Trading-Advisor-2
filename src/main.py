"""
TSX Stock Analyst Agent — Main Orchestrator.

Runs the full analysis pipeline:
1. Load TSX stock universe
2. Fetch financial data
3. Calculate intrinsic values (Buffett DCF)
4. Score financial health
5. Rank & select top candidates
6. Deep research via Perplexity
7. Synthesize & select top 5 via Claude (or output JSON for Claude Code Routine)
8. Generate report

Supports two modes:
  --mode full     : Uses Claude API for final synthesis (needs ANTHROPIC_API_KEY)
  --mode routine  : Outputs candidate JSON for Claude Code Routine to synthesize
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

# Fix Windows console encoding for Unicode symbols
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.config import (
    LOG_LEVEL,
    TOP_CANDIDATES_FOR_RESEARCH,
    FINAL_TOP_PICKS,
    REPORTS_DIR,
)
from src.data.tsx_universe import load_tsx_universe
from src.data.financial_data import fetch_all_stock_data, StockData
from src.analysis.buffett_valuation import calculate_intrinsic_value, ValuationResult
from src.analysis.financial_health import evaluate_financial_health, FinancialHealthScore
from src.analysis.scoring import (
    score_and_rank,
    select_top_candidates,
    update_qualitative_scores,
    ScoredStock,
)
from src.research.perplexity_agent import research_stock
from src.reporting.report_generator import generate_report
from src.reporting.email_sender import send_report_email

# ── Configure logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def _build_financial_context(stock: StockData, valuation: ValuationResult) -> str:
    """Build a brief financial context string for research prompts."""
    parts = [
        f"Market Cap: ${stock.market_cap/1e9:.1f}B",
        f"P/E: {stock.pe_ratio:.1f}" if stock.pe_ratio else None,
        f"ROE: {stock.avg_roe:.1%}" if stock.avg_roe else None,
        f"D/E: {stock.debt_to_equity:.2f}" if stock.debt_to_equity != float('inf') else None,
        f"Div Yield: {stock.dividend_yield:.1%}" if stock.dividend_yield else None,
        f"Intrinsic Value: ${valuation.intrinsic_value_per_share:.2f}",
        f"Current Price: ${stock.current_price:.2f}",
        f"Margin of Safety: {valuation.margin_of_safety:.1%}",
        f"Owner Earnings (avg): ${valuation.avg_owner_earnings:,.0f}",
        f"Growth Rate: {valuation.estimated_growth_rate:.1%}",
    ]
    return " | ".join(p for p in parts if p)


def _serialize_candidate(candidate: ScoredStock) -> Dict:
    """Serialize a ScoredStock into a JSON-friendly dict for routine mode."""
    v = candidate.valuation
    h = candidate.health
    s = candidate.stock_data

    return {
        "ticker": candidate.ticker,
        "name": candidate.name,
        "sector": candidate.sector,
        "composite_score": round(candidate.composite_score, 4),
        "rank": candidate.rank,
        "current_price": round(v.current_price, 2) if v else 0,
        "intrinsic_value": round(v.intrinsic_value_per_share, 2) if v else 0,
        "intrinsic_value_conservative": round(v.intrinsic_value_conservative, 2) if v else 0,
        "margin_of_safety": round(v.margin_of_safety, 4) if v else 0,
        "margin_of_safety_conservative": round(v.margin_of_safety_conservative, 4) if v else 0,
        "estimated_growth_rate": round(v.estimated_growth_rate, 4) if v else 0,
        "avg_owner_earnings": round(v.avg_owner_earnings, 0) if v else 0,
        "earnings_cagr": round(v.earnings_growth_cagr, 4) if v else 0,
        "revenue_cagr": round(v.revenue_growth_cagr, 4) if v else 0,
        "valuation_confidence": v.valuation_confidence if v else "low",
        "health_grade": h.grade if h else "N/A",
        "health_score": round(h.overall_score, 3) if h else 0,
        "health_checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "score": round(c.score, 2),
                "detail": c.detail,
            }
            for c in h.checks
        ] if h else [],
        "market_cap": s.market_cap if s else 0,
        "pe_ratio": round(s.pe_ratio, 2) if s else 0,
        "pb_ratio": round(s.pb_ratio, 2) if s else 0,
        "avg_roe": round(s.avg_roe, 4) if s else 0,
        "debt_to_equity": round(s.debt_to_equity, 3) if s and s.debt_to_equity != float('inf') else None,
        "current_ratio": round(s.current_ratio, 3) if s and s.current_ratio != float('inf') else None,
        "dividend_yield": round(s.dividend_yield, 4) if s else 0,
        "industry": s.industry if s else "Unknown",
        "perplexity_research": candidate.perplexity_research or {},
    }


def run_analysis(
    force_refresh_universe: bool = False,
    mode: str = "full",
    send_email: bool = True,
):
    """
    Run the complete TSX stock analysis pipeline.

    Args:
        force_refresh_universe: If True, rebuild the TSX ticker cache.
        mode: "full" (uses Claude API for synthesis) or
              "routine" (outputs JSON for Claude Code Routine to synthesize).
        send_email: If True, email the report after generation.
    """
    start_time = time.time()

    logger.info("=" * 70)
    logger.info("  TSX STOCK ANALYST AGENT — Warren Buffett Intrinsic Value Model")
    logger.info(f"  Run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
    logger.info(f"  Mode: {mode}")
    logger.info("=" * 70)

    # ── Phase 1: Load TSX Universe ──────────────────────────────────────────
    logger.info("")
    logger.info("━━━ PHASE 1: Loading TSX Stock Universe ━━━")
    universe = load_tsx_universe(force_refresh=force_refresh_universe)
    if not universe:
        logger.error("Failed to load TSX universe. Aborting.")
        return
    logger.info(f"Universe loaded: {len(universe)} stocks")

    # ── Phase 2: Fetch Financial Data ───────────────────────────────────────
    logger.info("")
    logger.info("━━━ PHASE 2: Fetching Financial Data ━━━")

    def progress(current, total, ticker):
        logger.info(f"  [{current}/{total}] Fetching {ticker}...")

    stocks = fetch_all_stock_data(universe, progress_callback=progress)
    if not stocks:
        logger.error("No stocks with sufficient financial data. Aborting.")
        return
    logger.info(f"Financial data collected for {len(stocks)} stocks")

    # ── Phase 3: Calculate Intrinsic Values ─────────────────────────────────
    logger.info("")
    logger.info("━━━ PHASE 3: Calculating Intrinsic Values (Buffett DCF) ━━━")
    valuations: Dict[str, ValuationResult] = {}
    for stock in stocks:
        result = calculate_intrinsic_value(stock)
        if result:
            valuations[stock.ticker] = result

    logger.info(f"Valuations computed for {len(valuations)} stocks")
    undervalued = sum(1 for v in valuations.values() if v.is_undervalued)
    mos_pass = sum(1 for v in valuations.values() if v.passes_margin_of_safety)
    logger.info(f"  Undervalued: {undervalued} | Pass 30% MoS: {mos_pass}")

    # ── Phase 4: Score Financial Health ─────────────────────────────────────
    logger.info("")
    logger.info("━━━ PHASE 4: Evaluating Financial Health ━━━")
    health_scores: Dict[str, FinancialHealthScore] = {}
    for stock in stocks:
        health = evaluate_financial_health(stock)
        health_scores[stock.ticker] = health

    grade_dist = {}
    for h in health_scores.values():
        grade_dist[h.grade] = grade_dist.get(h.grade, 0) + 1
    logger.info(f"Health grades: {grade_dist}")

    # ── Phase 5: Score & Rank ───────────────────────────────────────────────
    logger.info("")
    logger.info("━━━ PHASE 5: Scoring & Ranking ━━━")
    scored = score_and_rank(stocks, valuations, health_scores)
    if not scored:
        logger.error("No undervalued stocks found. Aborting.")
        return

    top_candidates = select_top_candidates(scored)

    # ── Phase 6: Deep Research via Perplexity ───────────────────────────────
    logger.info("")
    logger.info("━━━ PHASE 6: Deep Research via Perplexity ━━━")
    qualitative_scores = {}

    for i, candidate in enumerate(top_candidates):
        ticker = candidate.ticker
        logger.info(f"  [{i+1}/{len(top_candidates)}] Researching {ticker} ({candidate.name})...")

        financial_context = _build_financial_context(candidate.stock_data, candidate.valuation)

        research = research_stock(
            ticker=ticker,
            name=candidate.name,
            sector=candidate.sector,
            financial_context=financial_context,
        )

        candidate.perplexity_research = research
        qualitative_scores[ticker] = research.get("qualitative_score", 0.5)

        # Rate limiting between calls
        if i < len(top_candidates) - 1:
            time.sleep(1.0)

    # Update scores with qualitative data
    top_candidates = update_qualitative_scores(top_candidates, qualitative_scores)

    elapsed = time.time() - start_time

    # ── MODE SPLIT ──────────────────────────────────────────────────────────

    if mode == "routine":
        # ── Routine Mode: Output JSON for Claude Code to synthesize ─────────
        logger.info("")
        logger.info("━━━ PHASE 7: Exporting Candidate Data (Routine Mode) ━━━")

        output_data = {
            "generated_at": datetime.now().isoformat(),
            "pipeline_duration_seconds": round(elapsed, 1),
            "universe_size": len(universe),
            "stocks_analyzed": len(stocks),
            "undervalued_count": undervalued,
            "candidates_researched": len(top_candidates),
            "candidates": [_serialize_candidate(c) for c in top_candidates],
        }

        # Save to JSON
        output_path = REPORTS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_candidates.json"
        if output_path.exists():
            timestamp = datetime.now().strftime("%H%M%S")
            output_path = REPORTS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}_{timestamp}_candidates.json"

        output_path.write_text(json.dumps(output_data, indent=2, default=str), encoding="utf-8")

        logger.info(f"Candidate data exported to: {output_path}")
        logger.info("")
        logger.info("=" * 70)
        logger.info("  PIPELINE COMPLETE (Routine Mode)")
        logger.info(f"  Candidates exported: {output_path}")
        logger.info(f"  Duration: {elapsed/60:.1f} minutes")
        logger.info("")
        logger.info("  Claude Code Routine will now synthesize the top 5 picks")
        logger.info("  and generate the final report.")
        logger.info("=" * 70)

        # Also print the JSON path to stdout for Claude Code to pick up
        print(f"\n[ROUTINE_OUTPUT] {output_path}")

        return str(output_path)

    else:
        # ── Full Mode: Use Claude API for synthesis ─────────────────────────
        from src.research.claude_analyst import analyze_and_select_top_picks

        logger.info("")
        logger.info("━━━ PHASE 7: Claude AI Final Analysis ━━━")
        claude_result = analyze_and_select_top_picks(top_candidates)

        # ── Phase 8: Generate Report ────────────────────────────────────────
        logger.info("")
        logger.info("━━━ PHASE 8: Generating Report ━━━")

        report_path = generate_report(
            claude_analysis=claude_result,
            candidates=top_candidates,
            universe_size=len(universe),
            stocks_analyzed=len(stocks),
            undervalued_count=undervalued,
            run_duration_seconds=elapsed,
        )

        # ── Phase 9: Email Report ───────────────────────────────────────────
        if send_email:
            logger.info("")
            logger.info("━━━ PHASE 9: Emailing Report ━━━")
            send_report_email(report_path)

        # ── Summary ─────────────────────────────────────────────────────────
        logger.info("")
        logger.info("=" * 70)
        logger.info("  ANALYSIS COMPLETE")
        logger.info(f"  Report saved: {report_path}")
        logger.info(f"  Duration: {elapsed/60:.1f} minutes")
        logger.info("")

        top_picks = claude_result.get("top_picks", [])
        if top_picks:
            logger.info(f"  TOP {len(top_picks)} PICKS:")
            for pick in top_picks:
                logger.info(
                    f"    #{pick['rank']} {pick['ticker']} ({pick['name']}) "
                    f"— {pick['conviction']} conviction, "
                    f"{pick.get('position_size_pct', 0):.0f}% position"
                )

        logger.info("=" * 70)

        return report_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="TSX Stock Analyst Agent — Buffett Intrinsic Value Analysis"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force refresh the TSX ticker universe cache",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "routine"],
        default="routine",
        help=(
            "full: Uses Claude API for final synthesis (needs ANTHROPIC_API_KEY). "
            "routine: Outputs candidate JSON for Claude Code Routine to synthesize "
            "(default, no Anthropic key needed)."
        ),
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip sending the email after report generation",
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    run_analysis(
        force_refresh_universe=args.refresh,
        mode=args.mode,
        send_email=not args.no_email,
    )
