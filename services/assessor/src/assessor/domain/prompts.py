"""Prompt templates for the retail relevance assessment.

All prompt assembly lives here in the domain layer — no prompt logic
inside any LLM adapter (SC4).
"""

PROMPT_VERSION = "v1"

DEFAULT_BUSINESS_CONTEXT = """\
We are a large retail company (grocery + general merchandise). \
Topics are relevant if they represent either:
- OPPORTUNITY: viral products, trending categories, or consumer behaviour shifts we should react to in assortment/marketing
- RISK: supply chain disruptions, geopolitical events, natural disasters, regulatory changes, or reputational threats that could impact operations
Score relevance from the perspective of a retail category manager or risk officer."""

RETAIL_RELEVANCE_SYSTEM = """\
You are a business analyst. Your job is to assess whether a trending \
topic is relevant to the operator's business based on the context they provide.

You must respond with valid JSON matching this schema:
{{
  "verdict": "relevant" | "not-relevant",
  "category": "opportunity" | "risk" | "neutral",
  "reason": "<1-3 sentence explanation>"
}}

Rules:
- "relevant" means the topic could materially affect the business as described in the business context.
- "not-relevant" means the topic has no meaningful connection to the business.
- "category" classifies relevant topics: "opportunity" (growth, new products, trends to capitalise on) \
or "risk" (threats, disruptions, negative impact). Use "neutral" only for not-relevant topics.
- Be inclusive: anything that could require action from the business is relevant.
- Your reason must be specific to the topic, not generic.

BUSINESS CONTEXT:
{business_context}
"""

RETAIL_RELEVANCE_PROMPT = """\
Assess the following trending topic for relevance to the business described above.

{topic_context}

Respond with JSON only. No markdown, no explanation outside the JSON.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "category": {"type": "string", "enum": ["opportunity", "risk", "neutral"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}
