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
from crawler.ports.source_port import SourcePort
from crawler.ports.topic_repository_port import TopicRepositoryPort

_log = structlog.get_logger(__name__)


async def run_once(
    sources: list[SourcePort], repo: TopicRepositoryPort, top_n: int
) -> dict[str, Any]:
    """Run a single crawl across all sources. Returns a stats dict."""

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
            stats["sources"][source.name] = src_stats
            continue

        src_stats["fetched"] = len(items)
        stats["totals"]["fetched"] += len(items)

        for item in items:
            key = dedup_key(item.title)
            candidates = await repo.find_candidates(key, limit=50)

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
    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    stats["duration_ms"] = duration_ms

    _log.info(
        "crawl.complete",
        duration_ms=duration_ms,
        fetched=stats["totals"]["fetched"],
        inserted=stats["totals"]["inserted"],
        updated=stats["totals"]["updated"],
        skipped_duplicates_within_run=stats["totals"]["skipped_within_run"],
        errors=stats["totals"]["errors"],
        sources=stats["sources"],
    )

    return stats


__all__ = ["run_once"]
