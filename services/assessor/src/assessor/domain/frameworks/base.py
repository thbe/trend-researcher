"""Framework Protocol — shape every assessment framework must implement."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import jsonschema

from assessor.ports.rag import TopicContext


@dataclass(frozen=True)
class AIConfig:
    """Per-dept prompt knobs passed into every framework.

    Mirrors the historical ``business_context`` / ``opportunity_criteria`` /
    ``risk_criteria`` triple stored on ``ai_configs`` (and overridable per
    pipeline). Frameworks may ignore fields that are not meaningful for them
    (e.g. PESTLE does not need explicit opportunity / risk lists).
    """

    business_context: str
    opportunity_criteria: str
    risk_criteria: str


@dataclass(frozen=True)
class FrameworkDefinition:
    """Static metadata used to seed the ``assessment_frameworks`` table."""

    key: str
    name: str
    description: str
    display_component: str
    prompt_version: str
    json_schema: dict[str, Any]


@runtime_checkable
class Framework(Protocol):
    """Contract every assessment framework implements.

    Frameworks are pure: no DB access, no LLM calls. They produce LLM input
    (``build_messages``) and parse LLM output (``parse_output``). The pipeline
    owns I/O.
    """

    KEY: str
    NAME: str
    DESCRIPTION: str
    DISPLAY_COMPONENT: str
    PROMPT_VERSION: str
    JSON_SCHEMA: dict[str, Any]

    def build_messages(
        self, context: TopicContext, ai_config: AIConfig
    ) -> list[dict[str, str]]:
        """Build the message list to feed ``LLMPort.complete``.

        Returns ``[{"role": ..., "content": ...}, ...]``.
        """
        ...

    def parse_output(self, raw: str) -> dict[str, Any]:
        """Parse raw LLM text into the structured dict matching ``JSON_SCHEMA``.

        Raises ``json.JSONDecodeError`` if no parseable JSON is found.
        Does NOT validate against the schema — caller validates separately so
        the pipeline can decide on retry vs hard-fail.
        """
        ...

    def definition(self) -> FrameworkDefinition:
        """Return seed metadata for this framework."""
        ...


# --- shared helpers ---------------------------------------------------------


_FIRST_JSON_OBJECT = re.compile(r"\{", re.DOTALL)


def extract_first_json_object(raw: str) -> str:
    """Find the first balanced ``{...}`` block in ``raw``.

    Tolerates LLMs that prefix/suffix the JSON with markdown fences or prose.
    Counts braces while ignoring those inside double-quoted strings (with
    backslash escapes). Raises ``ValueError`` if no balanced object is found.
    """
    match = _FIRST_JSON_OBJECT.search(raw)
    if match is None:
        raise ValueError("no '{' found in LLM output")
    start = match.start()
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    raise ValueError("unbalanced JSON object in LLM output")


def parse_json_block(raw: str) -> dict[str, Any]:
    """Robust JSON-from-LLM-text helper used by every framework's ``parse_output``."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    block = extract_first_json_object(raw)
    return json.loads(block)


def validate_structured_output(data: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate ``data`` against ``schema``. Raises ``jsonschema.ValidationError`` on mismatch."""
    jsonschema.validate(instance=data, schema=schema)


__all__ = [
    "AIConfig",
    "Framework",
    "FrameworkDefinition",
    "extract_first_json_object",
    "parse_json_block",
    "validate_structured_output",
]
