"""Prompt templates for the retail relevance assessment.

All prompt assembly lives here in the domain layer — no prompt logic
inside any LLM adapter (SC4).

Opportunity and risk criteria are supplied per-deployment via the AI config
(see `ai_config.opportunity_criteria` / `ai_config.risk_criteria`). The
operator describes what counts as opportunity / risk for THEIR business
(e.g. travel retail vs grocery vs pharma) and the prompt substitutes those
verbatim. This keeps the prompt market-agnostic in code while still giving
the LLM concrete, business-specific anchors at runtime.
"""

PROMPT_VERSION = "v3"

DEFAULT_BUSINESS_CONTEXT = """\
We are a large retail company (grocery + general merchandise). \
Score relevance from the perspective of a category manager or risk officer."""

DEFAULT_OPPORTUNITY_CRITERIA = """\
- Viral products, trending categories, or consumer behaviour shifts the business should react to in assortment / marketing
- Emerging trends within categories we sell (e.g. health, sustainability, premiumisation)
- New consumer segments or demographic shifts that expand our addressable market
- Competitor moves, exits, or whitespace we can capture
- New routes, sites, or channels that expand our footprint or audience"""

DEFAULT_RISK_CRITERIA = """\
- Supply chain disruptions affecting our core categories or key suppliers
- Geopolitical events, wars, sanctions, or trade restrictions impacting our markets
- Natural disasters, weather events, or health crises (pandemics, outbreaks) affecting demand or operations
- Regulatory changes (taxation, product bans, safety mandates, packaging or labelling rules)
- Reputational / ESG threats relevant to our brand, categories, or social licence
- Macro shocks that change customer footfall, basket size, or category mix"""

RETAIL_RELEVANCE_SYSTEM = """\
You are a senior business analyst. Your job is to assess whether a trending \
topic is relevant to the operator's business based on the business context, \
opportunity criteria, and risk criteria they provide.

CRITICAL: Reason about INDIRECT and SECOND-ORDER effects, not just the literal \
subject of the headline. A topic is relevant if ANY plausible causal chain — \
possibly two or three steps removed — connects it to at least one of the \
operator's opportunity or risk criteria listed below.

Bias: when in doubt, classify as RELEVANT. Marking a real signal as \
not-relevant is more costly than flagging a marginal one — a human will review.

You must respond with valid JSON matching this schema:
{{
  "reasoning": "<1-3 sentence walk-through of the causal chain from this topic to a SPECIFIC opportunity or risk criterion listed below>",
  "verdict": "relevant" | "not-relevant",
  "category": "opportunity" | "risk" | "neutral",
  "reason": "<1-2 sentence final justification, citing which specific criterion this matches>"
}}

Rules:
- ALWAYS fill "reasoning" first — trace the causal chain explicitly before deciding.
- A topic is "relevant" if it materially connects (directly or indirectly) to at least ONE listed opportunity or risk criterion.
- "not-relevant" means no plausible chain to ANY listed criterion exists.
- "category" must be "opportunity" or "risk" matching whichever criterion the topic hits; use "neutral" only when verdict is "not-relevant".
- "reason" must reference the specific criterion matched — never generic.

BUSINESS CONTEXT:
{business_context}

OPPORTUNITY CRITERIA — what counts as an opportunity for this business:
{opportunity_criteria}

RISK CRITERIA — what counts as a risk for this business:
{risk_criteria}
"""

RETAIL_RELEVANCE_PROMPT = """\
Assess the following trending topic for relevance to the business described above.

{topic_context}

Think through the causal chain step by step in the "reasoning" field, then \
decide. Respond with JSON only. No markdown, no explanation outside the JSON.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "category": {"type": "string", "enum": ["opportunity", "risk", "neutral"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}
