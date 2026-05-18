"""Composition root — wires adapters to the assessment pipeline."""

from __future__ import annotations

from core import get_engine, get_sessionmaker, get_settings
from assessor.adapters.anthropic_adapter import AnthropicAdapter
from assessor.adapters.ollama_adapter import OllamaAdapter
from assessor.adapters.postgres_rag import PostgresRAGAdapter
from assessor.domain.pipeline import AssessmentPipeline


def build_pipeline() -> tuple[AssessmentPipeline, "AsyncEngine"]:
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
        model_id=settings.llm_model,
    )

    return pipeline, engine
