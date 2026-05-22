"""Assessment API route — trigger AI assessment from the UI.

POST /api/assess         — start background batch assessment job
POST /api/assess/{id}    — assess a single topic by ID (synchronous)
GET  /api/assess/jobs    — list recent jobs
GET  /api/assess/jobs/{id} — get job status/progress
GET  /api/business-cases — list all business cases
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, text, update

from core import get_engine, get_sessionmaker, get_settings
from core.models import AIConfig, AssessmentJob
from assessor.adapters.anthropic_adapter import AnthropicAdapter
from assessor.adapters.ollama_adapter import OllamaAdapter
from assessor.adapters.openai_adapter import OpenAIAdapter
from assessor.adapters.postgres_rag import PostgresRAGAdapter
from assessor.domain.pipeline import AssessmentPipeline

router = APIRouter()


async def _build_pipeline(session_factory):
    """Build pipeline using AI config from DB."""
    async with session_factory() as session:
        result = await session.execute(select(AIConfig).where(AIConfig.key == "default"))
        ai_config = result.scalar_one_or_none()

    if ai_config:
        base_url = ai_config.base_url
        model = ai_config.model
        api_token = ai_config.api_token
        thinking_effort = ai_config.thinking_effort or "off"
        business_context = ai_config.business_context
        opportunity_criteria = ai_config.opportunity_criteria
        risk_criteria = ai_config.risk_criteria
    else:
        settings = get_settings()
        base_url = settings.llm_base_url
        model = settings.llm_model
        api_token = settings.llm_api_key
        thinking_effort = "off"
        business_context = None
        opportunity_criteria = None
        risk_criteria = None

    # Determine provider from base_url
    if "anthropic" in (base_url or ""):
        llm = AnthropicAdapter(api_key=api_token or "", default_model=model)
    elif "openai" in (base_url or "") or (api_token and "anthropic" not in (base_url or "")):
        llm = OpenAIAdapter(base_url=base_url, api_key=api_token or "no-key", default_model=model)
    else:
        llm = OllamaAdapter(base_url=base_url, default_model=model, thinking_effort=thinking_effort)

    rag = PostgresRAGAdapter(session_factory)
    pipeline = AssessmentPipeline(
        llm=llm, rag=rag, session_factory=session_factory,
        model_id=model, business_context=business_context,
        opportunity_criteria=opportunity_criteria,
        risk_criteria=risk_criteria,
    )
    return pipeline


async def _run_job(job_id: str):
    """Background coroutine that processes assessment job."""
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

        pipeline = await _build_pipeline(session_factory)

        # Get unassessed topics
        async with session_factory() as session:
            result = await session.execute(
                select(AssessmentJob).where(AssessmentJob.id == job_id)
            )
            job = result.scalar_one()
            total = job.total_topics

        topic_ids = await pipeline._rag.get_unassessed_topic_ids(limit=total)

        # Update total in case fewer unassessed exist
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

        # Process topics one by one, updating progress
        results = []
        completed = 0
        failed = 0

        for tid in topic_ids:
            try:
                result = await pipeline.assess_topic(tid)
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

            # Update progress after each topic
            async with session_factory() as session:
                await session.execute(
                    update(AssessmentJob)
                    .where(AssessmentJob.id == job_id)
                    .values(completed_topics=completed, failed_topics=failed)
                )
                await session.commit()

        # Mark completed
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
        # Mark failed
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


@router.post("/assess")
async def assess_batch(limit: int = 20):
    """Start a background assessment job for unassessed topics."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        # Create job record
        async with session_factory() as session:
            result = await session.execute(
                text("""
                    INSERT INTO assessment_jobs (total_topics, state)
                    VALUES (:total, 'pending')
                    RETURNING id
                """),
                {"total": limit},
            )
            job_id = result.scalar_one()
            await session.commit()

        # Fire and forget the background task
        asyncio.create_task(_run_job(job_id))

        return {"job_id": job_id, "state": "pending", "total_topics": limit}
    finally:
        await engine.dispose()


@router.get("/assess/jobs")
async def list_jobs(limit: int = 10):
    """List recent assessment jobs."""
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
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
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


@router.get("/assess/jobs/{job_id}")
async def get_job(job_id: str):
    """Get status/progress of a specific job."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(AssessmentJob).where(AssessmentJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
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


@router.post("/assess/{topic_id}")
async def assess_single(topic_id: str):
    """Assess a single topic for retail relevance (synchronous)."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        pipeline = await _build_pipeline(session_factory)
        result = await pipeline.assess_topic(topic_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {type(e).__name__}: {e}")
    finally:
        await engine.dispose()


@router.get("/business-cases")
async def list_business_cases(limit: int = 50, offset: int = 0, category: str | None = None):
    """List all business cases with topic titles. Optionally filter by category."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        async with session_factory() as session:
            where_clause = ""
            params: dict = {"limit": limit, "offset": offset}
            if category:
                where_clause = "WHERE bc.raw_response->'parsed'->>'category' = :category"
                params["category"] = category
            result = await session.execute(
                text(f"""
                    SELECT bc.id, bc.topic_id, t.title, bc.relevance_verdict,
                           bc.relevance_reason, bc.model_used, bc.prompt_version,
                           bc.generated_at
                    FROM business_cases bc
                    JOIN topics t ON t.id = bc.topic_id
                    {where_clause}
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
                }
                for r in rows
            ]
    finally:
        await engine.dispose()
