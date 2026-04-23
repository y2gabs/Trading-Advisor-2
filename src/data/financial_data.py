"""
Financial Data Collector.

Fetches comprehensive financial statements and metrics from Yahoo Finance
via the yfinance library. Returns structured StockData objects for analysis.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

import yfinance as yf
import pandas as pd
import numpy as np

from src.config import YFINANCE_RATE_LIMIT_DELAY, MIN_YEARS_FINANCIALS

logger = logging.getLogger(__name__)


@dataclass
class StockData:
    """Structured container for all financial data needed for analysis."""
    ticker: str
    name: str
    sector: str
    industry: str
    currency: str

    # Current market data
    current_price: float = 0.0
    market_cap: float = 0.0
    shares_outstanding: float = 0.0

    # Income statement (annual, most recent N years)
    net_income: List[float] = field(default_factory=list)
    revenue: List[float] = field(default_factory=list)
    operating_income: List[float] = field(default_factory=list)
    ebit: List[float] = field(default_factory=list)

    # Cash flow statement
    operating_cash_flow: List[float] = field(default_factory=list)
    capital_expenditures: List[float] = field(default_factory=list)  # Stored as positive values
    depreciation_amortization: List[float] = field(default_factory=list)
    free_cash_flow: List[float] = field(default_factory=list)

    # Balance sheet (most recent)
    total_debt: float = 0.0
    total_equity: float = 0.0
    current_assets: float = 0.0
    current_liabilities: float = 0.0
    total_assets: float = 0.0
    cash_and_equivalents: float = 0.0

    # Key ratios (calculated or from yfinance)
    pe_ratio: float = 0.0
    pb_ratio: float = 0.0
    roe_history: List[float] = field(default_factory=list)
    operating_margin_history: List[float] = field(default_factory=list)
    dividend_yield: float = 0.0

    # Metadata
    years_of_data: int = 0
    fiscal_years: List[str] = field(default_factory=list)
    data_quality: str = "unknown"  # "good", "partial", "poor"

    @property
    def has_sufficient_data(self) -> bool:
        """Check if we have enough years of financial data for analysis."""
        return self.years_of_data >= MIN_YEARS_FINANCIALS and len(self.net_income) >= MIN_YEARS_FINANCIALS

    @property
    def debt_to_equity(self) -> float:
        """Calculate debt-to-equity ratio."""
        if self.total_equity <= 0:
            return float('inf')
        return self.total_debt / self.total_equity

    @property
    def current_ratio(self) -> float:
        """Calculate current ratio."""
        if self.current_liabilities <= 0:
            return float('inf')
        return self.current_assets / self.current_liabilities

    @property
    def avg_roe(self) -> float:
        """Average ROE over available history."""
        valid = [r for r in self.roe_history if not np.isnan(r) and not np.isinf(r)]
        return np.mean(valid) if valid else 0.0

    @property
    def avg_operating_margin(self) -> float:
        """Average operating margin over available history."""
        valid = [m for m in self.operating_margin_history if not np.isnan(m) and not np.isinf(m)]
        return np.mean(valid) if valid else 0.0


def _safe_get(series: pd.Series, key: str, default: float = 0.0) -> float:
    """Safely extract a value from a pandas Series."""
    try:
        val = series.get(key, default)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _extract_annual_values(df: pd.DataFrame, field_names: List[str]) -> List[float]:
    """
    Extract annual values from a financial statement DataFrame.
    Tries multiple field name variants for compatibility.
    """
    if df is None or df.empty:
        return []

    for field_name in field_names:
        if field_name in df.index:
            values = df.loc[field_name].tolist()
            # Convert to floats, replacing None/NaN with 0
            result = []
            for v in values:
                try:
                    fv = float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else 0.0
                    result.append(fv)
                except (TypeError, ValueError):
                    result.append(0.0)
            return result

    return []


def fetch_stock_data(ticker_info: Dict[str, Any]) -> Optional[StockData]:
    """
    Fetch comprehensive financial data for a single stock.

    Args:
        ticker_info: Dict with at minimum 'ticker' key, plus optional
                     'name', 'sector', 'industry', 'currency' from universe loader.

    Returns:
        StockData object or None if insufficient data.
    """
    symbol = ticker_info["ticker"]

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        # ── Basic info ──────────────────────────────────────────────────────
        stock = StockData(
            ticker=symbol,
            name=ticker_info.get("name", info.get("longName", symbol)),
            sector=ticker_info.get("sector", info.get("sector", "Unknown")),
            industry=ticker_info.get("industry", info.get("industry", "Unknown")),
            currency=ticker_info.get("currency", info.get("currency", "CAD")),
            current_price=info.get("currentPrice", info.get("regularMarketPrice", 0.0)) or 0.0,
            market_cap=info.get("marketCap", 0) or 0,
            shares_outstanding=info.get("sharesOutstanding", 0) or 0,
            pe_ratio=info.get("trailingPE", 0.0) or 0.0,
            pb_ratio=info.get("priceToBook", 0.0) or 0.0,
            dividend_yield=info.get("dividendYield", 0.0) or 0.0,
        )

        # ── Income Statement ────────────────────────────────────────────────
        income_stmt = ticker.financials  # Annual income statement
        if income_stmt is not None and not income_stmt.empty:
            stock.net_income = _extract_annual_values(income_stmt, ["Net Income", "Net Income Common Stockholders"])
            stock.revenue = _extract_annual_values(income_stmt, ["Total Revenue", "Revenue"])
            stock.operating_income = _extract_annual_values(income_stmt, ["Operating Income", "EBIT"])
            stock.ebit = _extract_annual_values(income_stmt, ["EBIT", "Operating Income"])
            stock.fiscal_years = [str(col.year) for col in income_stmt.columns]
            stock.years_of_data = len(income_stmt.columns)

            # Calculate operating margin history
            for rev, oi in zip(stock.revenue, stock.operating_income):
                if rev and rev > 0:
                    stock.operating_margin_history.append(oi / rev)
                else:
                    stock.operating_margin_history.append(0.0)

        # ── Cash Flow Statement ─────────────────────────────────────────────
        cash_flow = ticker.cashflow
        if cash_flow is not None and not cash_flow.empty:
            stock.operating_cash_flow = _extract_annual_values(
                cash_flow, ["Operating Cash Flow", "Total Cash From Operating Activities"]
            )
            raw_capex = _extract_annual_values(
                cash_flow, ["Capital Expenditure", "Capital Expenditures"]
            )
            # CapEx is typically negative in statements; store as positive
            stock.capital_expenditures = [abs(c) for c in raw_capex]

            stock.depreciation_amortization = _extract_annual_values(
                cash_flow, ["Depreciation And Amortization", "Depreciation"]
            )
            stock.free_cash_flow = _extract_annual_values(
                cash_flow, ["Free Cash Flow"]
            )
            # If free_cash_flow not directly available, calculate it
            if not stock.free_cash_flow and stock.operating_cash_flow:
                stock.free_cash_flow = [
                    ocf - capex
                    for ocf, capex in zip(stock.operating_cash_flow, stock.capital_expenditures)
                ]

        # ── Balance Sheet ───────────────────────────────────────────────────
        balance_sheet = ticker.balance_sheet
        if balance_sheet is not None and not balance_sheet.empty:
            # Get most recent period (first column)
            latest = balance_sheet.iloc[:, 0]

            stock.total_debt = _safe_get(latest, "Total Debt", 0.0)
            if stock.total_debt == 0.0:
                stock.total_debt = _safe_get(latest, "Long Term Debt", 0.0) + _safe_get(latest, "Short Long Term Debt", 0.0)

            stock.total_equity = _safe_get(latest, "Stockholders Equity",
                                 _safe_get(latest, "Total Stockholder Equity", 0.0))
            stock.current_assets = _safe_get(latest, "Current Assets",
                                   _safe_get(latest, "Total Current Assets", 0.0))
            stock.current_liabilities = _safe_get(latest, "Current Liabilities",
                                        _safe_get(latest, "Total Current Liabilities", 0.0))
            stock.total_assets = _safe_get(latest, "Total Assets", 0.0)
            stock.cash_and_equivalents = _safe_get(latest, "Cash And Cash Equivalents",
                                         _safe_get(latest, "Cash", 0.0))

            # ROE history from balance sheet + income
            if balance_sheet.shape[1] > 0 and stock.net_income:
                for i in range(min(len(stock.net_income), balance_sheet.shape[1])):
                    equity_col = balance_sheet.iloc[:, i]
                    equity = _safe_get(equity_col, "Stockholders Equity",
                             _safe_get(equity_col, "Total Stockholder Equity", 0.0))
                    if equity > 0:
                        stock.roe_history.append(stock.net_income[i] / equity)
                    else:
                        stock.roe_history.append(0.0)

        # ── Determine data quality ──────────────────────────────────────────
        if stock.years_of_data >= 5 and stock.net_income and stock.operating_cash_flow:
            stock.data_quality = "good"
        elif stock.years_of_data >= MIN_YEARS_FINANCIALS:
            stock.data_quality = "partial"
        else:
            stock.data_quality = "poor"

        if not stock.has_sufficient_data:
            logger.debug(f"  {symbol}: insufficient data ({stock.years_of_data} years)")
            return None

        logger.info(
            f"  ✓ {symbol}: {stock.years_of_data}yr data, "
            f"price=${stock.current_price:.2f}, "
            f"cap=${stock.market_cap/1e9:.1f}B, "
            f"quality={stock.data_quality}"
        )
        return stock

    except Exception as e:
        logger.warning(f"  ✗ {symbol}: failed to fetch data — {e}")
        return None


def fetch_all_stock_data(
    universe: List[Dict[str, Any]],
    progress_callback=None,
) -> List[StockData]:
    """
    Fetch financial data for all stocks in the universe.

    Args:
        universe: List of ticker info dicts from tsx_universe.load_tsx_universe()
        progress_callback: Optional callable(current, total, ticker) for progress updates

    Returns:
        List of StockData objects with sufficient data for analysis.
    """
    results = []
    total = len(universe)
    logger.info(f"Fetching financial data for {total} stocks...")

    for i, ticker_info in enumerate(universe):
        if progress_callback:
            progress_callback(i + 1, total, ticker_info["ticker"])

        stock_data = fetch_stock_data(ticker_info)
        if stock_data:
            results.append(stock_data)

        time.sleep(YFINANCE_RATE_LIMIT_DELAY)

    logger.info(f"Successfully fetched data for {len(results)}/{total} stocks")
    return results
