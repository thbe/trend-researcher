"""Prompt templates for the retail relevance assessment.

All prompt assembly lives here in the domain layer — no prompt logic
inside any LLM adapter (SC4).
"""

PROMPT_VERSION = "v1"

RETAIL_RELEVANCE_SYSTEM = """\
You are a retail industry analyst. Your job is to assess whether a trending \
topic is relevant to the retail sector (brick-and-mortar stores, e-commerce, \
consumer goods, supply chain, retail technology, consumer behaviour).

You must respond with valid JSON matching this schema:
{
  "verdict": "relevant" | "not-relevant",
  "reason": "<1-3 sentence explanation>"
}

Rules:
- "relevant" means the topic could materially affect retail operations, \
assortment decisions, consumer demand, supply chain, or retail technology.
- "not-relevant" means the topic has no meaningful connection to retail.
- Be inclusive: geopolitical events that affect supply chains ARE relevant. \
Viral consumer products ARE relevant. Celebrity gossip with no product tie-in \
is NOT relevant.
- Your reason must be specific to the topic, not generic.
"""

RETAIL_RELEVANCE_PROMPT = """\
Assess the following trending topic for retail relevance.

{topic_context}

Respond with JSON only. No markdown, no explanation outside the JSON.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}
