"""``GET /runs`` — last N ``crawl_runs`` rows newest-first.

Pagination is the simplest thing that satisfies OPS-001 / OPS-002:
``?limit`` (default 20, clamped to ``[1, 100]`` by FastAPI Query
validation), ``ORDER BY started_at DESC``, no offset, no cursor — the
operator only ever needs the recent tail of the run-history table to spot
ingest failures, and the table is small enough that this stays cheap.

Per Phase 3 CONTEXT.md the response is a JSON object (``{runs:[...],
limit:N}``) rather than a bare array so future fields (eg. ``next_cursor``)
can be added without breaking consumers.

Mounted at ``/api/runs`` (prefix applied in ``main.py`` so the SPA catch-all
at ``/`` doesn't swallow this route — see Phase 4 CONTEXT.md G2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas import RunResponse, RunsListResponse
from core.models import CrawlRun

router = APIRouter()


@router.get("/runs", response_model=RunsListResponse)
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> RunsListResponse:
    """Return the most-recent ``limit`` ``crawl_runs`` rows, newest first."""

    stmt = select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return RunsListResponse(
        runs=[RunResponse.model_validate(row) for row in rows],
        limit=limit,
    )


__all__ = ["router"]
