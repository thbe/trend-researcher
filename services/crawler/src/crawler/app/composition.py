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
from crawler.adapters.sources.rss import RssSource
from crawler.ports import SourcePort, TopicRepositoryPort

# Reddit JSON adapter is kept in tree (crawler.adapters.sources.reddit) but is
# NOT registered here. Plan 02-04 live smoke confirmed Reddit's Cloudflare WAF
# returns 403 to httpx (BOTH /hot.json AND /.rss endpoints) from datacenter
# IPs regardless of User-Agent — same UA over plain `curl` from the same
# Docker network gets 200, so the block is a TLS / client fingerprint, not
# the UA string itself. Re-enabling Reddit requires either:
#   (a) running the crawler from a residential IP (works locally for the
#       operator), or
#   (b) Reddit OAuth via a registered app (out of scope for v1; tracked as
#       Phase 3+ follow-up — see CONTEXT.md "Reddit access reality").
# See .planning/phases/02-multi-source-ingest/CONTEXT.md for full discussion.

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
    Phase 2 (Wave 1): added 4 Reddit subreddits — DROPPED in Plan 02-04 after
        live smoke confirmed datacenter-IP WAF block (see module docstring).
    Phase 2 (Wave 2): adds 2 RSS sources (NYT homepage, Google News).
    Effective v1 source count: 3 (HackerNews + NYT + Google News).
    """
    sources: list[SourcePort] = [HackerNewsSource()]
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
