"""
Perplexity Research Agent.

Uses Perplexity's Sonar API (OpenAI-compatible) to conduct real-time
web-grounded research on stock candidates, focusing on qualitative
factors that matter to Buffett-style investing.
"""

import logging
import time
import json
from typing import Dict, Any, Optional, List

from openai import OpenAI

from src.config import PERPLEXITY_API_KEY, PERPLEXITY_MODEL, PERPLEXITY_RATE_LIMIT_DELAY

logger = logging.getLogger(__name__)

# Initialize Perplexity client via OpenAI-compatible endpoint
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    """Lazy-initialize the Perplexity client."""
    global _client
    if _client is None:
        if not PERPLEXITY_API_KEY:
            raise ValueError(
                "PERPLEXITY_API_KEY not set. Add it to your .env file. "
                "Get a key at https://www.perplexity.ai/"
            )
        _client = OpenAI(
            api_key=PERPLEXITY_API_KEY,
            base_url="https://api.perplexity.ai",
        )
    return _client


def _build_research_prompt(ticker: str, name: str, sector: str, context: str) -> str:
    """Build a comprehensive research prompt for a single stock."""
    return f"""Analyze the Canadian TSX-listed stock {name} (ticker: {ticker}) in the {sector} sector.

Provide a thorough analysis covering these specific areas. Be factual and cite recent data:

1. **Competitive Moat Analysis**: Does {name} have durable competitive advantages? Consider:
   - Brand strength, network effects, switching costs, cost advantages, or regulatory barriers
   - Rate the moat as: Wide, Narrow, or None

2. **Recent News & Catalysts** (last 6 months):
   - Any earnings surprises, M&A activity, major contracts, or regulatory changes?
   - Any material positive or negative developments?

3. **Management Quality**:
   - CEO/leadership track record and tenure
   - Capital allocation decisions (buybacks, dividends, acquisitions)
   - Any insider buying or selling activity?

4. **Industry Outlook**:
   - Current state and near-term outlook for the {sector} sector in Canada
   - Key tailwinds and headwinds

5. **Risk Factors**:
   - Top 3 risks specific to this company
   - Any litigation, regulatory threats, or balance sheet concerns?

6. **Overall Assessment**:
   - Is this a business you'd be comfortable owning for 10+ years (Buffett style)?
   - Rate overall quality: Excellent, Good, Fair, or Poor

Additional context about this stock's financials:
{context}

Respond in structured JSON format with these keys:
- moat_rating: "Wide", "Narrow", or "None"
- moat_analysis: string
- recent_news: string
- management_quality: "Excellent", "Good", "Fair", or "Poor"
- management_detail: string
- industry_outlook: "Positive", "Neutral", or "Negative"
- industry_detail: string
- risk_factors: list of strings (top 3)
- overall_quality: "Excellent", "Good", "Fair", or "Poor"
- overall_summary: string (2-3 sentence summary)
- confidence_level: "High", "Medium", or "Low"
"""


def _parse_research_response(content: str) -> Dict[str, Any]:
    """Parse the Perplexity response, handling both JSON and text formats."""
    # Try to extract JSON from the response
    try:
        # Look for JSON block in response
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        elif content.strip().startswith("{"):
            json_str = content.strip()
        else:
            # Try to find JSON-like content
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = content[start:end]
            else:
                # Fallback: return raw text as analysis
                return {
                    "moat_rating": "Unknown",
                    "moat_analysis": content,
                    "recent_news": "See full analysis",
                    "management_quality": "Unknown",
                    "management_detail": "See full analysis",
                    "industry_outlook": "Unknown",
                    "industry_detail": "See full analysis",
                    "risk_factors": ["Unable to parse structured response"],
                    "overall_quality": "Unknown",
                    "overall_summary": content[:500],
                    "confidence_level": "Low",
                    "raw_response": content,
                }

        return json.loads(json_str)

    except (json.JSONDecodeError, IndexError) as e:
        logger.warning(f"Failed to parse Perplexity response as JSON: {e}")
        return {
            "moat_rating": "Unknown",
            "overall_summary": content[:500],
            "raw_response": content,
            "parse_error": str(e),
        }


def _qualitative_score_from_research(research: Dict[str, Any]) -> float:
    """
    Convert qualitative research into a 0.0-1.0 score.

    Scoring matrix:
    - Moat: Wide=0.30, Narrow=0.15, None=0.00
    - Management: Excellent=0.25, Good=0.15, Fair=0.05, Poor=0.00
    - Industry: Positive=0.20, Neutral=0.10, Negative=0.00
    - Quality: Excellent=0.25, Good=0.15, Fair=0.05, Poor=0.00
    """
    score = 0.0

    moat_scores = {"Wide": 0.30, "Narrow": 0.15, "None": 0.0}
    score += moat_scores.get(research.get("moat_rating", "Unknown"), 0.10)

    mgmt_scores = {"Excellent": 0.25, "Good": 0.15, "Fair": 0.05, "Poor": 0.0}
    score += mgmt_scores.get(research.get("management_quality", "Unknown"), 0.08)

    industry_scores = {"Positive": 0.20, "Neutral": 0.10, "Negative": 0.0}
    score += industry_scores.get(research.get("industry_outlook", "Unknown"), 0.08)

    quality_scores = {"Excellent": 0.25, "Good": 0.15, "Fair": 0.05, "Poor": 0.0}
    score += quality_scores.get(research.get("overall_quality", "Unknown"), 0.08)

    return min(1.0, score)


def research_stock(
    ticker: str,
    name: str,
    sector: str,
    financial_context: str,
) -> Dict[str, Any]:
    """
    Research a single stock using Perplexity's Sonar API.

    Args:
        ticker: Stock ticker (e.g., "RY.TO")
        name: Company name
        sector: Sector classification
        financial_context: Summary of financial data for context

    Returns:
        Dict with research results and a qualitative score.
    """
    client = _get_client()

    prompt = _build_research_prompt(ticker, name, sector, financial_context)

    try:
        response = client.chat.completions.create(
            model=PERPLEXITY_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior equity research analyst specializing in "
                        "Canadian markets. Provide thorough, factual analysis with "
                        "specific data points. Always respond in structured JSON format."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,  # Low temperature for factual research
        )

        content = response.choices[0].message.content
        research = _parse_research_response(content)
        research["qualitative_score"] = _qualitative_score_from_research(research)

        logger.info(
            f"  ✓ {ticker}: Moat={research.get('moat_rating', '?')}, "
            f"Quality={research.get('overall_quality', '?')}, "
            f"Score={research['qualitative_score']:.2f}"
        )

        return research

    except Exception as e:
        logger.error(f"  ✗ {ticker}: Perplexity research failed — {e}")
        return {
            "error": str(e),
            "qualitative_score": 0.5,  # Neutral score on failure
        }


def research_candidates(
    candidates: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Research multiple stock candidates.

    Args:
        candidates: List of dicts with 'ticker', 'name', 'sector', 'financial_context'

    Returns:
        Dict mapping ticker -> research results
    """
    results = {}
    total = len(candidates)

    logger.info(f"Researching {total} candidates via Perplexity Sonar...")

    for i, candidate in enumerate(candidates):
        ticker = candidate["ticker"]
        logger.info(f"[{i+1}/{total}] Researching {ticker}...")

        results[ticker] = research_stock(
            ticker=ticker,
            name=candidate["name"],
            sector=candidate["sector"],
            financial_context=candidate.get("financial_context", ""),
        )

        if i < total - 1:
            time.sleep(PERPLEXITY_RATE_LIMIT_DELAY)

    return results
