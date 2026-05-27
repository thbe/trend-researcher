"""Assessment pipeline — orchestrates RAG retrieval + LLM call + persistence."""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assessor.domain.prompts import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_OPPORTUNITY_CRITERIA,
    DEFAULT_RISK_CRITERIA,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    RETAIL_RELEVANCE_PROMPT,
    RETAIL_RELEVANCE_SYSTEM,
)
from assessor.ports.llm import LLMPort
from assessor.ports.rag import RAGPort

_log = structlog.get_logger(__name__)


class AssessmentPipeline:
    """Single-shot RAG → LLM assessment pipeline (no agentic loop).

    Reads topic context from Postgres via RAGPort, sends to LLM via LLMPort,
    persists result to business_cases table.
    """

    def __init__(
        self,
        llm: LLMPort,
        rag: RAGPort,
        session_factory: async_sessionmaker[AsyncSession],
        department_id: str,
        model_id: str | None = None,
        business_context: str | None = None,
        opportunity_criteria: str | None = None,
        risk_criteria: str | None = None,
    ) -> None:
        """Create a pipeline bound to one department.

        Phase 10 (MT-006): ``department_id`` is REQUIRED — every
        ``business_cases`` row carries it (NOT NULL since migration 0017) so
        the same topic can be re-assessed independently per dept with
        different prompts / criteria / framework.
        """
        self._llm = llm
        self._rag = rag
        self._session_factory = session_factory
        self._department_id = department_id
        self._model_id = model_id
        self._business_context = business_context or DEFAULT_BUSINESS_CONTEXT
        self._opportunity_criteria = opportunity_criteria or DEFAULT_OPPORTUNITY_CRITERIA
        self._risk_criteria = risk_criteria or DEFAULT_RISK_CRITERIA

    async def assess_topic(self, topic_id: str) -> dict[str, Any] | None:
        """Assess a single topic and persist the result.

        Returns the business_case dict on success, None if topic not found.
        """
        context = await self._rag.get_topic_context(topic_id)
        if context is None:
            _log.warning("assessment.topic_not_found", topic_id=topic_id)
            return None

        # Build messages (prompt assembly lives here in domain, not in adapter)
        messages = [
            {"role": "user", "content": RETAIL_RELEVANCE_SYSTEM.format(
                business_context=self._business_context,
                opportunity_criteria=self._opportunity_criteria,
                risk_criteria=self._risk_criteria,
            )},
            {
                "role": "user",
                "content": RETAIL_RELEVANCE_PROMPT.format(
                    topic_context=context.to_prompt_text()
                ),
            },
        ]

        # Call LLM
        response = await self._llm.complete(
            messages,
            model_id=self._model_id,
            response_schema=RESPONSE_SCHEMA,
        )

        # Parse structured output
        parsed = response.get("parsed")
        if not parsed:
            # Try parsing content as JSON
            try:
                parsed = json.loads(response["content"])
            except (json.JSONDecodeError, KeyError):
                _log.error(
                    "assessment.parse_failed",
                    topic_id=topic_id,
                    content=response.get("content", "")[:200],
                )
                # Store as not-relevant with parse failure reason
                parsed = {
                    "verdict": "not-relevant",
                    "reason": f"LLM response parse failure: {response.get('content', '')[:100]}",
                }

        verdict = parsed.get("verdict", "not-relevant")
        category = parsed.get("category", "neutral")
        reason = parsed.get("reason", "No reason provided")
        model_used = response.get("model", self._model_id or "unknown")

        # Persist to business_cases (scoped to this pipeline's department).
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO business_cases
                        (topic_id, department_id, relevance_verdict, relevance_reason,
                         model_used, prompt_version, raw_response)
                    VALUES
                        (:topic_id, :department_id, :verdict, :reason,
                         :model_used, :prompt_version, :raw_response)
                """),
                {
                    "topic_id": topic_id,
                    "department_id": self._department_id,
                    "verdict": verdict,
                    "reason": reason,
                    "model_used": model_used,
                    "prompt_version": PROMPT_VERSION,
                    "raw_response": json.dumps(response),
                },
            )
            await session.commit()

        _log.info(
            "assessment.complete",
            topic_id=topic_id,
            verdict=verdict,
            model=model_used,
        )

        return {
            "topic_id": topic_id,
            "relevance_verdict": verdict,
            "category": category,
            "relevance_reason": reason,
            "model_used": model_used,
            "prompt_version": PROMPT_VERSION,
        }

    async def assess_batch(self, topic_ids: list[str]) -> list[dict[str, Any]]:
        """Assess multiple topics sequentially (no parallel LLM calls in v1).

        Individual topic failures (timeouts, LLM errors) are logged and skipped
        so the batch returns partial results rather than failing entirely.
        """
        results = []
        for tid in topic_ids:
            try:
                result = await self.assess_topic(tid)
                if result:
                    results.append(result)
            except Exception as exc:
                _log.error("assessment.topic_failed", topic_id=tid, error=str(exc))
                results.append({
                    "topic_id": tid,
                    "relevance_verdict": "error",
                    "category": "neutral",
                    "relevance_reason": f"Assessment failed: {exc}",
                    "model_used": self._model_id or "unknown",
                    "prompt_version": PROMPT_VERSION,
                })
        return results
