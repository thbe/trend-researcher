"""Internal endpoint to trigger a crawl run (Cloud Scheduler -> Cloud Run).

POST /api/internal/crawl
  - Protected by require_pat (bearer PAT).
  - Runs the crawl SYNCHRONOUSLY and returns 200 with stats.

Why sync (not BackgroundTasks):
  Cloud Run scales to zero. After the response is sent, CPU is throttled
  to near-zero unless --no-cpu-throttling is set (which breaks scale-to-0
  pricing). A FastAPI BackgroundTask gets starved and never completes.
  The crawl is bounded (~30s typical, far under the 600s Cloud Run
  timeout), so running it inline is the standard Cloud Run pattern.

Engine isolation: builds its own engine via
``crawler.app.composition.build_repository`` and disposes it in a ``finally``
block. We deliberately do NOT reuse the API's request-scoped engine —
``run_once`` is long-running and would hold an API DB session open for the
entire crawl. Mirrors ``services/crawler/src/crawler/app/cli.py:_main``.
"""
from __future__ import annotations

import os
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from api.middleware.pat_auth import require_pat

router = APIRouter(tags=["internal"])

_log = structlog.get_logger(__name__)


async def _run_crawl_isolated() -> dict[str, Any]:
    """Run one crawl with an engine local to this request. Returns stats."""

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
        return stats
    finally:
        if engine is not None:
            await engine.dispose()


@router.post(
    "/internal/crawl",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_pat)],
)
async def trigger_crawl() -> dict[str, Any]:
    """Run a crawl synchronously and return the stats."""

    try:
        stats = await _run_crawl_isolated()
    except Exception as exc:  # noqa: BLE001
        _log.exception("internal.crawl.failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"crawl failed: {exc}",
        ) from exc
    return {"status": "ok", **stats}


__all__ = ["router", "_run_crawl_isolated"]
