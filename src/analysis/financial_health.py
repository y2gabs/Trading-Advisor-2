"""
Financial Health Analyzer.

Evaluates stocks against Buffett-style quality criteria including
earnings consistency, ROE, debt levels, and operating efficiency.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from src.data.financial_data import StockData
from src.config import (
    MIN_ROE,
    MAX_DEBT_TO_EQUITY,
    PREFERRED_DEBT_TO_EQUITY,
    MIN_CURRENT_RATIO,
)

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """Individual health check result."""
    name: str
    passed: bool
    score: float  # 0.0 to 1.0
    value: float  # The actual metric value
    threshold: str  # Description of the threshold
    detail: str  # Explanation


@dataclass
class FinancialHealthScore:
    """Composite financial health assessment."""
    ticker: str
    name: str
    overall_score: float = 0.0  # 0.0 to 1.0
    checks: List[HealthCheckResult] = field(default_factory=list)
    passed_checks: int = 0
    total_checks: int = 0
    grade: str = "F"  # A, B, C, D, F

    @property
    def pass_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return self.passed_checks / self.total_checks


def _check_earnings_consistency(stock: StockData) -> HealthCheckResult:
    """
    Check for consistent positive earnings growth.
    Buffett prefers companies with predictable, growing earnings.
    """
    if len(stock.net_income) < 3:
        return HealthCheckResult(
            name="Earnings Consistency",
            passed=False, score=0.0, value=0.0,
            threshold="≥3 years positive growth",
            detail="Insufficient earnings history"
        )

    # Reverse so oldest is first
    earnings = list(reversed(stock.net_income))
    positive_years = sum(1 for e in earnings if e > 0)
    total = len(earnings)

    # Check for growth trend
    growing_years = sum(1 for i in range(1, len(earnings)) if earnings[i] > earnings[i-1])

    consistency = positive_years / total
    growth_ratio = growing_years / (total - 1) if total > 1 else 0

    # Score: weighted combo of positive years + growth trend
    score = (consistency * 0.6) + (growth_ratio * 0.4)
    passed = consistency >= 0.8 and growth_ratio >= 0.4

    return HealthCheckResult(
        name="Earnings Consistency",
        passed=passed,
        score=score,
        value=consistency,
        threshold="≥80% positive years, ≥40% growing",
        detail=f"{positive_years}/{total} positive years, {growing_years}/{total-1} growth years"
    )


def _check_roe(stock: StockData) -> HealthCheckResult:
    """
    Check Return on Equity.
    Buffett typically requires ROE ≥ 15% averaged over several years.
    """
    avg_roe = stock.avg_roe

    if avg_roe >= MIN_ROE:
        score = min(1.0, avg_roe / 0.25)  # Perfect score at 25%+ ROE
        passed = True
    elif avg_roe >= 0.10:
        score = avg_roe / MIN_ROE * 0.7  # Partial credit
        passed = False
    else:
        score = max(0, avg_roe / MIN_ROE * 0.3)
        passed = False

    return HealthCheckResult(
        name="Return on Equity",
        passed=passed,
        score=score,
        value=avg_roe,
        threshold=f"≥{MIN_ROE:.0%} average",
        detail=f"Avg ROE: {avg_roe:.1%} over {len(stock.roe_history)} years"
    )


def _check_debt_levels(stock: StockData) -> HealthCheckResult:
    """
    Check debt-to-equity ratio.
    Buffett prefers low-debt companies (D/E ≤ 0.5 ideal, ≤ 1.0 acceptable).
    """
    de = stock.debt_to_equity

    if de == float('inf') or de < 0:
        return HealthCheckResult(
            name="Debt Levels",
            passed=False, score=0.0, value=de,
            threshold=f"D/E ≤ {MAX_DEBT_TO_EQUITY:.1f}",
            detail="Cannot calculate D/E (negative or zero equity)"
        )

    if de <= PREFERRED_DEBT_TO_EQUITY:
        score = 1.0
        passed = True
    elif de <= MAX_DEBT_TO_EQUITY:
        score = 0.7 + 0.3 * (1 - (de - PREFERRED_DEBT_TO_EQUITY) / (MAX_DEBT_TO_EQUITY - PREFERRED_DEBT_TO_EQUITY))
        passed = True
    elif de <= 1.5:
        score = 0.3
        passed = False
    else:
        score = max(0, 0.2 * (2.0 - de))
        passed = False

    return HealthCheckResult(
        name="Debt Levels",
        passed=passed,
        score=score,
        value=de,
        threshold=f"D/E ≤ {PREFERRED_DEBT_TO_EQUITY:.1f} (ideal), ≤ {MAX_DEBT_TO_EQUITY:.1f} (max)",
        detail=f"Debt-to-Equity: {de:.2f}"
    )


def _check_current_ratio(stock: StockData) -> HealthCheckResult:
    """
    Check current ratio (liquidity).
    Buffett looks for companies that can easily cover short-term obligations.
    """
    cr = stock.current_ratio

    if cr == float('inf'):
        return HealthCheckResult(
            name="Liquidity (Current Ratio)",
            passed=True, score=1.0, value=cr,
            threshold=f"≥ {MIN_CURRENT_RATIO:.1f}",
            detail="No current liabilities"
        )

    if cr >= MIN_CURRENT_RATIO:
        score = min(1.0, cr / 2.5)
        passed = True
    elif cr >= 1.0:
        score = 0.5 * (cr / MIN_CURRENT_RATIO)
        passed = False
    else:
        score = max(0, 0.2 * cr)
        passed = False

    return HealthCheckResult(
        name="Liquidity (Current Ratio)",
        passed=passed,
        score=score,
        value=cr,
        threshold=f"≥ {MIN_CURRENT_RATIO:.1f}",
        detail=f"Current Ratio: {cr:.2f}"
    )


def _check_operating_margin_stability(stock: StockData) -> HealthCheckResult:
    """
    Check operating margin stability.
    Buffett prefers businesses with stable, predictable margins (low variance).
    """
    margins = stock.operating_margin_history
    if len(margins) < 3:
        return HealthCheckResult(
            name="Margin Stability",
            passed=False, score=0.0, value=0.0,
            threshold="Low coefficient of variation",
            detail="Insufficient margin history"
        )

    valid_margins = [m for m in margins if not np.isnan(m) and not np.isinf(m)]
    if not valid_margins:
        return HealthCheckResult(
            name="Margin Stability",
            passed=False, score=0.0, value=0.0,
            threshold="Low coefficient of variation",
            detail="No valid margin data"
        )

    avg_margin = np.mean(valid_margins)
    std_margin = np.std(valid_margins)

    # Coefficient of variation (lower is more stable)
    cv = std_margin / abs(avg_margin) if avg_margin != 0 else float('inf')

    if cv <= 0.15:  # Very stable
        score = 1.0
        passed = True
    elif cv <= 0.30:  # Acceptably stable
        score = 0.7
        passed = True
    elif cv <= 0.50:
        score = 0.4
        passed = False
    else:
        score = 0.1
        passed = False

    return HealthCheckResult(
        name="Margin Stability",
        passed=passed,
        score=score,
        value=cv,
        threshold="CV ≤ 0.30",
        detail=f"Avg margin: {avg_margin:.1%}, CV: {cv:.2f}"
    )


def _check_free_cash_flow(stock: StockData) -> HealthCheckResult:
    """
    Check free cash flow consistency.
    Buffett wants businesses that reliably generate free cash.
    """
    fcf = stock.free_cash_flow
    if len(fcf) < 3:
        return HealthCheckResult(
            name="Free Cash Flow",
            passed=False, score=0.0, value=0.0,
            threshold="Positive in ≥80% of years",
            detail="Insufficient FCF history"
        )

    positive_years = sum(1 for f in fcf if f > 0)
    total = len(fcf)
    ratio = positive_years / total

    score = ratio
    passed = ratio >= 0.8

    return HealthCheckResult(
        name="Free Cash Flow",
        passed=passed,
        score=score,
        value=ratio,
        threshold="Positive in ≥80% of years",
        detail=f"{positive_years}/{total} years positive FCF"
    )


def _check_revenue_growth(stock: StockData) -> HealthCheckResult:
    """
    Check revenue growth trend.
    """
    if len(stock.revenue) < 3:
        return HealthCheckResult(
            name="Revenue Growth",
            passed=False, score=0.0, value=0.0,
            threshold="Positive 3yr+ CAGR",
            detail="Insufficient revenue history"
        )

    # Calculate CAGR (data is most-recent-first, so reverse)
    revenues = list(reversed(stock.revenue))
    valid = [r for r in revenues if r > 0]

    if len(valid) < 2:
        return HealthCheckResult(
            name="Revenue Growth",
            passed=False, score=0.0, value=0.0,
            threshold="Positive 3yr+ CAGR",
            detail="No valid revenue data"
        )

    years = len(valid) - 1
    try:
        cagr = (valid[-1] / valid[0]) ** (1 / years) - 1
    except (ZeroDivisionError, ValueError):
        cagr = 0.0

    if cagr >= 0.10:
        score = 1.0
    elif cagr >= 0.05:
        score = 0.8
    elif cagr >= 0.0:
        score = 0.5
    else:
        score = max(0, 0.2 + cagr)  # Negative growth

    passed = cagr > 0

    return HealthCheckResult(
        name="Revenue Growth",
        passed=passed,
        score=score,
        value=cagr,
        threshold="Positive CAGR",
        detail=f"Revenue CAGR: {cagr:.1%} over {years} years"
    )


def _check_earnings_predictability(stock: StockData) -> HealthCheckResult:
    """
    Check earnings predictability (low coefficient of variation).
    Buffett prefers businesses where future earnings are reasonably predictable.
    """
    earnings = [e for e in stock.net_income if e > 0]

    if len(earnings) < 3:
        return HealthCheckResult(
            name="Earnings Predictability",
            passed=False, score=0.0, value=0.0,
            threshold="Low earnings CV",
            detail="Insufficient positive earnings history"
        )

    avg = np.mean(earnings)
    std = np.std(earnings)
    cv = std / avg if avg > 0 else float('inf')

    if cv <= 0.20:
        score = 1.0
        passed = True
    elif cv <= 0.35:
        score = 0.7
        passed = True
    elif cv <= 0.50:
        score = 0.4
        passed = False
    else:
        score = 0.1
        passed = False

    return HealthCheckResult(
        name="Earnings Predictability",
        passed=passed,
        score=score,
        value=cv,
        threshold="Earnings CV ≤ 0.35",
        detail=f"Earnings CV: {cv:.2f} ({len(earnings)} positive years)"
    )


def evaluate_financial_health(stock: StockData) -> FinancialHealthScore:
    """
    Run all financial health checks and compute a composite score.

    Args:
        stock: StockData object with financial history.

    Returns:
        FinancialHealthScore with individual check results and overall grade.
    """
    result = FinancialHealthScore(
        ticker=stock.ticker,
        name=stock.name,
    )

    # Run all checks with their weights
    checks_with_weights = [
        (_check_earnings_consistency(stock), 0.15),
        (_check_roe(stock), 0.15),
        (_check_debt_levels(stock), 0.15),
        (_check_current_ratio(stock), 0.10),
        (_check_operating_margin_stability(stock), 0.10),
        (_check_free_cash_flow(stock), 0.10),
        (_check_revenue_growth(stock), 0.10),
        (_check_earnings_predictability(stock), 0.15),
    ]

    weighted_score = 0.0
    for check, weight in checks_with_weights:
        result.checks.append(check)
        weighted_score += check.score * weight
        if check.passed:
            result.passed_checks += 1
        result.total_checks += 1

    result.overall_score = weighted_score

    # Assign letter grade
    if result.overall_score >= 0.85:
        result.grade = "A"
    elif result.overall_score >= 0.70:
        result.grade = "B"
    elif result.overall_score >= 0.55:
        result.grade = "C"
    elif result.overall_score >= 0.40:
        result.grade = "D"
    else:
        result.grade = "F"

    logger.info(
        f"  {stock.ticker}: Health Grade {result.grade} "
        f"(score={result.overall_score:.2f}, "
        f"passed={result.passed_checks}/{result.total_checks})"
    )

    return result
