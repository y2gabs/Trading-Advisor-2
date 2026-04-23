"""
Financial Data Collector — Perplexity Edition.

Replaces the yfinance-based fetcher with Perplexity Sonar API calls.
Perplexity has live web access to retrieve current financial statements,
ratios, and market data for TSX-listed stocks.

The StockData dataclass is unchanged — downstream analysis modules are
fully compatible with this replacement.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

import numpy as np
from openai import OpenAI

from src.config import (
    PERPLEXITY_API_KEY,
    PERPLEXITY_MODEL,
    PERPLEXITY_RATE_LIMIT_DELAY,
    MIN_YEARS_FINANCIALS,
)

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not PERPLEXITY_API_KEY:
            raise ValueError("PERPLEXITY_API_KEY not set. Add it to your environment variables.")
        _client = OpenAI(api_key=PERPLEXITY_API_KEY, base_url="https://api.perplexity.ai")
    return _client


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

    # Income statement (annual, most recent N years, most recent first)
    net_income: List[float] = field(default_factory=list)
    revenue: List[float] = field(default_factory=list)
    operating_income: List[float] = field(default_factory=list)
    ebit: List[float] = field(default_factory=list)

    # Cash flow statement
    operating_cash_flow: List[float] = field(default_factory=list)
    capital_expenditures: List[float] = field(default_factory=list)
    depreciation_amortization: List[float] = field(default_factory=list)
    free_cash_flow: List[float] = field(default_factory=list)

    # Balance sheet (most recent)
    total_debt: float = 0.0
    total_equity: float = 0.0
    current_assets: float = 0.0
    current_liabilities: float = 0.0
    total_assets: float = 0.0
    cash_and_equivalents: float = 0.0

    # Key ratios
    pe_ratio: float = 0.0
    pb_ratio: float = 0.0
    roe_history: List[float] = field(default_factory=list)
    operating_margin_history: List[float] = field(default_factory=list)
    dividend_yield: float = 0.0

    # Metadata
    years_of_data: int = 0
    fiscal_years: List[str] = field(default_factory=list)
    data_quality: str = "unknown"

    @property
    def has_sufficient_data(self) -> bool:
        return self.years_of_data >= MIN_YEARS_FINANCIALS and len(self.net_income) >= MIN_YEARS_FINANCIALS

    @property
    def debt_to_equity(self) -> float:
        if self.total_equity <= 0:
            return float('inf')
        return self.total_debt / self.total_equity

    @property
    def current_ratio(self) -> float:
        if self.current_liabilities <= 0:
            return float('inf')
        return self.current_assets / self.current_liabilities

    @property
    def avg_roe(self) -> float:
        valid = [r for r in self.roe_history if not np.isnan(r) and not np.isinf(r)]
        return np.mean(valid) if valid else 0.0

    @property
    def avg_operating_margin(self) -> float:
        valid = [m for m in self.operating_margin_history if not np.isnan(m) and not np.isinf(m)]
        return np.mean(valid) if valid else 0.0


def _build_financial_prompt(ticker: str, name: str, sector: str) -> str:
    return f"""Retrieve the most recent publicly available annual financial data for {name} (TSX: {ticker}), a {sector} company listed on the Toronto Stock Exchange.

Return ONLY a JSON object (no markdown, no explanation) with the following fields.
All monetary values must be in full CAD (not millions, not billions — actual dollar amounts).
All lists must have the most recent year FIRST and go back in time.
Provide 4-5 years of history where available.

{{
  "name": "{name}",
  "sector": "{sector}",
  "industry": "specific industry string",
  "current_price_cad": 0.0,
  "market_cap_cad": 0.0,
  "shares_outstanding": 0.0,
  "pe_ratio": 0.0,
  "pb_ratio": 0.0,
  "dividend_yield": 0.0,
  "net_income": [year1, year2, year3, year4, year5],
  "revenue": [year1, year2, year3, year4, year5],
  "operating_income": [year1, year2, year3, year4, year5],
  "operating_cash_flow": [year1, year2, year3, year4, year5],
  "capital_expenditures": [year1, year2, year3, year4, year5],
  "depreciation_amortization": [year1, year2, year3, year4, year5],
  "free_cash_flow": [year1, year2, year3, year4, year5],
  "total_debt_cad": 0.0,
  "total_equity_cad": 0.0,
  "current_assets_cad": 0.0,
  "current_liabilities_cad": 0.0,
  "total_assets_cad": 0.0,
  "cash_cad": 0.0,
  "roe_history": [year1_decimal, year2_decimal, year3_decimal, year4_decimal],
  "fiscal_years": ["2024", "2023", "2022", "2021", "2020"],
  "data_confidence": "high|medium|low"
}}

Use 0.0 for any value you cannot find. Use your best estimate based on publicly reported financials.
Return ONLY the JSON object, starting with {{."""


def _parse_financial_response(content: str, ticker: str) -> Optional[Dict[str, Any]]:
    """Extract and validate JSON from Perplexity financial response."""
    try:
        content = content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            content = content[start:end]

        return json.loads(content)
    except (json.JSONDecodeError, IndexError) as e:
        logger.warning(f"  {ticker}: failed to parse financial JSON — {e}")
        return None


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if not (np.isnan(f) or np.isinf(f)) else default
    except (TypeError, ValueError):
        return default


def _safe_list(val: Any) -> List[float]:
    if not isinstance(val, list):
        return []
    return [_safe_float(v) for v in val]


def _build_stock_data(ticker: str, ticker_info: Dict[str, Any], data: Dict[str, Any]) -> Optional[StockData]:
    """Populate a StockData object from Perplexity's JSON response."""
    net_income = _safe_list(data.get("net_income", []))
    revenue = _safe_list(data.get("revenue", []))
    operating_cash_flow = _safe_list(data.get("operating_cash_flow", []))
    capital_expenditures = [abs(v) for v in _safe_list(data.get("capital_expenditures", []))]
    depreciation_amortization = _safe_list(data.get("depreciation_amortization", []))
    operating_income = _safe_list(data.get("operating_income", []))
    free_cash_flow = _safe_list(data.get("free_cash_flow", []))
    roe_history = _safe_list(data.get("roe_history", []))
    fiscal_years = data.get("fiscal_years", [])

    # Derive FCF if not provided
    if not free_cash_flow and operating_cash_flow and capital_expenditures:
        free_cash_flow = [
            ocf - capex
            for ocf, capex in zip(operating_cash_flow, capital_expenditures)
        ]

    # Derive operating margin history
    operating_margin_history = []
    for rev, oi in zip(revenue, operating_income):
        if rev and rev > 0:
            operating_margin_history.append(oi / rev)
        else:
            operating_margin_history.append(0.0)

    years_of_data = len(net_income)

    stock = StockData(
        ticker=ticker,
        name=data.get("name", ticker_info.get("name", ticker)),
        sector=data.get("sector", ticker_info.get("sector", "Unknown")),
        industry=data.get("industry", ticker_info.get("industry", "Unknown")),
        currency="CAD",
        current_price=_safe_float(data.get("current_price_cad")),
        market_cap=_safe_float(data.get("market_cap_cad")),
        shares_outstanding=_safe_float(data.get("shares_outstanding")),
        pe_ratio=_safe_float(data.get("pe_ratio")),
        pb_ratio=_safe_float(data.get("pb_ratio")),
        dividend_yield=_safe_float(data.get("dividend_yield")),
        net_income=net_income,
        revenue=revenue,
        operating_income=operating_income,
        ebit=operating_income,  # Use operating income as EBIT proxy
        operating_cash_flow=operating_cash_flow,
        capital_expenditures=capital_expenditures,
        depreciation_amortization=depreciation_amortization,
        free_cash_flow=free_cash_flow,
        total_debt=_safe_float(data.get("total_debt_cad")),
        total_equity=_safe_float(data.get("total_equity_cad")),
        current_assets=_safe_float(data.get("current_assets_cad")),
        current_liabilities=_safe_float(data.get("current_liabilities_cad")),
        total_assets=_safe_float(data.get("total_assets_cad")),
        cash_and_equivalents=_safe_float(data.get("cash_cad")),
        roe_history=roe_history,
        operating_margin_history=operating_margin_history,
        fiscal_years=[str(y) for y in fiscal_years],
        years_of_data=years_of_data,
    )

    # Shares outstanding fallback: derive from market cap / price
    if stock.shares_outstanding == 0 and stock.market_cap > 0 and stock.current_price > 0:
        stock.shares_outstanding = stock.market_cap / stock.current_price

    # Data quality assessment
    confidence = data.get("data_confidence", "low")
    if years_of_data >= 5 and net_income and operating_cash_flow and confidence != "low":
        stock.data_quality = "good"
    elif years_of_data >= MIN_YEARS_FINANCIALS:
        stock.data_quality = "partial"
    else:
        stock.data_quality = "poor"

    return stock


def fetch_stock_data(ticker_info: Dict[str, Any]) -> Optional[StockData]:
    """
    Fetch financial data for a single TSX stock via Perplexity Sonar.

    Args:
        ticker_info: Dict with at minimum 'ticker', and optionally 'name', 'sector'.

    Returns:
        StockData object or None if insufficient data.
    """
    symbol = ticker_info["ticker"]
    name = ticker_info.get("name", symbol)
    sector = ticker_info.get("sector", "Unknown")

    client = _get_client()
    prompt = _build_financial_prompt(symbol, name, sector)

    try:
        response = client.chat.completions.create(
            model=PERPLEXITY_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a financial data provider. Return accurate financial data "
                        "from public financial statements. Always respond with valid JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )

        content = response.choices[0].message.content
        data = _parse_financial_response(content, symbol)

        if not data:
            return None

        stock = _build_stock_data(symbol, ticker_info, data)

        if not stock.has_sufficient_data:
            logger.warning(f"  ✗ {symbol}: insufficient data ({stock.years_of_data} years)")
            return None

        if stock.current_price <= 0 or stock.market_cap <= 0:
            logger.warning(f"  ✗ {symbol}: missing price or market cap")
            return None

        logger.info(
            f"  ✓ {symbol}: {stock.years_of_data}yr data, "
            f"price=CAD${stock.current_price:.2f}, "
            f"cap=CAD${stock.market_cap/1e9:.1f}B, "
            f"quality={stock.data_quality}"
        )
        return stock

    except Exception as e:
        logger.warning(f"  ✗ {symbol}: Perplexity fetch failed — {e}")
        return None


def fetch_all_stock_data(
    universe: List[Dict[str, Any]],
    progress_callback=None,
) -> List[StockData]:
    """
    Fetch financial data for all stocks in the universe via Perplexity.

    Args:
        universe: List of ticker info dicts from load_tsx_universe()
        progress_callback: Optional callable(current, total, ticker) for progress.

    Returns:
        List of StockData objects with sufficient data for analysis.
    """
    results = []
    total = len(universe)
    logger.info(f"Fetching financial data for {total} stocks via Perplexity...")

    for i, ticker_info in enumerate(universe):
        if progress_callback:
            progress_callback(i + 1, total, ticker_info["ticker"])

        stock_data = fetch_stock_data(ticker_info)
        if stock_data:
            results.append(stock_data)

        if i < total - 1:
            time.sleep(PERPLEXITY_RATE_LIMIT_DELAY)

    logger.info(f"Successfully fetched data for {len(results)}/{total} stocks")
    return results
