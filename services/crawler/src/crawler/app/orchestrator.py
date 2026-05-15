"""Crawler orchestrator: a single end-to-end crawl across all configured sources.

Pulls items from each source, runs the dedup decision in the domain layer
against a recent-window candidate set, and routes each item to either
``insert_new`` or ``update_existing`` on the topic repository. Stays a one-shot
function — there is no scheduler in process.

Phase 1 invariant: ``observation_count`` is bumped at most once per crawl per
topic. If the same topic is matched by multiple sources within a single run,
only the first match performs the update; later matches are skipped and
counted under ``skipped_within_run``. Cross-source aggregation arrives in
Phase 2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import UUID

import structlog

from crawler.domain.dedup import dedup_key, is_duplicate
from crawler.ports.crawl_run_repository_port import (
    CrawlRunRecord,
    CrawlRunRepositoryPort,
)
from crawler.ports.source_port import SourcePort
from crawler.ports.topic_repository_port import TopicRepositoryPort

_log = structlog.get_logger(__name__)


async def run_once(
    sources: list[SourcePort],
    repo: TopicRepositoryPort,
    crawl_run_repo: CrawlRunRepositoryPort,
    top_n: int,
) -> dict[str, Any]:
    """Run a single crawl across all sources. Returns a stats dict.

    At the end of the run (Phase 3, OPS-002), persist a single ``crawl_runs``
    row capturing started_at/finished_at, totals, per-source stats, and any
    failed sources. The persist is the last side effect before the
    ``crawl.complete`` log; if it raises, the orchestrator re-raises (does
    NOT swallow) so ops telemetry is never silently lost. The new row's id
    is attached as ``stats['crawl_run_id']``.
    """

    started_at = datetime.now(timezone.utc)
    t0 = perf_counter()

    stats: dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "top_n": top_n,
        "totals": {
            "fetched": 0,
            "inserted": 0,
            "updated": 0,
            "skipped_within_run": 0,
            "errors": 0,
        },
        "sources": {},
        # Names of sources whose ``.fetch()`` raised this run, in the order
        # they were encountered. Counterpart to ``totals.errors`` (which is
        # just a count). Phase 2 contract: callers can inspect this list to
        # decide whether to alert / retry on next run.
        "failed_sources": [],
    }

    updated_this_run: set[UUID] = set()

    for source in sources:
        src_stats = {
            "fetched": 0,
            "inserted": 0,
            "updated": 0,
            "skipped_within_run": 0,
            "errors": 0,
        }
        try:
            items = await source.fetch(top_n)
        except Exception as exc:  # noqa: BLE001 — we want broad isolation per-source
            _log.error("source.fetch_failed", source=source.name, error=str(exc))
            src_stats["errors"] += 1
            stats["totals"]["errors"] += 1
            stats["failed_sources"].append(source.name)
            stats["sources"][source.name] = src_stats
            continue

        src_stats["fetched"] = len(items)
        stats["totals"]["fetched"] += len(items)

        for item in items:
            key = dedup_key(item.title)
            candidates = await repo.find_candidates(key, limit=5000)

            match_id: UUID | None = None
            for candidate in candidates:
                if is_duplicate(item.title, candidate.title):
                    match_id = candidate.id
                    break

            if match_id is not None:
                if match_id in updated_this_run:
                    src_stats["skipped_within_run"] += 1
                    stats["totals"]["skipped_within_run"] += 1
                    continue
                await repo.update_existing(match_id, item)
                updated_this_run.add(match_id)
                src_stats["updated"] += 1
                stats["totals"]["updated"] += 1
            else:
                topic_id = await repo.insert_new(item)
                updated_this_run.add(topic_id)
                src_stats["inserted"] += 1
                stats["totals"]["inserted"] += 1

        stats["sources"][source.name] = src_stats

    duration_ms = int((perf_counter() - t0) * 1000)
    finished_at = datetime.now(timezone.utc)
    stats["finished_at"] = finished_at.isoformat()
    stats["duration_ms"] = duration_ms

    # Persist the crawl_runs row (Phase 3, OPS-002). Built from stats so the
    # persisted row matches exactly what the orchestrator just logged. On
    # failure we log + re-raise; we do NOT swallow.
    record = CrawlRunRecord(
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        top_n=top_n,
        totals_fetched=stats["totals"]["fetched"],
        totals_inserted=stats["totals"]["inserted"],
        totals_updated=stats["totals"]["updated"],
        totals_skipped_within_run=stats["totals"]["skipped_within_run"],
        totals_errors=stats["totals"]["errors"],
        per_source=stats["sources"],
        failed_sources=stats["failed_sources"],
    )
    try:
        crawl_run_id = await crawl_run_repo.insert(record)
    except Exception as exc:  # noqa: BLE001 — log + re-raise, do not swallow
        _log.exception(
            "crawl_run.persist_failed",
            error=str(exc),
            duration_ms=duration_ms,
            totals=stats["totals"],
        )
        raise
    stats["crawl_run_id"] = str(crawl_run_id)

    _log.info(
        "crawl.complete",
        crawl_run_id=stats["crawl_run_id"],
        duration_ms=duration_ms,
        fetched=stats["totals"]["fetched"],
        inserted=stats["totals"]["inserted"],
        updated=stats["totals"]["updated"],
        skipped_duplicates_within_run=stats["totals"]["skipped_within_run"],
        errors=stats["totals"]["errors"],
        failed_sources=stats["failed_sources"],
        sources=stats["sources"],
    )

    return stats


__all__ = ["run_once"]
