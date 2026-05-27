"""Internal endpoint to trigger a crawl run (Cloud Scheduler -> Cloud Run).

Endpoints:

- ``POST /api/internal/crawl``
    Global crawl, protected by env-PAT (``require_pat`` →
    ``TREND_INTERNAL_PAT``). Unions sources across **all** departments.
    Used by Cloud Scheduler.

- ``POST /api/internal/departments/{dept_slug}/crawl``
    Per-department crawl, protected by a per-dept PAT (``require_dept_pat`` →
    ``department_pats``). The path slug MUST match the PAT's department,
    otherwise 403. Filters sources to that department's subscriptions only.

- ``POST /api/crawl``
    UI-triggered global crawl (session-cookie auth via middleware).

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
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.middleware.pat_auth import require_dept_pat, require_pat
from core.models import Department, DepartmentPAT

router = APIRouter(tags=["internal"])

_log = structlog.get_logger(__name__)


async def _run_crawl_isolated(
    department_id: UUID | str | None = None,
) -> dict[str, Any]:
    """Run one crawl with an engine local to this request. Returns stats.

    When ``department_id`` is given, ``build_sources_from_db`` filters
    ``department_sources`` to that single dept (no fallback expansion).
    """

    # Imported lazily so importing the route module never pulls the entire
    # crawler dep graph during pytest collection.
    from crawler.app.composition import build_repository, build_sources_from_db
    from crawler.app.orchestrator import run_once

    top_n = int(os.getenv("CRAWLER_TOP_N", "100"))
    engine = None
    try:
        topic_repo, crawl_run_repo, engine = build_repository()
        session_factory = topic_repo._session_factory  # noqa: SLF001
        dept_uuid: UUID | None
        if department_id is None:
            dept_uuid = None
        elif isinstance(department_id, UUID):
            dept_uuid = department_id
        else:
            dept_uuid = UUID(str(department_id))
        sources = await build_sources_from_db(
            session_factory, department_id=dept_uuid
        )
        stats = await run_once(sources, topic_repo, crawl_run_repo, top_n)
        _log.info(
            "internal.crawl.complete",
            crawl_run_id=stats.get("crawl_run_id"),
            totals=stats.get("totals"),
            department_id=str(dept_uuid) if dept_uuid else None,
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
    """Run a global crawl synchronously and return the stats (env-PAT)."""

    try:
        stats = await _run_crawl_isolated()
    except Exception as exc:  # noqa: BLE001
        _log.exception("internal.crawl.failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"crawl failed: {exc}",
        ) from exc
    return {"status": "ok", **stats}


@router.post(
    "/internal/departments/{dept_slug}/crawl",
    status_code=status.HTTP_200_OK,
)
async def trigger_dept_crawl(
    dept_slug: str,
    auth: tuple[Department, DepartmentPAT] = Depends(require_dept_pat),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Run a dept-scoped crawl. PAT's department must match the path slug."""

    dept, _pat = auth

    # The PAT we just authenticated determines the *real* dept the crawl
    # runs against; the slug in the URL is a redundancy check so a leaked
    # PAT can't be silently used against a different dept by URL-tweaking.
    if dept.slug != dept_slug:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="token does not belong to this department",
        )

    # Re-resolve the dept by slug too, defensively, so we 404 cleanly
    # if the dept was deleted between PAT mint and this call.
    stmt = select(Department).where(Department.slug == dept_slug).limit(1)
    fresh = (await session.execute(stmt)).scalar_one_or_none()
    if fresh is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Department not found"
        )

    try:
        stats = await _run_crawl_isolated(department_id=fresh.id)
    except Exception as exc:  # noqa: BLE001
        _log.exception(
            "internal.dept_crawl.failed",
            dept_slug=dept_slug,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"crawl failed: {exc}",
        ) from exc
    return {"status": "ok", "department": dept_slug, **stats}


@router.post(
    "/crawl",
    status_code=status.HTTP_200_OK,
)
async def trigger_crawl_ui() -> dict[str, Any]:
    """Run a crawl from the UI (session-cookie auth handled by middleware)."""

    try:
        stats = await _run_crawl_isolated()
    except Exception as exc:  # noqa: BLE001
        _log.exception("crawl.failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"crawl failed: {exc}",
        ) from exc
    return {"status": "ok", **stats}


__all__ = ["router", "_run_crawl_isolated"]
