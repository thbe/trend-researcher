"""Assessment API routes — per-department AI assessment surface (Phase 10).

POST /api/assess              — start background batch assessment job (analyst+)
POST /api/assess/{topic_id}   — assess one topic synchronously (analyst+)
GET  /api/assess/jobs         — list recent jobs for active dept (viewer+)
GET  /api/assess/jobs/{id}    — get job status/progress for active dept (viewer+)
GET  /api/business-cases      — list BCs owned by active dept (viewer+)

All writes set ``department_id = active_dept.id``; all reads filter by it.
The background ``_run_job`` worker has no request context, so it carries the
dept id explicitly as an argument and reads its own AIConfig keyed on that id.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text, update

from api.dependencies import (
    ActiveDepartment,
    get_active_department,
    require_role,
)
from api.schemas import AssessBatchRequest, AssessSingleRequest
from assessor.adapters.anthropic_adapter import AnthropicAdapter
from assessor.adapters.ollama_adapter import OllamaAdapter
from assessor.adapters.openai_adapter import OpenAIAdapter
from assessor.adapters.postgres_rag import PostgresRAGAdapter
from assessor.domain.pipeline import AssessmentPipeline
from core import get_engine, get_sessionmaker, get_settings
from core.models import AIConfig, AssessmentJob

router = APIRouter()


async def _build_pipeline(session_factory, department_id: str):
    """Build pipeline using AI config for the given department.

    Falls back to env-derived defaults (``llm_base_url``/``llm_model``/...) if
    the dept has not initialised its ``ai_config`` row yet — keeps the
    background worker robust if the operator triggers a job before saving
    config in the UI.
    """
    async with session_factory() as session:
        result = await session.execute(
            select(AIConfig).where(AIConfig.department_id == department_id)
        )
        ai_config = result.scalar_one_or_none()

    if ai_config:
        base_url = ai_config.base_url
        model = ai_config.model
        api_token = ai_config.api_token
        thinking_effort = ai_config.thinking_effort or "off"
        business_context = ai_config.business_context
        opportunity_criteria = ai_config.opportunity_criteria
        risk_criteria = ai_config.risk_criteria
        request_timeout_seconds = ai_config.request_timeout_seconds or 120
    else:
        settings = get_settings()
        base_url = settings.llm_base_url
        model = settings.llm_model
        api_token = settings.llm_api_key
        thinking_effort = "off"
        business_context = None
        opportunity_criteria = None
        risk_criteria = None
        request_timeout_seconds = 120

    # Provider detection order:
    #   1. Anthropic — hosted only, identified by domain.
    #   2. OpenAI-compatible — any endpoint exposing `/v1`. Covers oMLX, LM
    #      Studio, vLLM, llama.cpp server, and hosted OpenAI itself.
    #   3. Ollama — default fallback (uses /api/chat, not /v1).
    base_url_lc = (base_url or "").lower()
    if "anthropic" in base_url_lc:
        llm = AnthropicAdapter(api_key=api_token or "", default_model=model)
    elif "/v1" in base_url_lc or "openai" in base_url_lc:
        llm = OpenAIAdapter(base_url=base_url, api_key=api_token or "no-key", default_model=model)
    else:
        llm = OllamaAdapter(
            base_url=base_url,
            default_model=model,
            thinking_effort=thinking_effort,
            request_timeout_seconds=float(request_timeout_seconds),
        )

    rag = PostgresRAGAdapter(session_factory)
    pipeline = AssessmentPipeline(
        llm=llm,
        rag=rag,
        session_factory=session_factory,
        department_id=department_id,
        model_id=model,
        business_context=business_context,
        opportunity_criteria=opportunity_criteria,
        risk_criteria=risk_criteria,
    )
    return pipeline


async def _run_job(job_id: str, department_id: str, framework_id: str):
    """Background coroutine that processes an assessment job for one dept."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)

    try:
        # Mark running
        async with session_factory() as session:
            await session.execute(
                update(AssessmentJob)
                .where(AssessmentJob.id == job_id)
                .values(state="running", started_at=datetime.now(timezone.utc))
            )
            await session.commit()

        pipeline = await _build_pipeline(session_factory, department_id)

        # Get target row to read total
        async with session_factory() as session:
            result = await session.execute(
                select(AssessmentJob).where(AssessmentJob.id == job_id)
            )
            job = result.scalar_one()
            total = job.total_topics

        topic_ids = await pipeline._rag.get_unassessed_topic_ids(
            limit=total, department_id=department_id
        )

        # Update total in case fewer unassessed exist for this dept
        actual_total = len(topic_ids)
        async with session_factory() as session:
            await session.execute(
                update(AssessmentJob)
                .where(AssessmentJob.id == job_id)
                .values(total_topics=actual_total)
            )
            await session.commit()

        if not topic_ids:
            async with session_factory() as session:
                await session.execute(
                    update(AssessmentJob)
                    .where(AssessmentJob.id == job_id)
                    .values(
                        state="completed",
                        finished_at=datetime.now(timezone.utc),
                        results={"assessed": 0, "relevant": 0, "details": []},
                    )
                )
                await session.commit()
            return

        results: list[dict] = []
        completed = 0
        failed = 0

        for tid in topic_ids:
            try:
                result = await pipeline.assess_topic(
                    tid, framework_id=framework_id
                )
                if result:
                    results.append(result)
                completed += 1
            except Exception as exc:
                failed += 1
                completed += 1
                results.append({
                    "topic_id": tid,
                    "relevance_verdict": "error",
                    "category": "neutral",
                    "relevance_reason": f"Assessment failed: {exc}",
                    "model_used": pipeline._model_id or "unknown",
                    "prompt_version": "v1",
                })

            async with session_factory() as session:
                await session.execute(
                    update(AssessmentJob)
                    .where(AssessmentJob.id == job_id)
                    .values(completed_topics=completed, failed_topics=failed)
                )
                await session.commit()

        relevant = sum(1 for r in results if r.get("relevance_verdict") == "relevant")
        async with session_factory() as session:
            await session.execute(
                update(AssessmentJob)
                .where(AssessmentJob.id == job_id)
                .values(
                    state="completed",
                    finished_at=datetime.now(timezone.utc),
                    results={"assessed": len(results), "relevant": relevant, "details": results},
                )
            )
            await session.commit()

    except Exception as exc:
        async with session_factory() as session:
            await session.execute(
                update(AssessmentJob)
                .where(AssessmentJob.id == job_id)
                .values(
                    state="failed",
                    finished_at=datetime.now(timezone.utc),
                    error=str(exc),
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _resolve_dept_framework(
    session_factory, dept_id: str, requested_id: str | None
) -> tuple[str, str]:
    """Resolve which framework an assessment request should run against.

    Returns ``(framework_id, framework_key)``.

    - ``requested_id is None`` ⇒ pick the dept's default framework (the
      single ``department_frameworks`` row with ``is_default = true``).
      Errors with 422 if the dept has no default (data anomaly: migration
      0019 + the auto-enable in ``POST /departments`` guarantee one).
    - ``requested_id`` supplied ⇒ verify it is in the dept's enabled set;
      else 422. Never silently fall back to default — operators sending
      an explicit framework_id deserve an explicit error.
    """
    async with session_factory() as session:
        if requested_id is None:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT af.id, af.key
                        FROM department_frameworks df
                        JOIN assessment_frameworks af ON af.id = df.framework_id
                        WHERE df.department_id = :dept_id AND df.is_default = true
                        LIMIT 1
                        """
                    ),
                    {"dept_id": dept_id},
                )
            ).first()
            if row is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Department has no default framework configured. "
                        "Set one via PUT /api/frameworks/mine."
                    ),
                )
            return str(row[0]), str(row[1])

        row = (
            await session.execute(
                text(
                    """
                    SELECT af.id, af.key
                    FROM department_frameworks df
                    JOIN assessment_frameworks af ON af.id = df.framework_id
                    WHERE df.department_id = :dept_id AND af.id = :fw_id
                    LIMIT 1
                    """
                ),
                {"dept_id": dept_id, "fw_id": str(requested_id)},
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Requested framework is not enabled for this department"
                ),
            )
        return str(row[0]), str(row[1])


@router.post(
    "/assess",
    dependencies=[Depends(require_role("analyst", "dept_lead"))],
)
async def assess_batch(
    body: AssessBatchRequest | None = None,
    ad: ActiveDepartment = Depends(get_active_department),
):
    """Start a background assessment job for unassessed topics in the active dept."""
    body = body or AssessBatchRequest()
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    dept_id = str(ad.department.id)
    try:
        framework_id, _framework_key = await _resolve_dept_framework(
            session_factory,
            dept_id,
            str(body.framework_id) if body.framework_id else None,
        )

        async with session_factory() as session:
            result = await session.execute(
                text("""
                    INSERT INTO assessment_jobs (department_id, framework_id, total_topics, state)
                    VALUES (:dept_id, :fw_id, :total, 'pending')
                    RETURNING id
                """),
                {
                    "dept_id": dept_id,
                    "fw_id": framework_id,
                    "total": body.limit,
                },
            )
            job_id = result.scalar_one()
            await session.commit()

        # Fire and forget the background task — carries dept_id + framework_id
        # explicitly since the worker has no request context.
        asyncio.create_task(_run_job(str(job_id), dept_id, framework_id))

        return {
            "job_id": job_id,
            "state": "pending",
            "total_topics": body.limit,
            "department_id": dept_id,
            "framework_id": framework_id,
        }
    finally:
        await engine.dispose()


@router.get(
    "/assess/jobs",
    dependencies=[Depends(require_role("viewer", "analyst", "dept_lead"))],
)
async def list_jobs(
    limit: int = 10,
    ad: ActiveDepartment = Depends(get_active_department),
):
    """List recent assessment jobs owned by the active department."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        async with session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT id, state, total_topics, completed_topics, failed_topics,
                           error, created_at, started_at, finished_at
                    FROM assessment_jobs
                    WHERE department_id = :dept_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit, "dept_id": str(ad.department.id)},
            )
            rows = result.all()
            return [
                {
                    "id": r[0],
                    "state": r[1],
                    "total_topics": r[2],
                    "completed_topics": r[3],
                    "failed_topics": r[4],
                    "error": r[5],
                    "created_at": str(r[6]) if r[6] else None,
                    "started_at": str(r[7]) if r[7] else None,
                    "finished_at": str(r[8]) if r[8] else None,
                }
                for r in rows
            ]
    finally:
        await engine.dispose()


@router.get(
    "/assess/jobs/{job_id}",
    dependencies=[Depends(require_role("viewer", "analyst", "dept_lead"))],
)
async def get_job(
    job_id: str,
    ad: ActiveDepartment = Depends(get_active_department),
):
    """Get status/progress of a specific job (must belong to the active dept)."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(AssessmentJob).where(AssessmentJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job or str(job.department_id) != str(ad.department.id):
                # 404 — never reveal cross-dept job existence.
                raise HTTPException(status_code=404, detail="Job not found")
            return {
                "id": job.id,
                "state": job.state,
                "total_topics": job.total_topics,
                "completed_topics": job.completed_topics,
                "failed_topics": job.failed_topics,
                "results": job.results,
                "error": job.error,
                "created_at": str(job.created_at) if job.created_at else None,
                "started_at": str(job.started_at) if job.started_at else None,
                "finished_at": str(job.finished_at) if job.finished_at else None,
            }
    finally:
        await engine.dispose()


@router.post(
    "/assess/{topic_id}",
    dependencies=[Depends(require_role("analyst", "dept_lead"))],
)
async def assess_single(
    topic_id: str,
    body: AssessSingleRequest | None = None,
    ad: ActiveDepartment = Depends(get_active_department),
):
    """Assess a single topic synchronously for the active dept."""
    body = body or AssessSingleRequest()
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    dept_id = str(ad.department.id)
    try:
        framework_id, _framework_key = await _resolve_dept_framework(
            session_factory,
            dept_id,
            str(body.framework_id) if body.framework_id else None,
        )
        pipeline = await _build_pipeline(session_factory, dept_id)
        result = await pipeline.assess_topic(topic_id, framework_id=framework_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {type(e).__name__}: {e}")
    finally:
        await engine.dispose()


@router.get(
    "/business-cases",
    dependencies=[Depends(require_role("viewer", "analyst", "dept_lead"))],
)
async def list_business_cases(
    limit: int = 50,
    offset: int = 0,
    category: str | None = None,
    ad: ActiveDepartment = Depends(get_active_department),
):
    """List business cases owned by the active department.

    Phase 10 (MT-006): rows are filtered to ``department_id = active_dept``;
    a dept never sees another dept's assessments. Optional ``category``
    filter (opportunity/risk/neutral) still works against
    ``raw_response->'parsed'->>'category'``.
    """
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        async with session_factory() as session:
            params: dict = {
                "limit": limit,
                "offset": offset,
                "dept_id": str(ad.department.id),
            }
            extra_where = ""
            if category:
                extra_where = "AND bc.raw_response->'parsed'->>'category' = :category"
                params["category"] = category
            result = await session.execute(
                text(f"""
                    SELECT bc.id, bc.topic_id, t.title, bc.relevance_verdict,
                           bc.relevance_reason, bc.model_used, bc.prompt_version,
                           bc.generated_at, bc.structured_output,
                           af.id, af.key, af.display_component
                    FROM business_cases bc
                    JOIN topics t ON t.id = bc.topic_id
                    JOIN assessment_frameworks af ON af.id = bc.framework_id
                    WHERE bc.department_id = :dept_id
                    {extra_where}
                    ORDER BY bc.generated_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.all()
            return [
                {
                    "id": r[0],
                    "topic_id": r[1],
                    "title": r[2],
                    "relevance_verdict": r[3],
                    "relevance_reason": r[4],
                    "model_used": r[5],
                    "prompt_version": r[6],
                    "generated_at": str(r[7]),
                    "structured_output": r[8],
                    "framework": {
                        "id": str(r[9]),
                        "key": r[10],
                        "display_component": r[11],
                    },
                }
                for r in rows
            ]
    finally:
        await engine.dispose()
