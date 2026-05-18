"""``GET /crawl-config`` and ``PUT /crawl-config/{source_name}`` — per-source crawl settings.

Phase 5: the ``crawl_config`` table is the single source of truth for mutable
crawl settings (enabled + top_n). The crawler reads it at the start of each
run. This route lets the UI toggle sources and adjust N.

Mounted at ``/api/crawl-config`` (prefix applied in ``main.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas import CrawlConfigResponse, CrawlConfigUpdateRequest
from core.models import CrawlConfig

router = APIRouter()


@router.get("/crawl-config", response_model=list[CrawlConfigResponse])
async def list_crawl_config(
    session: AsyncSession = Depends(get_session),
) -> list[CrawlConfigResponse]:
    """Return all crawl config rows, ordered by source_name."""
    stmt = select(CrawlConfig).order_by(CrawlConfig.source_name)
    rows = (await session.execute(stmt)).scalars().all()
    return [CrawlConfigResponse.model_validate(r) for r in rows]


@router.put("/crawl-config/{source_name}", response_model=CrawlConfigResponse)
async def update_crawl_config(
    source_name: str,
    body: CrawlConfigUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> CrawlConfigResponse:
    """Update mutable fields (enabled, top_n) for one source."""
    # Build SET clause from non-None fields
    values: dict = {"updated_at": datetime.now(timezone.utc)}
    if body.enabled is not None:
        values["enabled"] = body.enabled
    if body.top_n is not None:
        values["top_n"] = body.top_n

    if len(values) == 1:
        raise HTTPException(status_code=400, detail="No fields to update")

    stmt = (
        update(CrawlConfig)
        .where(CrawlConfig.source_name == source_name)
        .values(**values)
        .returning(CrawlConfig)
    )
    result = (await session.execute(stmt)).first()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Source '{source_name}' not found")
    await session.commit()
    return CrawlConfigResponse.model_validate(result)


__all__ = ["router"]
