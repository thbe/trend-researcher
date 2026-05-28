"""Verdict framework — 1:1 port of the historical single-tenant prompt.

This file IS the prior ``prompts.py`` content, rehoused as a Framework so the
multi-tenant pipeline can dispatch on ``framework_id``. The prompt strings,
``PROMPT_VERSION``, and ``JSON_SCHEMA`` are preserved verbatim. T07's
golden-file test pins the rendered prompt byte-for-byte against the pre-
refactor output so re-assessment of an existing topic produces identical
``business_cases`` rows.
"""

from __future__ import annotations

from typing import Any

from assessor.domain.frameworks.base import (
    AIConfig,
    FrameworkDefinition,
    parse_json_block,
)
from assessor.ports.rag import TopicContext

# Hardcoded UUID matching packages/core/alembic/versions/0019_assessment_frameworks.py.
# Kept here so adapters can dispatch by key without a DB round-trip when the
# framework_id is already known.
VERDICT_FRAMEWORK_ID = "00000000-0000-0000-0000-000000000010"

PROMPT_VERSION = "v4"

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

You may reason about INDIRECT and SECOND-ORDER effects, not just the literal \
subject of the headline — but ONLY when the chain is concrete and material. \
A chain is concrete when each step names a specific mechanism (e.g. "screening \
slows boarding → passenger volume drops → airport duty-free footfall drops") \
rather than vague generalities ("could shift consumer behaviour", "might affect \
demand", "may impact assortment"). A chain is material when the predicted \
impact would plausibly change a buying, ops, or risk decision within the next \
3–12 months.

MATERIALITY GATE — mark "relevant" ONLY if ALL of the following hold:
1. The chain ends on a SPECIFIC listed opportunity or risk criterion, naming it.
2. Each step in the chain has a real mechanism, not a generic phrase.
3. The effect is large enough to matter at the business's scale (a category \
   manager or risk officer would actually take action or watch this).
4. The topic is more than entertainment, lifestyle fluff, sports results, \
   celebrity gossip, horoscopes, opinion columns, or human-interest stories \
   with no concrete tie to inventory, footfall, regulation, operations, or \
   competitive position.

If the only way you can connect the topic to a criterion requires phrases \
like "could potentially", "may drive temporary shifts", "might influence", \
"as people may consider" — that is NOT a material chain. Mark "not-relevant".

Default: when the chain is weak, abstract, or speculative, classify as \
NOT-RELEVANT. False positives flood the operator's queue and erode trust; be \
strict. Only genuinely concrete and material signals should pass.

You must respond with valid JSON matching this schema:
{{
  "reasoning": "<1-3 sentence walk-through of the causal chain from this topic to a SPECIFIC opportunity or risk criterion listed below, with concrete mechanisms at each step>",
  "verdict": "relevant" | "not-relevant",
  "category": "opportunity" | "risk" | "neutral",
  "reason": "<1-2 sentence final justification, citing which specific criterion this matches AND why the impact is material>"
}}

Rules:
- ALWAYS fill "reasoning" first — trace the causal chain explicitly with concrete mechanisms before deciding.
- A topic is "relevant" ONLY if all four materiality-gate conditions hold.
- "not-relevant" means the chain is missing, abstract, speculative, or immaterial — including topics that are entertainment, lifestyle, gossip, horoscopes, or sports unless they tie concretely to a listed criterion.
- "category" must be "opportunity" or "risk" matching whichever criterion the topic hits; use "neutral" only when verdict is "not-relevant".
- "reason" must reference the specific criterion matched AND why the impact is material — never generic.

EXAMPLES OF NOT-RELEVANT (do not mark these as relevant):
- "Your Love Horoscope For Friday" — lifestyle/entertainment, no concrete chain to assortment or operations.
- "Celebrity X spotted at restaurant Y" — gossip, no material business mechanism.
- "Local sports team wins championship" — unless directly tied to a specific listed criterion (e.g. branded merchandise category), this is human-interest only.
- "10 best summer reads" — opinion/listicle with no buying, regulatory, or operational signal.

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

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "category": {"type": "string", "enum": ["opportunity", "risk", "neutral"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}


class VerdictFramework:
    """Single relevance verdict — the historical Stage-2 pipeline as a framework."""

    KEY = "verdict"
    NAME = "Relevance Verdict"
    DESCRIPTION = (
        "Binary relevance + 1-2 sentence reason. The original single-tenant "
        "assessment shape, preserved 1:1 as a framework so all pre-Phase-10 "
        "business_cases migrate cleanly."
    )
    DISPLAY_COMPONENT = "VerdictCard"
    PROMPT_VERSION = PROMPT_VERSION
    JSON_SCHEMA = RESPONSE_SCHEMA

    def build_messages(
        self, context: TopicContext, ai_config: AIConfig
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "user",
                "content": RETAIL_RELEVANCE_SYSTEM.format(
                    business_context=ai_config.business_context,
                    opportunity_criteria=ai_config.opportunity_criteria,
                    risk_criteria=ai_config.risk_criteria,
                ),
            },
            {
                "role": "user",
                "content": RETAIL_RELEVANCE_PROMPT.format(
                    topic_context=context.to_prompt_text()
                ),
            },
        ]

    def parse_output(self, raw: str) -> dict[str, Any]:
        """Parse a verdict JSON payload. Mirrors pre-refactor pipeline behaviour:
        on JSON failure, return a not-relevant fallback so the row still persists.
        """
        try:
            return parse_json_block(raw)
        except (ValueError, Exception):
            # Match historical pipeline.py:97-109 fallback exactly so existing
            # business_cases rows that were stored after a parse failure remain
            # reproducible.
            return {
                "verdict": "not-relevant",
                "reason": f"LLM response parse failure: {raw[:100]}",
            }

    def definition(self) -> FrameworkDefinition:
        return FrameworkDefinition(
            key=self.KEY,
            name=self.NAME,
            description=self.DESCRIPTION,
            display_component=self.DISPLAY_COMPONENT,
            prompt_version=self.PROMPT_VERSION,
            json_schema=self.JSON_SCHEMA,
        )


__all__ = [
    "DEFAULT_BUSINESS_CONTEXT",
    "DEFAULT_OPPORTUNITY_CRITERIA",
    "DEFAULT_RISK_CRITERIA",
    "PROMPT_VERSION",
    "RESPONSE_SCHEMA",
    "RETAIL_RELEVANCE_PROMPT",
    "RETAIL_RELEVANCE_SYSTEM",
    "VERDICT_FRAMEWORK_ID",
    "VerdictFramework",
]
