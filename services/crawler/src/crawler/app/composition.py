"""Composition root for the crawler service.

This is the *only* module that knows how to wire concrete adapters to the
ports defined in :mod:`crawler.ports`. Everything else (orchestrator, CLI)
depends on the abstract ports — keeping wiring centralized here is what
lets us swap adapters (e.g., a different source list) without touching
business logic.
"""

from __future__ import annotations

import os

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import CrawlConfig, get_engine, get_sessionmaker, get_settings

from crawler.adapters.persistence.sqlalchemy_crawl_run_repository import (
    SqlAlchemyCrawlRunRepository,
)
from crawler.adapters.persistence.sqlalchemy_topic_repository import (
    SqlAlchemyTopicRepository,
)
from crawler.adapters.sources.hackernews import HackerNewsSource
from crawler.adapters.sources.rss import RssSource
from crawler.ports import CrawlRunRepositoryPort, SourcePort, TopicRepositoryPort

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

# (source_name, feed_url, capture_summary) — RSS / Atom feeds.
# capture_summary=False suppresses ``RawItem.description`` for sources whose
# ``<description>`` is structurally NOT publisher prose (e.g. Google News
# ships an ``<ol><li><a>`` related-articles HTML fragment). Plan 04.5.1.
_RSS_SOURCES: list[tuple[str, str, bool]] = [
    (
        "nyt_homepage",
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        True,
    ),
    (
        "google_news",
        "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        False,
    ),
]

_log = structlog.get_logger(__name__)


def _parse_disabled_sources(raw: str | None) -> set[str]:
    """Parse the ``CRAWLER_DISABLED_SOURCES`` env value into a set of names.

    Empty / unset / whitespace-only ⇒ empty set (no filtering). Otherwise:
    split on ``,``, strip each entry, lowercase, drop empties. Comparison
    against ``source.name`` is case-insensitive by convention here.
    """
    if not raw or not raw.strip():
        return set()
    return {entry.strip().lower() for entry in raw.split(",") if entry.strip()}


def build_sources() -> list[SourcePort]:
    """Return the list of sources the crawler will fan out across.

    Phase 1: HackerNews only.
    Phase 2 (Wave 1): added 4 Reddit subreddits — DROPPED in Plan 02-04 after
        live smoke confirmed datacenter-IP WAF block (see module docstring).
    Phase 2 (Wave 2): adds 2 RSS sources (NYT homepage, Google News).
    Effective v1 source count: 3 (HackerNews + NYT + Google News).

    Phase 3 (Plan 03-03): the env var ``CRAWLER_DISABLED_SOURCES`` (csv,
    case-insensitive, whitespace-tolerant) filters out any source whose
    ``.name`` appears in the list. Unknown names log a warning but do NOT
    raise — operator typos remain visible without breaking the run. An
    empty result (all sources disabled) returns ``[]`` and the orchestrator
    runs to completion writing a zero-totals ``crawl_runs`` row.
    """
    sources: list[SourcePort] = [HackerNewsSource()]
    sources.extend(
        RssSource(name=name, feed_url=url, capture_summary=capture)
        for name, url, capture in _RSS_SOURCES
    )

    raw = os.environ.get("CRAWLER_DISABLED_SOURCES")
    disabled = _parse_disabled_sources(raw)
    if not disabled:
        return sources

    known = {s.name.lower() for s in sources}
    unknown = disabled - known
    if unknown:
        _log.warning(
            "crawler.disabled_sources.unknown",
            unknown=sorted(unknown),
        )
    _log.info("crawler.disabled_sources.applied", disabled=sorted(disabled))
    return [s for s in sources if s.name.lower() not in disabled]


def build_repository() -> tuple[
    TopicRepositoryPort, CrawlRunRepositoryPort, AsyncEngine
]:
    """Build the persistence adapters plus the underlying engine.

    Returns the topic repository, the crawl-run repository, and the engine
    itself. The engine is returned so the caller (typically the CLI) can
    dispose of it cleanly after the crawl finishes. Both repositories share
    the same session factory and engine.
    """
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    topic_repo = SqlAlchemyTopicRepository(session_factory)
    crawl_run_repo = SqlAlchemyCrawlRunRepository(session_factory)
    return topic_repo, crawl_run_repo, engine


async def build_sources_from_db(
    session_factory,
) -> list[SourcePort]:
    """Build sources from the ``crawl_config`` table (Phase 5).

    Each returned source carries a ``configured_top_n`` attribute so the
    orchestrator can use per-source limits. Sources with ``enabled=False``
    are excluded.

    Falls back to :func:`build_sources` if the table is empty or on error
    (graceful degradation for fresh installs before migration 0007 runs).
    """
    try:
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(CrawlConfig).where(CrawlConfig.enabled.is_(True))
                )
            ).scalars().all()
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "crawl_config.read_failed_fallback_hardcoded",
            error=str(exc),
        )
        return build_sources()

    if not rows:
        _log.info("crawl_config.empty_fallback_hardcoded")
        return build_sources()

    sources: list[SourcePort] = []
    for cfg in rows:
        if cfg.source_name == "hackernews":
            src: SourcePort = HackerNewsSource(verify_ssl=cfg.verify_ssl)
        elif cfg.feed_url:
            src = RssSource(
                name=cfg.source_name,
                feed_url=cfg.feed_url,
                capture_summary=cfg.capture_summary,
                verify_ssl=cfg.verify_ssl,
            )
        else:
            _log.warning(
                "crawl_config.skip_no_feed_url",
                source_name=cfg.source_name,
            )
            continue
        # Attach per-source top_n for orchestrator consumption.
        src.configured_top_n = cfg.top_n  # type: ignore[attr-defined]
        sources.append(src)

    _log.info(
        "crawl_config.sources_built",
        count=len(sources),
        names=[s.name for s in sources],
    )
    return sources


__all__ = ["build_sources", "build_sources_from_db", "build_repository"]
