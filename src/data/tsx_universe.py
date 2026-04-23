"""
TSX Stock Universe Loader — Perplexity Edition.

Uses Perplexity Sonar to identify a curated shortlist of TSX stocks that
are most likely to pass Buffett-style screening, eliminating the need to
crawl 230+ tickers via Yahoo Finance.

Falls back to the static curated list if Perplexity is unavailable.
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

from src.config import (
    TICKER_CACHE_FILE,
    TICKER_CACHE_MAX_AGE_DAYS,
    PERPLEXITY_API_KEY,
    PERPLEXITY_MODEL,
    TSX_SCREEN_COUNT,
)

logger = logging.getLogger(__name__)


# ── Curated S&P/TSX Composite constituents (static fallback) ────────────────
# Used when Perplexity is unavailable. Focused on established large-caps
# most likely to meet Buffett criteria (consistent earnings, moat, low debt).
TSX_QUALITY_CANDIDATES = [
    # Financials
    "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO",
    "MFC.TO", "SLF.TO", "GWO.TO", "IAG.TO", "POW.TO", "IGM.TO",
    "EQB.TO", "BN.TO", "BAM.TO", "IFC.TO", "FFH.TO",
    # Energy
    "CNQ.TO", "SU.TO", "CVE.TO", "IMO.TO", "TOU.TO", "ARX.TO",
    "ENB.TO", "TRP.TO", "PPL.TO",
    # Materials
    "ABX.TO", "AEM.TO", "FNV.TO", "WPM.TO", "NTR.TO", "WFG.TO",
    # Industrials
    "CNR.TO", "CP.TO", "WSP.TO", "TIH.TO", "TFII.TO", "CAE.TO",
    "STN.TO", "GFL.TO",
    # Technology
    "SHOP.TO", "CSU.TO", "OTEX.TO", "ENGH.TO", "GIB-A.TO",
    # Consumer
    "DOL.TO", "QSR.TO", "ATZ.TO", "ATD.TO", "L.TO", "MRU.TO",
    # Utilities
    "FTS.TO", "EMA.TO", "H.TO",
    # Communication
    "BCE.TO", "T.TO", "RCI-B.TO",
]


def _is_cache_valid() -> bool:
    if not TICKER_CACHE_FILE.exists():
        return False
    try:
        with open(TICKER_CACHE_FILE, "r") as f:
            data = json.load(f)
        cached_date = datetime.fromisoformat(data.get("updated_at", "2000-01-01"))
        return datetime.now() - cached_date < timedelta(days=TICKER_CACHE_MAX_AGE_DAYS)
    except (json.JSONDecodeError, ValueError):
        return False


def _save_cache(tickers: List[Dict[str, Any]]) -> None:
    cache_data = {
        "updated_at": datetime.now().isoformat(),
        "count": len(tickers),
        "tickers": tickers,
    }
    TICKER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TICKER_CACHE_FILE, "w") as f:
        json.dump(cache_data, f, indent=2)
    logger.info(f"Cached {len(tickers)} tickers to {TICKER_CACHE_FILE}")


def _load_cache() -> List[Dict[str, Any]]:
    with open(TICKER_CACHE_FILE, "r") as f:
        data = json.load(f)
    tickers = data.get("tickers", [])
    logger.info(f"Loaded {len(tickers)} tickers from cache (updated {data.get('updated_at', 'unknown')})")
    return tickers


def _perplexity_screen_tsx() -> List[Dict[str, Any]]:
    """
    Ask Perplexity to identify TSX stocks currently meeting Buffett criteria.
    Returns a ranked shortlist with basic metadata.
    """
    from openai import OpenAI

    if not PERPLEXITY_API_KEY:
        raise ValueError("PERPLEXITY_API_KEY not set")

    client = OpenAI(api_key=PERPLEXITY_API_KEY, base_url="https://api.perplexity.ai")

    prompt = f"""You are a Canadian equity analyst specializing in value investing.

Identify the {TSX_SCREEN_COUNT} most compelling TSX-listed stocks RIGHT NOW that best meet Warren Buffett's investing criteria:
- Listed on the Toronto Stock Exchange (ticker ends in .TO)
- Market cap > $500M CAD
- Consistent profitability for 5+ years (positive net income every year)
- Average ROE > 12% over last 5 years
- Debt/Equity ratio < 1.5
- Currently trading at a discount to intrinsic value (undervalued vs peers or historical)
- Identifiable competitive moat (brand, network effects, switching costs, low-cost producer, or regulatory)
- Dividend track record preferred but not required

Use current publicly available market data and financial statements.

Return ONLY a JSON array (no markdown, no explanation) of exactly {TSX_SCREEN_COUNT} objects, each with:
{{
  "ticker": "XX.TO",
  "name": "Full Company Name",
  "sector": "Financials|Energy|Materials|Industrials|Technology|Consumer Discretionary|Consumer Staples|Utilities|Communication Services|Real Estate|Healthcare",
  "industry": "specific industry",
  "market_cap_cad_billions": 0.0,
  "approx_pe": 0.0,
  "approx_roe_pct": 0.0,
  "approx_debt_equity": 0.0,
  "moat_type": "Brand|Network Effects|Switching Costs|Cost Advantage|Regulatory|None",
  "why_undervalued": "one sentence"
}}

Return the array sorted by attractiveness (most compelling first). Return ONLY the JSON array, starting with [."""

    try:
        response = client.chat.completions.create(
            model=PERPLEXITY_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a senior equity analyst. Return only valid JSON arrays with no markdown formatting.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )

        content = response.choices[0].message.content.strip()

        # Extract JSON array
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            content = content[start:end]

        candidates = json.loads(content)

        # Normalize to standard universe format
        result = []
        for c in candidates:
            if not c.get("ticker", "").endswith(".TO"):
                continue
            result.append({
                "ticker": c["ticker"],
                "name": c.get("name", c["ticker"]),
                "sector": c.get("sector", "Unknown"),
                "industry": c.get("industry", "Unknown"),
                "currency": "CAD",
                "market_cap": c.get("market_cap_cad_billions", 0) * 1e9,
                "approx_pe": c.get("approx_pe", 0),
                "approx_roe": c.get("approx_roe_pct", 0) / 100,
                "moat_type": c.get("moat_type", "Unknown"),
                "why_undervalued": c.get("why_undervalued", ""),
            })

        logger.info(f"Perplexity screened {len(result)} TSX candidates")
        return result

    except Exception as e:
        logger.error(f"Perplexity screening failed: {e}")
        raise


def _static_fallback_universe() -> List[Dict[str, Any]]:
    """Return the static curated list as basic dicts (no market data)."""
    return [
        {
            "ticker": t,
            "name": t.replace(".TO", ""),
            "sector": "Unknown",
            "industry": "Unknown",
            "currency": "CAD",
        }
        for t in TSX_QUALITY_CANDIDATES
    ]


def load_tsx_universe(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Load TSX candidate universe via Perplexity screening.

    Primary: Perplexity Sonar identifies pre-screened value candidates.
    Fallback: Static curated list if Perplexity is unavailable.
    Cache: Valid results are cached for TICKER_CACHE_MAX_AGE_DAYS days.
    """
    # Use cache if valid and not forcing refresh
    if not force_refresh and _is_cache_valid():
        return _load_cache()

    logger.info(f"Screening TSX universe via Perplexity (requesting {TSX_SCREEN_COUNT} candidates)...")

    try:
        candidates = _perplexity_screen_tsx()
        if candidates:
            _save_cache(candidates)
            return candidates
    except Exception as e:
        logger.warning(f"Perplexity screening unavailable ({e}), using static fallback list")

    fallback = _static_fallback_universe()
    logger.info(f"Using static fallback: {len(fallback)} candidates")
    return fallback
