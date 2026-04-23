"""
TSX Stock Universe Loader.

Builds and maintains a cached list of S&P/TSX Composite Index constituents.
Falls back to a curated static list if dynamic fetching fails.
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

import yfinance as yf

from src.config import (
    TICKER_CACHE_FILE,
    TICKER_CACHE_MAX_AGE_DAYS,
    MIN_MARKET_CAP,
    MIN_AVG_VOLUME,
    YFINANCE_RATE_LIMIT_DELAY,
)

logger = logging.getLogger(__name__)


# ── Curated S&P/TSX Composite constituents (as of Q1 2025) ─────────────────
# This serves as the primary source; yfinance is used to validate & enrich.
TSX_COMPOSITE_TICKERS = [
    # Financials
    "RY.TO", "TD.TO", "BNS.TO", "BMO.TO", "CM.TO", "NA.TO",
    "MFC.TO", "SLF.TO", "GWO.TO", "IAG.TO", "POW.TO", "IGM.TO",
    "CWB.TO", "EQB.TO", "X.TO", "BN.TO", "BAM.TO", "IFC.TO",
    "FFH.TO", "DFY.TO",
    # Energy
    "CNQ.TO", "SU.TO", "CVE.TO", "IMO.TO", "TOU.TO", "ARX.TO",
    "ERF.TO", "WCP.TO", "MEG.TO", "PSK.TO", "PEY.TO", "BIR.TO",
    "TVE.TO", "VET.TO", "CPG.TO", "FRU.TO", "NVA.TO", "AAV.TO",
    "ENB.TO", "TRP.TO", "PPL.TO", "KEY.TO", "GEI.TO",
    # Materials
    "ABX.TO", "AEM.TO", "FNV.TO", "WPM.TO", "AGI.TO", "K.TO",
    "FM.TO", "CS.TO", "LUN.TO", "TECK.TO", "IVN.TO", "HBM.TO",
    "ERO.TO", "LIF.TO", "NTR.TO", "CCL-B.TO", "WFG.TO",
    # Industrials
    "CNR.TO", "CP.TO", "WSP.TO", "TIH.TO", "TFII.TO", "CAE.TO",
    "RBA.TO", "STN.TO", "SNC.TO", "ARE.TO", "GFL.TO", "BDGI.TO",
    "WJA.TO", "AC.TO", "EIF.TO", "RUS.TO", "NFI.TO",
    # Technology
    "SHOP.TO", "CSU.TO", "OTEX.TO", "LSPD.TO", "BB.TO",
    "DCBO.TO", "KXS.TO", "DSG.TO", "ENGH.TO", "GIB-A.TO",
    "MDA.TO", "TIXT.TO", "TOI.TO",
    # Consumer Discretionary
    "DOL.TO", "QSR.TO", "MG.TO", "LNR.TO", "BYD.TO",
    "GIL.TO", "ATZ.TO", "PBH.TO", "CTC-A.TO", "EMP-A.TO",
    # Consumer Staples
    "L.TO", "SAP.TO", "MFI.TO", "WN.TO", "ATD.TO", "NWC.TO",
    "MRU.TO", "PRMW.TO",
    # Communication Services
    "BCE.TO", "T.TO", "RCI-B.TO", "CGO.TO", "QBR-B.TO",
    "CCA.TO", "SJR-B.TO",
    # Utilities
    "FTS.TO", "EMA.TO", "H.TO", "AQN.TO", "BEP-UN.TO",
    "CPX.TO", "ACO-X.TO", "TA.TO", "NPI.TO", "ALA.TO",
    # REITs
    "REI-UN.TO", "AP-UN.TO", "HR-UN.TO", "CAR-UN.TO", "BPY-UN.TO",
    "SRU-UN.TO", "CHP-UN.TO", "DIR-UN.TO", "GRT-UN.TO", "PMZ-UN.TO",
    "IIP-UN.TO", "CRR-UN.TO", "CUF-UN.TO", "KEG-UN.TO",
    # Healthcare
    "WSP.TO", "CXR.TO", "WELL.TO",
]


def _is_cache_valid() -> bool:
    """Check if the ticker cache file exists and is recent enough."""
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
    """Save validated tickers to the cache file."""
    cache_data = {
        "updated_at": datetime.now().isoformat(),
        "count": len(tickers),
        "tickers": tickers,
    }
    TICKER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TICKER_CACHE_FILE, "w") as f:
        json.dump(cache_data, f, indent=2)
    logger.info(f"Cached {len(tickers)} validated TSX tickers to {TICKER_CACHE_FILE}")


def _load_cache() -> List[Dict[str, Any]]:
    """Load tickers from the cache file."""
    with open(TICKER_CACHE_FILE, "r") as f:
        data = json.load(f)
    tickers = data.get("tickers", [])
    logger.info(f"Loaded {len(tickers)} tickers from cache (updated {data.get('updated_at', 'unknown')})")
    return tickers


def _validate_and_enrich_tickers(raw_tickers: List[str]) -> List[Dict[str, Any]]:
    """
    Validate each ticker via yfinance and collect basic info.
    Filters out tickers that fail validation or don't meet criteria.
    """
    validated = []
    total = len(raw_tickers)

    for i, ticker_symbol in enumerate(raw_tickers):
        try:
            logger.debug(f"Validating [{i+1}/{total}] {ticker_symbol}...")
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info

            # Must have basic info
            if not info or info.get("regularMarketPrice") is None:
                logger.debug(f"  Skipping {ticker_symbol}: no market data")
                continue

            market_cap = info.get("marketCap", 0) or 0
            avg_volume = info.get("averageVolume", 0) or 0

            # Apply filters
            if market_cap < MIN_MARKET_CAP:
                logger.debug(f"  Skipping {ticker_symbol}: market cap ${market_cap:,.0f} < ${MIN_MARKET_CAP:,.0f}")
                continue

            if avg_volume < MIN_AVG_VOLUME:
                logger.debug(f"  Skipping {ticker_symbol}: avg volume {avg_volume:,.0f} < {MIN_AVG_VOLUME:,.0f}")
                continue

            validated.append({
                "ticker": ticker_symbol,
                "name": info.get("longName", info.get("shortName", ticker_symbol)),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "market_cap": market_cap,
                "currency": info.get("currency", "CAD"),
            })
            logger.info(f"  ✓ {ticker_symbol} — {info.get('longName', 'N/A')} (${market_cap/1e9:.1f}B)")

            time.sleep(YFINANCE_RATE_LIMIT_DELAY)

        except Exception as e:
            logger.warning(f"  ✗ {ticker_symbol}: {e}")
            continue

    logger.info(f"Validated {len(validated)}/{total} tickers")
    return validated


def load_tsx_universe(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Load the TSX stock universe.

    Returns a list of dicts with keys:
        ticker, name, sector, industry, market_cap, currency

    Uses cache if available and recent; otherwise validates from the
    curated composite list.
    """
    if not force_refresh and _is_cache_valid():
        return _load_cache()

    logger.info("Building TSX universe (this may take several minutes on first run)...")

    # Remove duplicates from the curated list
    unique_tickers = list(dict.fromkeys(TSX_COMPOSITE_TICKERS))

    validated = _validate_and_enrich_tickers(unique_tickers)

    if validated:
        _save_cache(validated)
    else:
        logger.error("No tickers validated! Check network connectivity and yfinance.")

    return validated
