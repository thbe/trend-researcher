"""Internal endpoint to trigger a crawl run (Cloud Scheduler -> Cloud Run).

POST /api/internal/crawl
  - Protected by require_pat (bearer PAT).
  - Returns 202 immediately; the actual crawl runs in a FastAPI
    BackgroundTask so Cloud Scheduler doesn't have to wait minutes.

Engine isolation: the background task builds its own engine via
``crawler.app.composition.build_repository`` and disposes it in a ``finally``
block. We deliberately do NOT reuse the API's request-scoped engine —
``run_once`` is long-running and would hold an API DB session open for the
entire crawl. Mirrors ``services/crawler/src/crawler/app/cli.py:_main``.
"""
from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, status

from api.middleware.pat_auth import require_pat

router = APIRouter(tags=["internal"])

_log = structlog.get_logger(__name__)


async def _run_crawl_isolated() -> None:
    """Run one crawl with an engine local to this background task."""

    # Imported lazily so importing the route module never pulls the entire
    # crawler dep graph during pytest collection.
    from crawler.app.composition import build_repository, build_sources
    from crawler.app.orchestrator import run_once

    top_n = int(os.getenv("CRAWLER_TOP_N", "100"))
    engine = None
    try:
        sources = build_sources()
        topic_repo, crawl_run_repo, engine = build_repository()
        stats = await run_once(sources, topic_repo, crawl_run_repo, top_n)
        _log.info(
            "internal.crawl.complete",
            crawl_run_id=stats.get("crawl_run_id"),
            totals=stats.get("totals"),
        )
    except Exception as exc:  # noqa: BLE001 — log + swallow; we're a bg task
        _log.exception("internal.crawl.failed", error=str(exc))
    finally:
        if engine is not None:
            await engine.dispose()


@router.post(
    "/internal/crawl",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_pat)],
)
async def trigger_crawl(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Queue a crawl run and return 202 immediately."""

    background_tasks.add_task(_run_crawl_isolated)
    return {"status": "queued"}


__all__ = ["router", "_run_crawl_isolated"]
