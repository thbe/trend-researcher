"""PESTLE framework — political/economic/social/technological/legal/environmental."""

from __future__ import annotations

from typing import Any

from assessor.domain.frameworks.base import (
    AIConfig,
    FrameworkDefinition,
    parse_json_block,
)
from assessor.ports.rag import TopicContext

PESTLE_FRAMEWORK_ID = "00000000-0000-0000-0000-000000000012"

PROMPT_VERSION = "pestle.v1"

_CELL = {
    "type": "object",
    "properties": {
        "relevance": {"type": "string", "enum": ["low", "med", "high"]},
        "notes": {"type": "string"},
    },
    "required": ["relevance", "notes"],
}

JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "political": _CELL,
        "economic": _CELL,
        "social": _CELL,
        "technological": _CELL,
        "legal": _CELL,
        "environmental": _CELL,
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "reason": {"type": "string"},
        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": [
        "political",
        "economic",
        "social",
        "technological",
        "legal",
        "environmental",
        "verdict",
        "reason",
    ],
}


PESTLE_SYSTEM = """\
You are a senior strategist running a PESTLE macro-environment scan on a \
trending topic. For each of the six cells, rate the topic's relevance to the \
operator's business and explain in 1-2 sentences. Use "low" / "med" / "high".

Cells:
- political:     governments, policy, regulation, geopolitics
- economic:      macro indicators, demand cycles, prices, FX
- social:        demographics, consumer behaviour, cultural shifts
- technological: new tech enabling or disrupting the business
- legal:         laws, compliance, litigation risk
- environmental: climate, sustainability, ESG, natural disasters

Top-level fields:
- "verdict": "relevant" if ANY cell is "med" or "high"; "not-relevant" if all \
  six are "low".
- "importance": 0-100 — calibrated against the operator's listed criteria.
- "confidence": 0.0-1.0.
- "reason": 1-2 sentences citing the dominant cell(s).

Be honest with "low" — most topics will be "low" in most cells.

Respond with strict JSON matching this schema:
{{
  "political":     {{"relevance": "low|med|high", "notes": "..."}},
  "economic":      {{"relevance": "low|med|high", "notes": "..."}},
  "social":        {{"relevance": "low|med|high", "notes": "..."}},
  "technological": {{"relevance": "low|med|high", "notes": "..."}},
  "legal":         {{"relevance": "low|med|high", "notes": "..."}},
  "environmental": {{"relevance": "low|med|high", "notes": "..."}},
  "verdict": "relevant" | "not-relevant",
  "reason": "<1-2 sentence summary>",
  "importance": 0-100,
  "confidence": 0.0-1.0
}}

BUSINESS CONTEXT:
{business_context}

OPPORTUNITY CRITERIA:
{opportunity_criteria}

RISK CRITERIA:
{risk_criteria}
"""

PESTLE_USER = """\
Run a PESTLE assessment on the following trending topic.

{topic_context}

Respond with JSON only. No markdown fences, no prose outside the JSON.
"""


class PestleFramework:
    """PESTLE — six-cell macro-environment scan."""

    KEY = "pestle"
    NAME = "PESTLE"
    DESCRIPTION = (
        "Political, Economic, Social, Technological, Legal, Environmental — "
        "macro-environment scan."
    )
    DISPLAY_COMPONENT = "PestleCard"
    PROMPT_VERSION = PROMPT_VERSION
    JSON_SCHEMA = JSON_SCHEMA

    def build_messages(
        self, context: TopicContext, ai_config: AIConfig
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "user",
                "content": PESTLE_SYSTEM.format(
                    business_context=ai_config.business_context,
                    opportunity_criteria=ai_config.opportunity_criteria,
                    risk_criteria=ai_config.risk_criteria,
                ),
            },
            {
                "role": "user",
                "content": PESTLE_USER.format(topic_context=context.to_prompt_text()),
            },
        ]

    def parse_output(self, raw: str) -> dict[str, Any]:
        return parse_json_block(raw)

    def definition(self) -> FrameworkDefinition:
        return FrameworkDefinition(
            key=self.KEY,
            name=self.NAME,
            description=self.DESCRIPTION,
            display_component=self.DISPLAY_COMPONENT,
            prompt_version=self.PROMPT_VERSION,
            json_schema=self.JSON_SCHEMA,
        )


__all__ = ["JSON_SCHEMA", "PESTLE_FRAMEWORK_ID", "PROMPT_VERSION", "PestleFramework"]
