"""Tests for the framework registry + per-framework rendering / parsing.

Phase 10 (plan 10-03 T07). Pure unit tests — no DB, no LLM, no async setup.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from assessor.domain.frameworks import registry
from assessor.domain.frameworks.base import (
    AIConfig,
    extract_first_json_object,
    parse_json_block,
    validate_structured_output,
)
from assessor.domain.frameworks.pestle import PESTLE_FRAMEWORK_ID, PestleFramework
from assessor.domain.frameworks.swot import SWOT_FRAMEWORK_ID, SwotFramework
from assessor.domain.frameworks.verdict import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_OPPORTUNITY_CRITERIA,
    DEFAULT_RISK_CRITERIA,
    VERDICT_FRAMEWORK_ID,
    VerdictFramework,
)


FIXTURES = Path(__file__).parent / "fixtures"


# --- fixtures ---------------------------------------------------------------


class _FakeTopic:
    title = "Test topic title"
    description = "Test topic description"
    first_seen_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    last_seen_at = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    observation_count = 7


class _FakeContext:
    """Minimal stand-in for TopicContext — to_prompt_text must match the
    real implementation byte-for-byte so the golden file stays stable."""

    topic = _FakeTopic()
    source_summaries = ["source-a: hello", "source-b: world"]

    def to_prompt_text(self) -> str:
        lines = [
            f"Title: {self.topic.title}",
            f"Description: {self.topic.description or '(none)'}",
            f"First seen: {self.topic.first_seen_at}",
            f"Last seen: {self.topic.last_seen_at}",
            f"Observation count: {self.topic.observation_count}",
            f"Sources ({len(self.source_summaries)}):",
        ]
        for s in self.source_summaries:
            lines.append(f"  - {s}")
        return "\n".join(lines)


@pytest.fixture
def ai_config() -> AIConfig:
    return AIConfig(
        business_context=DEFAULT_BUSINESS_CONTEXT,
        opportunity_criteria=DEFAULT_OPPORTUNITY_CRITERIA,
        risk_criteria=DEFAULT_RISK_CRITERIA,
    )


# --- registry ---------------------------------------------------------------


def test_registry_has_all_three_frameworks():
    assert set(registry.FRAMEWORKS.keys()) == {"verdict", "swot", "pestle"}


def test_get_by_key_returns_correct_instance():
    assert isinstance(registry.get_by_key("verdict"), VerdictFramework)
    assert isinstance(registry.get_by_key("swot"), SwotFramework)
    assert isinstance(registry.get_by_key("pestle"), PestleFramework)


def test_get_by_key_unknown_raises():
    with pytest.raises(registry.FrameworkNotFoundError):
        registry.get_by_key("does-not-exist")


def test_all_definitions_keys_match_registry():
    defs = registry.all_definitions()
    assert {d.key for d in defs} == set(registry.FRAMEWORKS.keys())


def test_well_known_ids_match_migration():
    # Hardcoded UUIDs in 0019_assessment_frameworks.py — drift here breaks
    # the framework_id round-trip from pipeline persist back to display.
    assert VERDICT_FRAMEWORK_ID == "00000000-0000-0000-0000-000000000010"
    assert SWOT_FRAMEWORK_ID == "00000000-0000-0000-0000-000000000011"
    assert PESTLE_FRAMEWORK_ID == "00000000-0000-0000-0000-000000000012"


# --- shared helpers ---------------------------------------------------------


def test_extract_first_json_object_handles_prose():
    raw = "Sure, here you go:\n```json\n{\"a\": 1, \"b\": \"x\"}\n```\nDone."
    assert extract_first_json_object(raw) == "{\"a\": 1, \"b\": \"x\"}"


def test_extract_first_json_object_ignores_braces_in_strings():
    raw = '{"key": "value with { brace }"}'
    assert extract_first_json_object(raw) == raw


def test_parse_json_block_falls_back_on_prose_wrapping():
    assert parse_json_block("noise {\"x\": 1} trailing") == {"x": 1}


def test_validate_structured_output_raises_on_mismatch():
    with pytest.raises(jsonschema.ValidationError):
        validate_structured_output(
            {"verdict": "maybe"},
            {"type": "object", "properties": {"verdict": {"enum": ["yes", "no"]}}},
        )


# --- verdict framework ------------------------------------------------------


def test_verdict_prompt_identity(ai_config):
    """Pin the rendered verdict prompt byte-for-byte to its golden snapshot.

    If this test changes, EVERY existing business_cases row's prompt_version
    is invalidated — re-assessments will produce drifted output. Bump
    ``PROMPT_VERSION`` in lockstep when this snapshot must change.
    """
    msgs = VerdictFramework().build_messages(_FakeContext(), ai_config)
    rendered = "\n\n---MESSAGE_SEPARATOR---\n\n".join(
        f"{m['role']}:\n{m['content']}" for m in msgs
    )
    golden = (FIXTURES / "verdict_prompt_golden.txt").read_text()
    assert rendered == golden, "verdict prompt drifted from golden snapshot"


def test_verdict_parse_output_valid_json():
    raw = '{"verdict": "relevant", "reason": "matches risk criteria"}'
    parsed = VerdictFramework().parse_output(raw)
    assert parsed["verdict"] == "relevant"
    assert parsed["reason"] == "matches risk criteria"


def test_verdict_parse_output_invalid_returns_fallback():
    """Mirrors pre-refactor pipeline.py:97-109 fallback exactly so existing
    business_cases rows that were stored after a parse failure remain
    reproducible."""
    parsed = VerdictFramework().parse_output("this is not json at all")
    assert parsed["verdict"] == "not-relevant"
    assert parsed["reason"].startswith("LLM response parse failure:")


# --- swot framework ---------------------------------------------------------


def test_swot_parse_output_validates_against_schema(ai_config):
    fw = SwotFramework()
    raw = (
        '{"strengths": [{"point": "p", "rationale": "r"}],'
        ' "weaknesses": [], "opportunities": [], "threats": [],'
        ' "verdict": "relevant", "reason": "ok",'
        ' "importance": 75, "confidence": 0.8}'
    )
    parsed = fw.parse_output(raw)
    # Should not raise.
    validate_structured_output(parsed, fw.JSON_SCHEMA)
    assert parsed["importance"] == 75


def test_swot_schema_rejects_missing_quadrant():
    fw = SwotFramework()
    with pytest.raises(jsonschema.ValidationError):
        validate_structured_output(
            {"strengths": [], "weaknesses": [], "opportunities": [],
             "verdict": "relevant", "reason": "missing threats"},
            fw.JSON_SCHEMA,
        )


def test_swot_build_messages_uses_ai_config(ai_config):
    msgs = SwotFramework().build_messages(_FakeContext(), ai_config)
    assert len(msgs) == 2
    assert ai_config.business_context in msgs[0]["content"]
    assert "Test topic title" in msgs[1]["content"]


# --- pestle framework -------------------------------------------------------


def test_pestle_parse_output_validates_against_schema(ai_config):
    fw = PestleFramework()
    cell = {"relevance": "med", "notes": "n"}
    raw = (
        '{"political": ' + str(cell).replace("'", '"') + ","
        '"economic": ' + str(cell).replace("'", '"') + ","
        '"social": ' + str(cell).replace("'", '"') + ","
        '"technological": ' + str(cell).replace("'", '"') + ","
        '"legal": ' + str(cell).replace("'", '"') + ","
        '"environmental": ' + str(cell).replace("'", '"') + ","
        '"verdict": "relevant", "reason": "ok"}'
    )
    parsed = fw.parse_output(raw)
    validate_structured_output(parsed, fw.JSON_SCHEMA)


def test_pestle_schema_rejects_invalid_relevance_enum():
    fw = PestleFramework()
    cell_bad = {"relevance": "extreme", "notes": "n"}
    cell_ok = {"relevance": "low", "notes": "n"}
    payload = {
        "political": cell_bad, "economic": cell_ok, "social": cell_ok,
        "technological": cell_ok, "legal": cell_ok, "environmental": cell_ok,
        "verdict": "relevant", "reason": "ok",
    }
    with pytest.raises(jsonschema.ValidationError):
        validate_structured_output(payload, fw.JSON_SCHEMA)
