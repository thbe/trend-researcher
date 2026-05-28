"""SWOT framework — strengths / weaknesses / opportunities / threats matrix."""

from __future__ import annotations

from typing import Any

from assessor.domain.frameworks.base import (
    AIConfig,
    FrameworkDefinition,
    parse_json_block,
)
from assessor.ports.rag import TopicContext

SWOT_FRAMEWORK_ID = "00000000-0000-0000-0000-000000000011"

PROMPT_VERSION = "swot.v1"

_CELL = {
    "type": "object",
    "properties": {
        "point": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["point", "rationale"],
}

JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "strengths": {"type": "array", "items": _CELL},
        "weaknesses": {"type": "array", "items": _CELL},
        "opportunities": {"type": "array", "items": _CELL},
        "threats": {"type": "array", "items": _CELL},
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "reason": {"type": "string"},
        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": [
        "strengths",
        "weaknesses",
        "opportunities",
        "threats",
        "verdict",
        "reason",
    ],
}


SWOT_SYSTEM = """\
You are a senior business analyst running a SWOT assessment on a trending \
topic. Evaluate it as a STRATEGIC SIGNAL for the operator's business — what \
internal Strengths it could exploit, which Weaknesses it exposes, which \
Opportunities it opens, and which Threats it creates.

Apply the same materiality discipline as a verdict assessment: each cell entry \
must name a concrete mechanism, not a vague generality. Empty cells are \
acceptable when nothing material applies — do NOT pad.

Top-level fields:
- "verdict": "relevant" if ANY cell has at least one material entry; \
  "not-relevant" if all four cells are essentially empty or speculative.
- "importance": 0-100 integer — 0 = noise, 100 = drop-everything signal. \
  Calibrate against the operator's listed opportunity / risk criteria.
- "confidence": 0.0-1.0 — your confidence that this assessment would hold up \
  under scrutiny from a domain expert.
- "reason": 1-2 sentence summary citing the dominant cell(s).

Each cell is a list of objects:
  {{"point": "<short label, <=12 words>", "rationale": "<concrete mechanism>"}}

Respond with strict JSON matching this schema:
{{
  "strengths":     [{{"point": "...", "rationale": "..."}}, ...],
  "weaknesses":    [{{"point": "...", "rationale": "..."}}, ...],
  "opportunities": [{{"point": "...", "rationale": "..."}}, ...],
  "threats":       [{{"point": "...", "rationale": "..."}}, ...],
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

SWOT_USER = """\
Run a SWOT assessment on the following trending topic.

{topic_context}

Respond with JSON only. No markdown fences, no prose outside the JSON.
"""


class SwotFramework:
    """SWOT — four-quadrant strategic assessment."""

    KEY = "swot"
    NAME = "SWOT"
    DESCRIPTION = (
        "Strengths, Weaknesses, Opportunities, Threats — classic four-quadrant "
        "strategic assessment."
    )
    DISPLAY_COMPONENT = "SwotCard"
    PROMPT_VERSION = PROMPT_VERSION
    JSON_SCHEMA = JSON_SCHEMA

    def build_messages(
        self, context: TopicContext, ai_config: AIConfig
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "user",
                "content": SWOT_SYSTEM.format(
                    business_context=ai_config.business_context,
                    opportunity_criteria=ai_config.opportunity_criteria,
                    risk_criteria=ai_config.risk_criteria,
                ),
            },
            {
                "role": "user",
                "content": SWOT_USER.format(topic_context=context.to_prompt_text()),
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


__all__ = ["JSON_SCHEMA", "PROMPT_VERSION", "SWOT_FRAMEWORK_ID", "SwotFramework"]
