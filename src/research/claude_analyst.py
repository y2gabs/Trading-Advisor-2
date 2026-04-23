"""
Claude Analysis Engine.

Uses the Anthropic Claude API to synthesize quantitative and qualitative
data into final investment recommendations, applying a Buffett-style
investment persona.
"""

import logging
import json
from typing import Dict, Any, List, Optional

import anthropic

from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, FINAL_TOP_PICKS
from src.analysis.scoring import ScoredStock

logger = logging.getLogger(__name__)

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    """Lazy-initialize the Anthropic client."""
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Add it to your .env file. "
                "Get a key at https://console.anthropic.com"
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


BUFFETT_SYSTEM_PROMPT = """You are Warren Buffett's personal investment analyst. You think exactly like Buffett when evaluating businesses:

CORE PRINCIPLES YOU FOLLOW:
1. **Circle of Competence**: Only recommend businesses you can understand.
2. **Economic Moats**: Favor businesses with durable competitive advantages.
3. **Management Integrity**: Prefer owner-operators who think long-term.
4. **Margin of Safety**: The price must be significantly below intrinsic value.
5. **Long-term Horizon**: Every pick should be a "hold forever" candidate.
6. **Conservative Estimates**: Always err on the side of caution in projections.
7. **Quality over Cheapness**: A wonderful business at a fair price beats a fair business at a wonderful price.

You are evaluating Canadian TSX-listed stocks. Consider:
- Canadian market dynamics, regulations, and economic outlook
- Currency (CAD) and cross-border business considerations
- TSX-specific factors (sector concentration in financials, energy, materials)

Be brutally honest. If a stock doesn't meet Buffett's standards, say so clearly.
Provide specific, actionable analysis — not generic platitudes."""


def _build_analysis_prompt(candidates: List[Dict[str, Any]]) -> str:
    """Build the synthesis prompt with all candidate data."""
    prompt = f"""Analyze these {len(candidates)} TSX stock candidates and select the TOP {FINAL_TOP_PICKS} most compelling undervalued investments.

For each candidate, I'm providing:
- Financial metrics and intrinsic value calculation
- Perplexity web research (moat, management, industry, risks)
- Composite scores

## CANDIDATES:

"""
    for i, c in enumerate(candidates):
        prompt += f"""
### Candidate #{i+1}: {c['ticker']} — {c['name']}
**Sector:** {c['sector']}
**Current Price:** ${c['current_price']:.2f}
**Intrinsic Value (Base):** ${c['intrinsic_value']:.2f}
**Intrinsic Value (Conservative):** ${c['intrinsic_value_conservative']:.2f}
**Margin of Safety:** {c['margin_of_safety']:.1%}
**Margin of Safety (Conservative):** {c['margin_of_safety_conservative']:.1%}

**Financial Health:**
- Grade: {c['health_grade']}
- ROE: {c['avg_roe']:.1%}
- Debt/Equity: {c['debt_to_equity']:.2f}
- Current Ratio: {c['current_ratio']:.2f}
- Earnings Growth CAGR: {c['earnings_cagr']:.1%}
- Revenue Growth CAGR: {c['revenue_cagr']:.1%}

**Owner Earnings:**
- Average (3yr): ${c['avg_owner_earnings']:,.0f}
- Growth Rate Used: {c['growth_rate']:.1%}

**Qualitative Research:**
{json.dumps(c.get('research', {}), indent=2, default=str)}

---
"""

    prompt += f"""
## YOUR TASK:

Select the TOP {FINAL_TOP_PICKS} stocks from the candidates above. For each pick, provide:

1. **Conviction Level**: High, Medium, or Low
2. **Investment Thesis**: 2-3 sentences on WHY this is a Buffett-style pick
3. **Writeup**: A detailed 3-4 paragraph narrative writeup explaining WHY you are recommending this stock. Write as if you are a senior analyst writing a note to a client. Cover: (a) what the company does and why it's a quality business, (b) why it's undervalued right now and what the market is missing, (c) the competitive moat and management quality, and (d) what you expect going forward. Use specific numbers (price, intrinsic value, margins, growth rates). This should be compelling, clear, and readable — not bullet points.
4. **Bull Case**: Best-case scenario (2-3 sentences)
5. **Bear Case**: Worst-case scenario (2-3 sentences)
6. **Key Risks**: Top 2-3 specific risks
7. **Catalysts**: What could unlock value in the next 12-24 months?
8. **Position Sizing**: Suggested allocation (as % of a $100K portfolio)

Also provide:
- **Overall Market Commentary**: 2-3 sentences on the current TSX environment
- **Sector Themes**: Any sector-level observations

Respond in JSON format with this structure:
{{
    "market_commentary": "string",
    "sector_themes": "string",
    "top_picks": [
        {{
            "rank": 1,
            "ticker": "XX.TO",
            "name": "Company Name",
            "conviction": "High/Medium/Low",
            "thesis": "string",
            "writeup": "string (3-4 paragraphs, detailed narrative)",
            "bull_case": "string",
            "bear_case": "string",
            "key_risks": ["risk1", "risk2", "risk3"],
            "catalysts": ["catalyst1", "catalyst2"],
            "position_size_pct": 5.0,
            "qualitative_score": 0.85
        }}
    ]
}}
"""
    return prompt


def _parse_claude_response(content: str) -> Dict[str, Any]:
    """Parse Claude's JSON response."""
    try:
        # Extract JSON from possible markdown formatting
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        elif content.strip().startswith("{"):
            json_str = content.strip()
        else:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = content[start:end]
            else:
                return {"error": "Could not extract JSON", "raw": content}

        return json.loads(json_str)

    except (json.JSONDecodeError, IndexError) as e:
        logger.warning(f"Failed to parse Claude response as JSON: {e}")
        return {"error": str(e), "raw": content[:2000]}


def _prepare_candidate_data(candidate: ScoredStock) -> Dict[str, Any]:
    """Convert a ScoredStock into a flat dict for the prompt."""
    v = candidate.valuation
    h = candidate.health
    s = candidate.stock_data

    return {
        "ticker": candidate.ticker,
        "name": candidate.name,
        "sector": candidate.sector,
        "current_price": v.current_price if v else 0,
        "intrinsic_value": v.intrinsic_value_per_share if v else 0,
        "intrinsic_value_conservative": v.intrinsic_value_conservative if v else 0,
        "margin_of_safety": v.margin_of_safety if v else 0,
        "margin_of_safety_conservative": v.margin_of_safety_conservative if v else 0,
        "health_grade": h.grade if h else "N/A",
        "avg_roe": s.avg_roe if s else 0,
        "debt_to_equity": s.debt_to_equity if s else 0,
        "current_ratio": s.current_ratio if s else 0,
        "earnings_cagr": v.earnings_growth_cagr if v else 0,
        "revenue_cagr": v.revenue_growth_cagr if v else 0,
        "avg_owner_earnings": v.avg_owner_earnings if v else 0,
        "growth_rate": v.estimated_growth_rate if v else 0,
        "research": candidate.perplexity_research or {},
    }


def analyze_and_select_top_picks(
    candidates: List[ScoredStock],
) -> Dict[str, Any]:
    """
    Use Claude to synthesize all data and select the final top picks.

    Args:
        candidates: List of ScoredStock objects with research data attached.

    Returns:
        Dict with 'market_commentary', 'sector_themes', and 'top_picks'.
    """
    client = _get_client()

    # Prepare candidate data for the prompt
    candidate_data = [_prepare_candidate_data(c) for c in candidates]

    prompt = _build_analysis_prompt(candidate_data)

    logger.info(f"Sending {len(candidates)} candidates to Claude for final analysis...")

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            system=BUFFETT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,  # Some creativity but mostly analytical
        )

        content = message.content[0].text
        result = _parse_claude_response(content)

        if "error" in result and "top_picks" not in result:
            logger.error(f"Claude analysis returned error: {result.get('error')}")
            # Fallback: use composite scores to select top picks
            return _fallback_selection(candidates)

        # Extract qualitative scores from Claude's response
        top_picks = result.get("top_picks", [])
        logger.info(f"Claude selected {len(top_picks)} top picks:")
        for pick in top_picks:
            logger.info(
                f"  #{pick.get('rank', '?')} {pick.get('ticker', '?')} — "
                f"Conviction: {pick.get('conviction', '?')}, "
                f"Position: {pick.get('position_size_pct', '?')}%"
            )

        return result

    except Exception as e:
        logger.error(f"Claude analysis failed: {e}")
        return _fallback_selection(candidates)


def _fallback_selection(candidates: List[ScoredStock]) -> Dict[str, Any]:
    """Fallback: select top picks based purely on composite scores."""
    logger.warning("Using fallback selection (composite scores only)")

    top_picks = []
    for i, c in enumerate(candidates[:FINAL_TOP_PICKS]):
        top_picks.append({
            "rank": i + 1,
            "ticker": c.ticker,
            "name": c.name,
            "conviction": "Medium",
            "thesis": f"Selected based on {c.valuation.margin_of_safety:.0%} margin of safety and {c.health.grade} financial health grade.",
            "writeup": (
                f"{c.name} ({c.ticker}) presents a compelling value opportunity on the TSX. "
                f"Trading at ${c.valuation.current_price:.2f} against our estimated intrinsic value of "
                f"${c.valuation.intrinsic_value_per_share:.2f}, the stock offers a "
                f"{c.valuation.margin_of_safety:.0%} margin of safety based on Buffett's Owner Earnings DCF model.\n\n"
                f"The company earned a financial health grade of {c.health.grade}, with "
                f"{c.health.passed_checks} out of {c.health.total_checks} quality checks passed. "
                f"Note: This writeup was generated from quantitative data only, as the Claude API "
                f"was unavailable for full qualitative synthesis. We recommend conducting additional "
                f"qualitative research on competitive moat, management quality, and industry dynamics "
                f"before acting on this recommendation."
            ),
            "bull_case": "Strong quantitative metrics suggest undervaluation.",
            "bear_case": "Qualitative analysis unavailable — exercise caution.",
            "key_risks": ["Qualitative analysis was not performed"],
            "catalysts": ["Reversion to intrinsic value"],
            "position_size_pct": 100 / FINAL_TOP_PICKS,
            "qualitative_score": c.qualitative_score,
        })

    return {
        "market_commentary": "Analysis performed using quantitative data only (Claude API unavailable).",
        "sector_themes": "N/A",
        "top_picks": top_picks,
    }
