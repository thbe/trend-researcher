"""Assessment pipeline — framework-aware RAG → LLM → persist orchestrator.

Phase 10 (plan 10-03 T06): the pipeline no longer hard-codes the verdict
prompt. Each ``assess_topic`` call dispatches on a framework (resolved by
``key`` or ``framework_id``) which owns prompt assembly + output parsing.
The pipeline owns I/O only: RAG fetch, LLM call (with ONE retry on
schema-validation failure), and the ``business_cases`` write — including the
new ``framework_id`` + ``structured_output`` columns from migration 0019.

Backwards-compat constructor: ``model_id`` / ``business_context`` /
``opportunity_criteria`` / ``risk_criteria`` continue to work; only the
default framework (verdict) is bound when no per-call ``framework_key`` /
``framework_id`` is given, so existing callers in the API keep working.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assessor.domain.frameworks import registry as framework_registry
from assessor.domain.frameworks.base import AIConfig, Framework, validate_structured_output
from assessor.domain.frameworks.verdict import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_OPPORTUNITY_CRITERIA,
    DEFAULT_RISK_CRITERIA,
)
from assessor.ports.llm import LLMPort
from assessor.ports.rag import RAGPort

_log = structlog.get_logger(__name__)


class AssessmentPipeline:
    """Single-shot RAG → LLM assessment pipeline (no agentic loop).

    Reads topic context from Postgres via ``RAGPort``, dispatches to a
    ``Framework`` for prompt assembly + output parsing, calls the LLM via
    ``LLMPort``, validates the parsed payload against the framework's
    ``JSON_SCHEMA`` (with ONE retry on validation failure), and persists the
    result to ``business_cases``.
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
        default_framework_key: str = "verdict",
    ) -> None:
        """Create a pipeline bound to one department.

        Phase 10 (MT-006): ``department_id`` is REQUIRED — every
        ``business_cases`` row carries it (NOT NULL since migration 0017) so
        the same topic can be re-assessed independently per dept with
        different prompts / criteria / framework.

        ``default_framework_key`` selects which framework is used when
        ``assess_topic`` / ``assess_batch`` are called without an explicit
        ``framework_key`` or ``framework_id``. Defaults to ``"verdict"`` to
        preserve pre-Phase-10 behaviour for existing API call sites.
        """
        self._llm = llm
        self._rag = rag
        self._session_factory = session_factory
        self._department_id = department_id
        self._model_id = model_id
        self._ai_config = AIConfig(
            business_context=business_context or DEFAULT_BUSINESS_CONTEXT,
            opportunity_criteria=opportunity_criteria or DEFAULT_OPPORTUNITY_CRITERIA,
            risk_criteria=risk_criteria or DEFAULT_RISK_CRITERIA,
        )
        self._default_framework_key = default_framework_key

    async def _resolve_framework(
        self,
        framework_key: str | None,
        framework_id: str | None,
    ) -> tuple[Framework, str | None]:
        """Resolve a framework + its DB id from caller-supplied key/id.

        Returns ``(framework, framework_id_or_none)``. ``framework_id`` may
        be ``None`` when the caller only passed a key AND the key resolves to
        a framework whose id is not in the in-process well-known map (rare —
        all three v1 frameworks export their hardcoded UUID).
        """
        if framework_id is not None:
            async with self._session_factory() as session:
                fw = await framework_registry.get_by_id(framework_id, session)
            return fw, framework_id

        key = framework_key or self._default_framework_key
        fw = framework_registry.get_by_key(key)
        # Try to recover the well-known id from the inverse map so persist
        # always has a framework_id to write (business_cases.framework_id is
        # NOT NULL since migration 0019).
        resolved_id: str | None = None
        for cid, cfw in framework_registry._BY_ID.items():
            if cfw is fw:
                resolved_id = cid
                break
        return fw, resolved_id

    async def assess_topic(
        self,
        topic_id: str,
        *,
        framework_key: str | None = None,
        framework_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Assess a single topic with the selected framework and persist the result.

        Returns the business_case dict on success, ``None`` if the topic is
        not found in RAG.
        """
        context = await self._rag.get_topic_context(topic_id)
        if context is None:
            _log.warning("assessment.topic_not_found", topic_id=topic_id)
            return None

        framework, resolved_fw_id = await self._resolve_framework(
            framework_key, framework_id
        )

        messages = framework.build_messages(context, self._ai_config)

        # ONE retry on schema-validation failure — gives a flaky LLM exactly
        # one chance to produce valid JSON before we hard-fail the row.
        structured, response, last_error = await self._call_and_parse(
            framework, messages
        )
        if structured is None:
            structured, response, last_error = await self._call_and_parse(
                framework, messages
            )

        if structured is None:
            # Both attempts failed. Fall back to the framework's parse_output
            # error shape (verdict framework returns a not-relevant stub;
            # other frameworks may raise). Persist whatever we have so the
            # operator can see the failure in the UI.
            _log.error(
                "assessment.parse_failed_after_retry",
                topic_id=topic_id,
                framework=framework.KEY,
                error=str(last_error),
                content=(response or {}).get("content", "")[:200] if response else "",
            )
            structured = framework.parse_output((response or {}).get("content", "") if response else "")

        verdict = str(structured.get("verdict", "not-relevant"))
        reason = str(structured.get("reason", "No reason provided"))
        category = structured.get("category", "neutral")
        model_used = (response or {}).get("model", self._model_id or "unknown") if response else (self._model_id or "unknown")

        async with self._session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO business_cases
                        (topic_id, department_id, framework_id, relevance_verdict,
                         relevance_reason, model_used, prompt_version,
                         raw_response, structured_output)
                    VALUES
                        (:topic_id, :department_id, :framework_id, :verdict,
                         :reason, :model_used, :prompt_version,
                         :raw_response, :structured_output)
                """),
                {
                    "topic_id": topic_id,
                    "department_id": self._department_id,
                    "framework_id": resolved_fw_id,
                    "verdict": verdict,
                    "reason": reason,
                    "model_used": model_used,
                    "prompt_version": framework.PROMPT_VERSION,
                    "raw_response": json.dumps(response) if response is not None else None,
                    "structured_output": json.dumps(structured),
                },
            )
            await session.commit()

        _log.info(
            "assessment.complete",
            topic_id=topic_id,
            framework=framework.KEY,
            verdict=verdict,
            model=model_used,
        )

        return {
            "topic_id": topic_id,
            "framework_id": resolved_fw_id,
            "framework_key": framework.KEY,
            "relevance_verdict": verdict,
            "category": category,
            "relevance_reason": reason,
            "model_used": model_used,
            "prompt_version": framework.PROMPT_VERSION,
            "structured_output": structured,
        }

    async def _call_and_parse(
        self,
        framework: Framework,
        messages: list[dict[str, str]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, Exception | None]:
        """One LLM round-trip + parse + schema-validate.

        Returns ``(structured_or_none, response_or_none, last_error_or_none)``.
        ``structured_or_none`` is ``None`` iff parse OR validation failed —
        signalling the caller to retry once.
        """
        try:
            response = await self._llm.complete(
                messages,
                model_id=self._model_id,
                response_schema=framework.JSON_SCHEMA,
            )
        except Exception as exc:  # network / provider error
            return None, None, exc

        parsed = response.get("parsed")
        if not parsed:
            try:
                parsed = framework.parse_output(response.get("content", ""))
            except Exception as exc:
                return None, response, exc

        try:
            validate_structured_output(parsed, framework.JSON_SCHEMA)
        except jsonschema.ValidationError as exc:
            return None, response, exc

        return parsed, response, None

    async def assess_batch(
        self,
        topic_ids: list[str],
        *,
        framework_key: str | None = None,
        framework_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Assess multiple topics sequentially (no parallel LLM calls in v1).

        Individual topic failures (timeouts, LLM errors) are logged and
        skipped so the batch returns partial results rather than failing
        entirely.
        """
        # Resolve framework once for prompt_version / id reporting in errors.
        framework, resolved_fw_id = await self._resolve_framework(
            framework_key, framework_id
        )
        results: list[dict[str, Any]] = []
        for tid in topic_ids:
            try:
                result = await self.assess_topic(
                    tid,
                    framework_key=framework.KEY,
                    framework_id=resolved_fw_id,
                )
                if result:
                    results.append(result)
            except Exception as exc:
                _log.error("assessment.topic_failed", topic_id=tid, error=str(exc))
                results.append({
                    "topic_id": tid,
                    "framework_id": resolved_fw_id,
                    "framework_key": framework.KEY,
                    "relevance_verdict": "error",
                    "category": "neutral",
                    "relevance_reason": f"Assessment failed: {exc}",
                    "model_used": self._model_id or "unknown",
                    "prompt_version": framework.PROMPT_VERSION,
                })
        return results
