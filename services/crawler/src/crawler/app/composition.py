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

from core import CrawlConfig, DepartmentSource, get_engine, get_sessionmaker, get_settings

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
    """Build sources from `crawl_config` ∩ `department_sources` (Plan 10-02).

    The set of source NAMES that get crawled is the **union of all
    department subscriptions** (any dept with ``enabled=true`` for a
    source name causes that source to be included). The per-source
    technical settings (``top_n``, ``capture_summary``, ``verify_ssl``,
    ``feed_url``) still come from ``crawl_config`` — that table is the
    single source of truth for *how* to fetch each source; the
    ``department_sources`` table answers *whether* to fetch it.

    Effective resolution:

    1. Read every ``crawl_config`` row (technical config).
    2. Read distinct ``source_name`` from ``department_sources`` where
       ``enabled = true`` (union over all depts).
    3. Build sources for the intersection. Emit INFO log
       ``crawl_sources.selected_via_department_sources_union``.

    Defensive fallback:

    - If **step 2 yields the empty set** (no department has subscribed
      to any source — possible if every dept_lead toggled everything
      off, or in a fresh post-migration DB where Default has nothing
      enabled), log WARNING
      ``crawl_sources.no_department_subscriptions_falling_back`` and
      build sources for **every** ``crawl_config`` row instead of
      bricking the cron.
    - If the whole DB read errors (fresh install, pre-migration), fall
      back to :func:`build_sources` (hardcoded list) as before.
    - If ``crawl_config`` itself is empty, fall back to :func:`build_sources`.

    Carries ARC-001: this function never reads any per-department config
    beyond the boolean ``enabled`` flag — no prompts, no criteria, no AI.
    """
    try:
        async with session_factory() as session:
            cfg_rows = (
                await session.execute(select(CrawlConfig))
            ).scalars().all()
            sub_names = set(
                (
                    await session.execute(
                        select(DepartmentSource.source_name)
                        .where(DepartmentSource.enabled.is_(True))
                        .distinct()
                    )
                ).scalars().all()
            )
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "crawl_config.read_failed_fallback_hardcoded",
            error=str(exc),
        )
        return build_sources()

    if not cfg_rows:
        _log.info("crawl_config.empty_fallback_hardcoded")
        return build_sources()

    fallback_used = False
    if not sub_names:
        # No department has subscribed to anything — don't brick the
        # cron. Crawl every known source so operators still get data
        # while they fix the subscription state.
        fallback_used = True
        sub_names = {cfg.source_name for cfg in cfg_rows}
        _log.warning(
            "crawl_sources.no_department_subscriptions_falling_back",
            fallback_count=len(sub_names),
            fallback_names=sorted(sub_names),
        )

    sources: list[SourcePort] = []
    for cfg in cfg_rows:
        if cfg.source_name not in sub_names:
            continue
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

    if not fallback_used:
        _log.info(
            "crawl_sources.selected_via_department_sources_union",
            count=len(sources),
            names=[s.name for s in sources],
        )
    else:
        _log.info(
            "crawl_sources.built_from_fallback",
            count=len(sources),
            names=[s.name for s in sources],
        )
    return sources


__all__ = ["build_sources", "build_sources_from_db", "build_repository"]
