"""Composition root — wires adapters to the assessment pipeline.

CLI path: targets the seeded Default department so ``uv run ... assessor
assess`` works without an HTTP request context. API code does NOT use this
factory — it builds per-request, per-dept pipelines in
``services/api/src/api/routes/assessment.py``.
"""

from __future__ import annotations

from core import get_engine, get_sessionmaker, get_settings
from assessor.adapters.anthropic_adapter import AnthropicAdapter
from assessor.adapters.ollama_adapter import OllamaAdapter
from assessor.adapters.openai_adapter import OpenAIAdapter
from assessor.adapters.postgres_rag import PostgresRAGAdapter
from assessor.domain.pipeline import AssessmentPipeline

# Mirrors packages/core/alembic/versions/0017_*.py — Default dept seeded UUID.
DEFAULT_DEPARTMENT_ID = "00000000-0000-0000-0000-000000000001"


def build_pipeline(
    *,
    department_id: str = DEFAULT_DEPARTMENT_ID,
    framework_key: str = "verdict",
) -> tuple[AssessmentPipeline, "AsyncEngine"]:
    """Build the full assessment pipeline from settings.

    Returns (pipeline, engine) — caller must dispose engine when done.
    """
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)

    # LLM adapter selection (env-driven, no code change needed)
    if settings.llm_provider == "ollama":
        llm = OllamaAdapter(
            base_url=settings.llm_base_url,
            default_model=settings.llm_model,
        )
    elif settings.llm_provider == "openai":
        llm = OpenAIAdapter(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "lm-studio",
            default_model=settings.llm_model,
        )
    else:
        # Default: anthropic
        llm = AnthropicAdapter(
            api_key=settings.llm_api_key,
            default_model=settings.llm_model,
        )

    rag = PostgresRAGAdapter(session_factory)

    pipeline = AssessmentPipeline(
        llm=llm,
        rag=rag,
        session_factory=session_factory,
        department_id=department_id,
        model_id=settings.llm_model,
        default_framework_key=framework_key,
    )

    return pipeline, engine
