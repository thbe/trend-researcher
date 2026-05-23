"""``GET /crawl-config``, ``POST /crawl-config``, ``PUT /crawl-config/{source_name}``, ``DELETE /crawl-config/{source_name}``

Phase 5: the ``crawl_config`` table is the single source of truth for mutable
crawl settings (enabled + top_n). The crawler reads it at the start of each
run. This route lets the UI toggle sources and adjust N.

Extended: add/delete sources, per-source SSL verification toggle.

Mounted at ``/api/crawl-config`` (prefix applied in ``main.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas import CrawlConfigCreateRequest, CrawlConfigResponse, CrawlConfigUpdateRequest
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


@router.post("/crawl-config", response_model=CrawlConfigResponse, status_code=201)
async def create_crawl_config(
    body: CrawlConfigCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> CrawlConfigResponse:
    """Create a new crawl source configuration."""
    # Check for duplicate
    existing = await session.get(CrawlConfig, body.source_name)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Source '{body.source_name}' already exists")

    row = CrawlConfig(
        source_name=body.source_name,
        enabled=body.enabled,
        top_n=body.top_n,
        capture_summary=body.capture_summary,
        verify_ssl=body.verify_ssl,
        feed_url=body.feed_url,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return CrawlConfigResponse.model_validate(row)


@router.put("/crawl-config/{source_name}", response_model=CrawlConfigResponse)
async def update_crawl_config(
    source_name: str,
    body: CrawlConfigUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> CrawlConfigResponse:
    """Update mutable fields for one source."""
    values: dict = {"updated_at": datetime.now(timezone.utc)}
    if body.enabled is not None:
        values["enabled"] = body.enabled
    if body.top_n is not None:
        values["top_n"] = body.top_n
    if body.capture_summary is not None:
        values["capture_summary"] = body.capture_summary
    if body.verify_ssl is not None:
        values["verify_ssl"] = body.verify_ssl
    if body.feed_url is not None:
        values["feed_url"] = body.feed_url

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
    return CrawlConfigResponse.model_validate(result[0])


@router.delete("/crawl-config/{source_name}", status_code=204)
async def delete_crawl_config(
    source_name: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a crawl source configuration."""
    stmt = delete(CrawlConfig).where(CrawlConfig.source_name == source_name)
    result = await session.execute(stmt)
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(status_code=404, detail=f"Source '{source_name}' not found")
    await session.commit()


__all__ = ["router"]
