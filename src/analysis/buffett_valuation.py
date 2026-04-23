"""
Buffett Intrinsic Value Calculator.

Implements Warren Buffett's Owner Earnings DCF model to estimate the
intrinsic value of a stock and calculate the margin of safety.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from src.data.financial_data import StockData
from src.config import (
    DISCOUNT_RATE,
    TERMINAL_GROWTH_RATE,
    DCF_PROJECTION_YEARS,
    MAINTENANCE_CAPEX_RATIO,
    MARGIN_OF_SAFETY_THRESHOLD,
)

logger = logging.getLogger(__name__)


@dataclass
class ValuationResult:
    """Result of the Buffett intrinsic value calculation."""
    ticker: str
    name: str

    # Owner Earnings
    avg_owner_earnings: float = 0.0
    latest_owner_earnings: float = 0.0
    owner_earnings_history: list = None

    # Growth
    estimated_growth_rate: float = 0.0
    earnings_growth_cagr: float = 0.0
    revenue_growth_cagr: float = 0.0

    # Intrinsic Value
    intrinsic_value_per_share: float = 0.0
    intrinsic_value_conservative: float = 0.0  # With lower growth assumption
    current_price: float = 0.0

    # Margin of Safety
    margin_of_safety: float = 0.0  # As decimal (0.30 = 30%)
    margin_of_safety_conservative: float = 0.0

    # DCF components
    pv_of_cash_flows: float = 0.0
    terminal_value: float = 0.0
    total_intrinsic_value: float = 0.0

    # Quality flags
    is_undervalued: bool = False
    passes_margin_of_safety: bool = False
    valuation_confidence: str = "low"  # "high", "medium", "low"

    def __post_init__(self):
        if self.owner_earnings_history is None:
            self.owner_earnings_history = []


def _calculate_owner_earnings(stock: StockData) -> list:
    """
    Calculate Owner Earnings for each year.

    Owner Earnings = Net Income + D&A - Maintenance CapEx
    
    Maintenance CapEx is estimated as MAINTENANCE_CAPEX_RATIO of total CapEx.
    """
    owner_earnings = []
    years = min(
        len(stock.net_income),
        len(stock.depreciation_amortization) if stock.depreciation_amortization else len(stock.net_income),
        len(stock.capital_expenditures) if stock.capital_expenditures else len(stock.net_income),
    )

    for i in range(years):
        ni = stock.net_income[i]
        da = stock.depreciation_amortization[i] if i < len(stock.depreciation_amortization) else 0.0
        capex = stock.capital_expenditures[i] if i < len(stock.capital_expenditures) else 0.0

        maintenance_capex = capex * MAINTENANCE_CAPEX_RATIO
        oe = ni + da - maintenance_capex
        owner_earnings.append(oe)

    return owner_earnings


def _calculate_cagr(values: list, reverse: bool = True) -> float:
    """
    Calculate Compound Annual Growth Rate.
    
    Financial data from yfinance is typically ordered most recent first,
    so we reverse by default.
    """
    if len(values) < 2:
        return 0.0

    # Filter out zeros and negatives
    valid = [v for v in values if v and v > 0]
    if len(valid) < 2:
        return 0.0

    if reverse:
        valid = list(reversed(valid))

    beginning = valid[0]
    ending = valid[-1]
    years = len(valid) - 1

    if beginning <= 0 or ending <= 0 or years <= 0:
        return 0.0

    try:
        cagr = (ending / beginning) ** (1 / years) - 1
        return cagr
    except (ZeroDivisionError, ValueError):
        return 0.0


def _estimate_sustainable_growth(stock: StockData) -> float:
    """
    Estimate sustainable growth rate using multiple approaches:
    1. Historical earnings CAGR
    2. Sustainable growth = ROE × retention ratio
    3. Revenue CAGR
    
    Returns a conservative weighted average.
    """
    # Approach 1: Earnings CAGR
    earnings_cagr = _calculate_cagr(stock.net_income)

    # Approach 2: Sustainable growth from ROE
    avg_roe = stock.avg_roe
    # Estimate retention ratio (assume ~60% retention if no dividend data)
    retention = 1.0 - min(stock.dividend_yield, 0.10)  # Cap at 10% yield
    sustainable_growth = avg_roe * retention if avg_roe > 0 else 0.0

    # Approach 3: Revenue CAGR
    revenue_cagr = _calculate_cagr(stock.revenue)

    # Weighted average with conservatism bias
    growth_estimates = []
    if earnings_cagr > 0:
        growth_estimates.append(earnings_cagr * 0.4)
    if sustainable_growth > 0:
        growth_estimates.append(sustainable_growth * 0.35)
    if revenue_cagr > 0:
        growth_estimates.append(revenue_cagr * 0.25)

    if not growth_estimates:
        return 0.03  # Default 3% if no data

    raw_growth = sum(growth_estimates) / sum([0.4, 0.35, 0.25][:len(growth_estimates)]) * len(growth_estimates)

    # Cap growth rate: Buffett prefers conservative estimates
    # Max at 15%, floor at 2%
    capped = max(0.02, min(raw_growth, 0.15))

    return capped


def _dcf_valuation(
    base_owner_earnings: float,
    growth_rate: float,
    discount_rate: float = DISCOUNT_RATE,
    terminal_growth: float = TERMINAL_GROWTH_RATE,
    projection_years: int = DCF_PROJECTION_YEARS,
) -> tuple:
    """
    Run a DCF valuation using Owner Earnings.

    Returns:
        (total_intrinsic_value, pv_of_cash_flows, terminal_value)
    """
    if base_owner_earnings <= 0:
        return 0.0, 0.0, 0.0

    # Phase 1: Present value of projected cash flows
    pv_cash_flows = 0.0
    projected_oe = base_owner_earnings

    for year in range(1, projection_years + 1):
        projected_oe *= (1 + growth_rate)
        pv = projected_oe / ((1 + discount_rate) ** year)
        pv_cash_flows += pv

    # Phase 2: Terminal value (Gordon Growth Model)
    terminal_cf = projected_oe * (1 + terminal_growth)
    if discount_rate <= terminal_growth:
        # Safety check: discount must exceed terminal growth
        terminal_value = projected_oe * 10  # Fallback: 10x final year
    else:
        terminal_value = terminal_cf / (discount_rate - terminal_growth)

    pv_terminal = terminal_value / ((1 + discount_rate) ** projection_years)

    total = pv_cash_flows + pv_terminal

    return total, pv_cash_flows, pv_terminal


def calculate_intrinsic_value(stock: StockData) -> Optional[ValuationResult]:
    """
    Calculate the intrinsic value of a stock using Buffett's Owner Earnings DCF.

    Args:
        stock: StockData object with financial history.

    Returns:
        ValuationResult or None if calculation is not possible.
    """
    if not stock.has_sufficient_data:
        return None

    result = ValuationResult(
        ticker=stock.ticker,
        name=stock.name,
        current_price=stock.current_price,
    )

    # ── Step 1: Calculate Owner Earnings history ────────────────────────────
    result.owner_earnings_history = _calculate_owner_earnings(stock)

    if not result.owner_earnings_history:
        logger.debug(f"  {stock.ticker}: cannot calculate owner earnings")
        return None

    # Use average of last 3 years for stability (Buffett prefers smoothed data)
    recent_oe = result.owner_earnings_history[:3]  # Most recent 3 years
    valid_oe = [oe for oe in recent_oe if oe > 0]

    if not valid_oe:
        logger.debug(f"  {stock.ticker}: negative owner earnings — skipping")
        return None

    result.avg_owner_earnings = np.mean(valid_oe)
    result.latest_owner_earnings = result.owner_earnings_history[0]

    # ── Step 2: Estimate growth rate ────────────────────────────────────────
    result.estimated_growth_rate = _estimate_sustainable_growth(stock)
    result.earnings_growth_cagr = _calculate_cagr(stock.net_income)
    result.revenue_growth_cagr = _calculate_cagr(stock.revenue)

    # ── Step 3: Run DCF — Base case ─────────────────────────────────────────
    total_iv, pv_cf, tv = _dcf_valuation(
        base_owner_earnings=result.avg_owner_earnings,
        growth_rate=result.estimated_growth_rate,
    )

    result.pv_of_cash_flows = pv_cf
    result.terminal_value = tv
    result.total_intrinsic_value = total_iv

    # Per-share intrinsic value
    if stock.shares_outstanding > 0:
        result.intrinsic_value_per_share = total_iv / stock.shares_outstanding
    else:
        logger.debug(f"  {stock.ticker}: no shares outstanding data")
        return None

    # ── Step 4: Run DCF — Conservative case (half growth rate) ──────────────
    conservative_growth = result.estimated_growth_rate * 0.5
    total_iv_c, _, _ = _dcf_valuation(
        base_owner_earnings=result.avg_owner_earnings,
        growth_rate=conservative_growth,
    )
    if stock.shares_outstanding > 0:
        result.intrinsic_value_conservative = total_iv_c / stock.shares_outstanding

    # ── Step 5: Calculate Margin of Safety ──────────────────────────────────
    if result.intrinsic_value_per_share > 0:
        result.margin_of_safety = (
            (result.intrinsic_value_per_share - stock.current_price)
            / result.intrinsic_value_per_share
        )
    if result.intrinsic_value_conservative > 0:
        result.margin_of_safety_conservative = (
            (result.intrinsic_value_conservative - stock.current_price)
            / result.intrinsic_value_conservative
        )

    # ── Step 6: Determine if undervalued ────────────────────────────────────
    result.is_undervalued = result.margin_of_safety > 0
    result.passes_margin_of_safety = result.margin_of_safety >= MARGIN_OF_SAFETY_THRESHOLD

    # ── Step 7: Confidence level ────────────────────────────────────────────
    if (
        stock.data_quality == "good"
        and len(valid_oe) >= 3
        and result.margin_of_safety_conservative > 0
    ):
        result.valuation_confidence = "high"
    elif stock.data_quality in ("good", "partial") and result.margin_of_safety > 0:
        result.valuation_confidence = "medium"
    else:
        result.valuation_confidence = "low"

    logger.info(
        f"  {stock.ticker}: IV=${result.intrinsic_value_per_share:.2f} vs "
        f"Price=${stock.current_price:.2f} → "
        f"MoS={result.margin_of_safety:.1%} "
        f"({'✓ PASS' if result.passes_margin_of_safety else '✗ FAIL'})"
    )

    return result
