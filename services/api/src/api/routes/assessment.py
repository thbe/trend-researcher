"""Assessment API route — trigger AI assessment from the UI.

POST /api/assess         — assess unassessed topics (batch)
POST /api/assess/{id}    — assess a single topic by ID
GET  /api/business-cases — list all business cases
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, text

from core import get_engine, get_sessionmaker, get_settings
from assessor.adapters.anthropic_adapter import AnthropicAdapter
from assessor.adapters.ollama_adapter import OllamaAdapter
from assessor.adapters.postgres_rag import PostgresRAGAdapter
from assessor.domain.pipeline import AssessmentPipeline

router = APIRouter()


def _build_pipeline_from_request():
    """Build pipeline using the API's own DB session factory."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)

    if settings.llm_provider == "ollama":
        llm = OllamaAdapter(base_url=settings.llm_base_url, default_model=settings.llm_model)
    else:
        llm = AnthropicAdapter(api_key=settings.llm_api_key, default_model=settings.llm_model)

    rag = PostgresRAGAdapter(session_factory)
    pipeline = AssessmentPipeline(llm=llm, rag=rag, session_factory=session_factory, model_id=settings.llm_model)
    return pipeline, engine


@router.post("/assess/{topic_id}")
async def assess_single(topic_id: str):
    """Assess a single topic for retail relevance."""
    pipeline, engine = _build_pipeline_from_request()
    try:
        result = await pipeline.assess_topic(topic_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        return result
    finally:
        await engine.dispose()


@router.post("/assess")
async def assess_batch(limit: int = 20):
    """Assess unassessed topics (up to limit)."""
    pipeline, engine = _build_pipeline_from_request()
    try:
        topic_ids = await pipeline._rag.get_unassessed_topic_ids(limit=limit)
        if not topic_ids:
            return {"assessed": 0, "results": []}
        results = await pipeline.assess_batch(topic_ids)
        relevant = sum(1 for r in results if r["relevance_verdict"] == "relevant")
        return {"assessed": len(results), "relevant": relevant, "results": results}
    finally:
        await engine.dispose()


@router.get("/business-cases")
async def list_business_cases(limit: int = 50, offset: int = 0):
    """List all business cases with topic titles."""
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        async with session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT bc.id, bc.topic_id, t.title, bc.relevance_verdict,
                           bc.relevance_reason, bc.model_used, bc.prompt_version,
                           bc.generated_at
                    FROM business_cases bc
                    JOIN topics t ON t.id = bc.topic_id
                    ORDER BY bc.generated_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"limit": limit, "offset": offset},
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
