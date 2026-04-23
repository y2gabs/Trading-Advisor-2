"""
Composite Scoring Engine.

Combines valuation margin-of-safety, financial health score, and
qualitative research score into a single ranked list.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from src.data.financial_data import StockData
from src.analysis.buffett_valuation import ValuationResult
from src.analysis.financial_health import FinancialHealthScore
from src.config import (
    WEIGHT_MARGIN_OF_SAFETY,
    WEIGHT_FINANCIAL_HEALTH,
    WEIGHT_QUALITATIVE,
    TOP_CANDIDATES_FOR_RESEARCH,
)

logger = logging.getLogger(__name__)


@dataclass
class ScoredStock:
    """A stock with all analysis results and a composite score."""
    ticker: str
    name: str
    sector: str

    # Component scores (0.0 to 1.0)
    margin_of_safety_score: float = 0.0
    financial_health_score: float = 0.0
    qualitative_score: float = 0.5  # Default neutral until research is done

    # Composite
    composite_score: float = 0.0
    rank: int = 0

    # References to full analysis
    stock_data: Optional[StockData] = None
    valuation: Optional[ValuationResult] = None
    health: Optional[FinancialHealthScore] = None

    # Research data (populated later)
    perplexity_research: Optional[Dict[str, Any]] = None
    claude_analysis: Optional[Dict[str, Any]] = None


def _normalize_margin_of_safety(mos: float) -> float:
    """
    Convert margin of safety to a 0-1 score.
    
    MoS >= 60% → 1.0 (exceptional)
    MoS >= 30% → 0.7-1.0 (strong)
    MoS >= 10% → 0.3-0.7 (moderate)
    MoS < 10%  → 0.0-0.3 (weak)
    MoS < 0    → 0.0 (overvalued)
    """
    if mos <= 0:
        return 0.0
    elif mos >= 0.60:
        return 1.0
    elif mos >= 0.30:
        return 0.7 + 0.3 * (mos - 0.30) / 0.30
    elif mos >= 0.10:
        return 0.3 + 0.4 * (mos - 0.10) / 0.20
    else:
        return 0.3 * (mos / 0.10)


def score_and_rank(
    stocks: List[StockData],
    valuations: Dict[str, ValuationResult],
    health_scores: Dict[str, FinancialHealthScore],
) -> List[ScoredStock]:
    """
    Score and rank all stocks based on valuation and financial health.

    Qualitative score starts at 0.5 (neutral) and gets updated after
    Perplexity/Claude research on the top candidates.

    Args:
        stocks: List of StockData objects
        valuations: Dict mapping ticker -> ValuationResult
        health_scores: Dict mapping ticker -> FinancialHealthScore

    Returns:
        Sorted list of ScoredStock (best first), filtered to those
        that pass minimum criteria.
    """
    scored = []

    for stock in stocks:
        ticker = stock.ticker
        valuation = valuations.get(ticker)
        health = health_scores.get(ticker)

        if not valuation or not health:
            continue

        # Skip stocks that don't pass minimum criteria
        if not valuation.is_undervalued:
            logger.debug(f"  Skipping {ticker}: overvalued (MoS={valuation.margin_of_safety:.1%})")
            continue

        entry = ScoredStock(
            ticker=ticker,
            name=stock.name,
            sector=stock.sector,
            stock_data=stock,
            valuation=valuation,
            health=health,
        )

        # Score components
        entry.margin_of_safety_score = _normalize_margin_of_safety(valuation.margin_of_safety)
        entry.financial_health_score = health.overall_score
        # qualitative_score stays at 0.5 default for now

        # Composite score (qualitative gets updated later for top candidates)
        entry.composite_score = (
            entry.margin_of_safety_score * WEIGHT_MARGIN_OF_SAFETY
            + entry.financial_health_score * WEIGHT_FINANCIAL_HEALTH
            + entry.qualitative_score * WEIGHT_QUALITATIVE
        )

        scored.append(entry)

    # Sort by composite score (descending)
    scored.sort(key=lambda s: s.composite_score, reverse=True)

    # Assign ranks
    for i, s in enumerate(scored):
        s.rank = i + 1

    logger.info(
        f"Scored {len(scored)} undervalued stocks. "
        f"Top candidate: {scored[0].ticker if scored else 'N/A'} "
        f"(score={scored[0].composite_score:.3f})" if scored else ""
    )

    return scored


def select_top_candidates(scored: List[ScoredStock]) -> List[ScoredStock]:
    """Select the top N candidates for deep research."""
    top = scored[:TOP_CANDIDATES_FOR_RESEARCH]
    logger.info(f"Selected top {len(top)} candidates for deep research:")
    for s in top:
        logger.info(
            f"  #{s.rank} {s.ticker} ({s.name}) — "
            f"Composite: {s.composite_score:.3f}, "
            f"MoS: {s.valuation.margin_of_safety:.1%}, "
            f"Health: {s.health.grade}"
        )
    return top


def update_qualitative_scores(
    candidates: List[ScoredStock],
    qualitative_scores: Dict[str, float],
) -> List[ScoredStock]:
    """
    Update candidates with qualitative scores from research and re-rank.

    Args:
        candidates: List of ScoredStock to update
        qualitative_scores: Dict mapping ticker -> qualitative score (0.0 to 1.0)

    Returns:
        Re-ranked list of ScoredStock.
    """
    for candidate in candidates:
        if candidate.ticker in qualitative_scores:
            candidate.qualitative_score = qualitative_scores[candidate.ticker]

            # Recalculate composite
            candidate.composite_score = (
                candidate.margin_of_safety_score * WEIGHT_MARGIN_OF_SAFETY
                + candidate.financial_health_score * WEIGHT_FINANCIAL_HEALTH
                + candidate.qualitative_score * WEIGHT_QUALITATIVE
            )

    # Re-sort and re-rank
    candidates.sort(key=lambda s: s.composite_score, reverse=True)
    for i, s in enumerate(candidates):
        s.rank = i + 1

    return candidates
