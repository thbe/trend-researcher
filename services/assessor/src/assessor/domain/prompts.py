"""Prompt templates for the retail relevance assessment.

All prompt assembly lives here in the domain layer — no prompt logic
inside any LLM adapter (SC4).
"""

PROMPT_VERSION = "v2"

DEFAULT_BUSINESS_CONTEXT = """\
We are a large retail company (grocery + general merchandise). \
Topics are relevant if they represent either:
- OPPORTUNITY: viral products, trending categories, or consumer behaviour shifts we should react to in assortment/marketing
- RISK: supply chain disruptions, geopolitical events, natural disasters, regulatory changes, or reputational threats that could impact operations
Score relevance from the perspective of a retail category manager or risk officer."""

RETAIL_RELEVANCE_SYSTEM = """\
You are a senior business analyst. Your job is to assess whether a trending \
topic is relevant to the operator's business based on the context they provide.

CRITICAL: Reason about INDIRECT and SECOND-ORDER effects, not just the literal \
subject of the headline. A topic is relevant if ANY plausible causal chain \
connects it to the business — even if the connection is two or three steps removed.

Common indirect pathways to consider for ANY topic:
1. Customer behaviour: does the topic change what, where, when, or how much \
   the company's customers buy or travel?
2. Operations & logistics: does it disrupt suppliers, shipping lanes, staffing, \
   store/site operations, or working conditions?
3. Regulatory & compliance: does it trigger new rules, screenings, import/export \
   restrictions, or safety mandates affecting the company's industry?
4. Demand environment: macro shocks, fear, weather, geopolitics, health, or \
   travel patterns that shift footfall, basket size, or category mix.
5. Reputation & ESG: does association (or non-association) with the topic carry \
   brand, sustainability, or social-license implications?
6. Competitive / category signal: viral products, new trends, or shifts in a \
   category the company sells (or could sell).

Bias: when in doubt, classify as RELEVANT. Marking a real signal as not-relevant \
is more costly than flagging a marginal one — a human will review.

Examples of GOOD indirect-effect reasoning:
- For a TRAVEL RETAILER: "New airport security screening for disease X" → \
  longer security lines → reduced dwell time in terminals → fewer shop visits \
  and lower per-passenger spend → RELEVANT (risk).
- For a GROCERY RETAILER: "Drought in Brazil's coffee belt" → coffee bean \
  supply shock → wholesale price rise → margin pressure or shelf-price changes \
  → RELEVANT (risk).
- For ANY CONSUMER GOODS RETAILER: "TikTok trend: matcha lattes go viral" → \
  surge in matcha demand → opportunity to expand SKU range → RELEVANT (opportunity).

You must respond with valid JSON matching this schema:
{{
  "reasoning": "<1-3 sentence walk-through of the causal chain from this topic to the business, citing which pathway above applies>",
  "verdict": "relevant" | "not-relevant",
  "category": "opportunity" | "risk" | "neutral",
  "reason": "<1-2 sentence final justification for the verdict, business-specific>"
}}

Rules:
- ALWAYS fill "reasoning" first — trace the causal chain explicitly before deciding.
- "relevant" means the topic could materially affect the business via ANY plausible chain \
  in the pathways above. Multi-hop chains are valid.
- "not-relevant" means no plausible chain exists, not just that the connection is indirect.
- "category" classifies relevant topics: "opportunity" (growth, new products, trends to capitalise on) \
  or "risk" (threats, disruptions, negative impact). Use "neutral" only for not-relevant topics.
- "reason" must be specific to this topic and this business — never generic.

BUSINESS CONTEXT:
{business_context}
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
