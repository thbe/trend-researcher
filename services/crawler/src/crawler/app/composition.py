"""Composition root for the crawler service.

This is the *only* module that knows how to wire concrete adapters to the
ports defined in :mod:`crawler.ports`. Everything else (orchestrator, CLI)
depends on the abstract ports — keeping wiring centralized here is what
lets us swap adapters (e.g., a different source list) without touching
business logic.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from core import get_engine, get_sessionmaker, get_settings

from crawler.adapters.persistence.sqlalchemy_topic_repository import (
    SqlAlchemyTopicRepository,
)
from crawler.adapters.sources.hackernews import HackerNewsSource
from crawler.ports import SourcePort, TopicRepositoryPort


def build_sources() -> list[SourcePort]:
    """Return the list of sources the crawler will fan out across.

    Phase 1: HackerNews only. Phase 2 adds Reddit + RSS sources.
    """
    return [HackerNewsSource()]


def build_repository() -> tuple[TopicRepositoryPort, AsyncEngine]:
    """Build the topic repository plus its underlying engine.

    The engine is returned alongside the repository so the caller (typically
    the CLI) can dispose of it cleanly after the crawl finishes.
    """
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    repo = SqlAlchemyTopicRepository(session_factory)
    return repo, engine


__all__ = ["build_sources", "build_repository"]
