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
from crawler.adapters.sources.reddit import RedditJsonSource
from crawler.adapters.sources.rss import RssSource
from crawler.ports import SourcePort, TopicRepositoryPort

# (source_name, subreddit_slug) — the four Reddit subs we ingest in v1.
# r/BuyItForLife is the operator-picked retail-adjacent sub.
_REDDIT_SOURCES: list[tuple[str, str]] = [
    ("reddit_all", "all"),
    ("reddit_business", "business"),
    ("reddit_retail", "retail"),
    ("reddit_bifl", "BuyItForLife"),
]

# (source_name, feed_url) — RSS / Atom feeds.
_RSS_SOURCES: list[tuple[str, str]] = [
    (
        "nyt_homepage",
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    ),
    (
        "google_news",
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    ),
]


def build_sources() -> list[SourcePort]:
    """Return the list of sources the crawler will fan out across.

    Phase 1: HackerNews only.
    Phase 2 (Wave 1): adds 4 Reddit subreddits.
    Phase 2 (Wave 2): adds 2 RSS sources (NYT homepage, Google News).
    Total after Wave 2: 7 sources.
    """
    sources: list[SourcePort] = [HackerNewsSource()]
    sources.extend(
        RedditJsonSource(name=name, subreddit=sub) for name, sub in _REDDIT_SOURCES
    )
    sources.extend(
        RssSource(name=name, feed_url=url) for name, url in _RSS_SOURCES
    )
    return sources


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
