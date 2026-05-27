"""``GET/POST/PUT/DELETE /crawl-config`` — global tech config per source.

Phase 10 (MT-006): this table holds only tech tuning knobs (``top_n``,
``capture_summary``, ``verify_ssl``, ``feed_url``) that apply uniformly to
a source regardless of which department subscribes to it. Per-dept
subscription lives in ``department_sources`` (see
``/api/department-sources``).

All endpoints are **superadmin-only** because they affect every department
that subscribes to the source. Per-dept users toggle their own subscription
via ``PUT /api/department-sources/{source_name}`` instead.

Mounted at ``/api/crawl-config`` (prefix applied in ``main.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, get_session
from api.schemas import CrawlConfigCreateRequest, CrawlConfigResponse, CrawlConfigUpdateRequest
from core.models import CrawlConfig, User

router = APIRouter()


def _require_superadmin(user: User = Depends(get_current_user)) -> User:
    """Reject anyone who isn't a system-wide superadmin.

    Per-dept ``dept_lead`` does NOT qualify here — crawl_config is global
    tech config that affects every subscribing department.
    """

    if not user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin privilege required to manage crawl_config",
        )
    return user


@router.get(
    "/crawl-config",
    response_model=list[CrawlConfigResponse],
    dependencies=[Depends(_require_superadmin)],
)
async def list_crawl_config(
    session: AsyncSession = Depends(get_session),
) -> list[CrawlConfigResponse]:
    """Return all crawl config rows, ordered by source_name."""
    stmt = select(CrawlConfig).order_by(CrawlConfig.source_name)
    rows = (await session.execute(stmt)).scalars().all()
    return [CrawlConfigResponse.model_validate(r) for r in rows]


@router.post(
    "/crawl-config",
    response_model=CrawlConfigResponse,
    status_code=201,
    dependencies=[Depends(_require_superadmin)],
)
async def create_crawl_config(
    body: CrawlConfigCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> CrawlConfigResponse:
    """Create a new crawl source tech configuration."""
    existing = await session.get(CrawlConfig, body.source_name)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Source '{body.source_name}' already exists")

    row = CrawlConfig(
        source_name=body.source_name,
        top_n=body.top_n,
        capture_summary=body.capture_summary,
        verify_ssl=body.verify_ssl,
        feed_url=body.feed_url,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return CrawlConfigResponse.model_validate(row)


@router.put(
    "/crawl-config/{source_name}",
    response_model=CrawlConfigResponse,
    dependencies=[Depends(_require_superadmin)],
)
async def update_crawl_config(
    source_name: str,
    body: CrawlConfigUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> CrawlConfigResponse:
    """Update mutable tech fields for one source."""
    values: dict = {"updated_at": datetime.now(timezone.utc)}
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


@router.delete(
    "/crawl-config/{source_name}",
    status_code=204,
    dependencies=[Depends(_require_superadmin)],
)
async def delete_crawl_config(
    source_name: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a crawl source tech configuration."""
    stmt = delete(CrawlConfig).where(CrawlConfig.source_name == source_name)
    result = await session.execute(stmt)
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(status_code=404, detail=f"Source '{source_name}' not found")
    await session.commit()


__all__ = ["router"]
