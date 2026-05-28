"""Tests for the framework-aware AssessmentPipeline (plan 10-03 T06).

Verifies:
  - dispatch on framework_key + framework_id
  - ONE retry on schema-validation failure
  - persisted SQL includes framework_id + structured_output
  - backwards-compat: no framework arg → default 'verdict'

No real DB / no real LLM — fakes for ``LLMPort``, ``RAGPort``, session
factory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from assessor.domain.frameworks.verdict import VERDICT_FRAMEWORK_ID
from assessor.domain.frameworks.swot import SWOT_FRAMEWORK_ID
from assessor.domain.pipeline import AssessmentPipeline
from assessor.ports.rag import TopicContext


# --- fakes ------------------------------------------------------------------


class _FakeTopic:
    title = "T"
    description = "D"
    first_seen_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    last_seen_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    observation_count = 1


def _make_context() -> TopicContext:
    return TopicContext(_FakeTopic(), ["src-a: x"])


class _FakeRAG:
    """RAGPort fake — returns a context for any topic_id."""

    async def get_topic_context(self, topic_id: str) -> TopicContext | None:
        return _make_context()

    async def get_unassessed_topic_ids(self, limit: int = 50) -> list[str]:
        return []


class _FakeLLM:
    """LLMPort fake — returns a queue of canned responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, messages, *, model_id=None, response_schema=None):
        self.calls += 1
        if not self._responses:
            return {"content": "{}", "model": model_id or "fake"}
        return self._responses.pop(0)


class _FakeSession:
    """Captures the INSERT params for assertion."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.committed = False

    async def execute(self, statement, params=None):
        # SQL text(...) wraps a TextClause whose ``text`` attribute is the SQL.
        sql = getattr(statement, "text", str(statement))
        self.executed.append((sql, params or {}))
        return MagicMock()

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _session_factory():
    """Returns a session per-call AND keeps a handle on the last session for
    assertions."""
    captured: dict[str, _FakeSession] = {}

    def factory() -> _FakeSession:
        s = _FakeSession()
        captured["last"] = s
        return s

    factory.captured = captured  # type: ignore[attr-defined]
    return factory


# --- pipeline tests ---------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_default_framework_is_verdict():
    """No framework arg → uses 'verdict' and writes verdict framework_id."""
    llm = _FakeLLM([{
        "content": '{"verdict": "relevant", "reason": "r"}',
        "model": "test-model",
    }])
    factory = _session_factory()
    pipe = AssessmentPipeline(
        llm=llm, rag=_FakeRAG(), session_factory=factory,
        department_id="dept-x", model_id="test-model",
    )
    result = await pipe.assess_topic("topic-1")

    assert result is not None
    assert result["framework_key"] == "verdict"
    assert result["framework_id"] == VERDICT_FRAMEWORK_ID
    assert result["relevance_verdict"] == "relevant"
    assert result["prompt_version"] == "v4"

    sess = factory.captured["last"]
    assert sess.committed
    sql, params = sess.executed[0]
    assert "INSERT INTO business_cases" in sql
    assert params["framework_id"] == VERDICT_FRAMEWORK_ID
    assert params["department_id"] == "dept-x"
    assert json.loads(params["structured_output"])["verdict"] == "relevant"


@pytest.mark.asyncio
async def test_pipeline_dispatches_on_framework_key():
    """framework_key='swot' → swot framework_id persisted."""
    swot_payload = {
        "strengths": [], "weaknesses": [], "opportunities": [], "threats": [],
        "verdict": "relevant", "reason": "r",
    }
    llm = _FakeLLM([{"content": json.dumps(swot_payload), "model": "m"}])
    factory = _session_factory()
    pipe = AssessmentPipeline(
        llm=llm, rag=_FakeRAG(), session_factory=factory,
        department_id="dept-x",
    )
    result = await pipe.assess_topic("t-1", framework_key="swot")

    assert result["framework_key"] == "swot"
    assert result["framework_id"] == SWOT_FRAMEWORK_ID
    _, params = factory.captured["last"].executed[0]
    assert params["framework_id"] == SWOT_FRAMEWORK_ID
    assert params["prompt_version"] == "swot.v1"


@pytest.mark.asyncio
async def test_pipeline_retries_once_on_schema_validation_failure():
    """Bad JSON on first attempt, good JSON on second → one extra LLM call,
    final persist uses the second response."""
    bad = {"content": '{"verdict": "maybe", "reason": "x"}', "model": "m"}  # invalid enum
    good = {"content": '{"verdict": "relevant", "reason": "ok"}', "model": "m"}
    llm = _FakeLLM([bad, good])
    factory = _session_factory()
    pipe = AssessmentPipeline(
        llm=llm, rag=_FakeRAG(), session_factory=factory,
        department_id="d",
    )
    result = await pipe.assess_topic("t-1")

    assert llm.calls == 2, "expected exactly one retry"
    assert result["relevance_verdict"] == "relevant"
    assert result["relevance_reason"] == "ok"


@pytest.mark.asyncio
async def test_pipeline_persists_fallback_after_two_failures():
    """Two bad attempts → falls back to framework.parse_output for the row.

    Verdict framework returns a not-relevant stub so the row still persists
    rather than blowing up the batch.
    """
    bad = {"content": "not json", "model": "m"}
    llm = _FakeLLM([bad, bad])
    factory = _session_factory()
    pipe = AssessmentPipeline(
        llm=llm, rag=_FakeRAG(), session_factory=factory,
        department_id="d",
    )
    result = await pipe.assess_topic("t-1")

    assert llm.calls == 2
    assert result["relevance_verdict"] == "not-relevant"
    assert result["relevance_reason"].startswith("LLM response parse failure:")


@pytest.mark.asyncio
async def test_pipeline_returns_none_when_topic_missing():
    class _MissingRAG:
        async def get_topic_context(self, topic_id):
            return None
        async def get_unassessed_topic_ids(self, limit=50):
            return []

    llm = _FakeLLM([])
    factory = _session_factory()
    pipe = AssessmentPipeline(
        llm=llm, rag=_MissingRAG(), session_factory=factory,
        department_id="d",
    )
    result = await pipe.assess_topic("missing")
    assert result is None
    assert llm.calls == 0
