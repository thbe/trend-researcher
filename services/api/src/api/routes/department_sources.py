"""``GET/PUT /department-sources`` — per-dept crawl source subscriptions.

Phase 10 (MT-006): the active department's view of every known crawl
source, joined with its own subscription flag from
``department_sources``. A source the dept has never touched shows up
as ``enabled=false`` (LEFT JOIN), so the UI can render a single
checkbox list driven by ``crawl_config``.

- ``GET  /api/department-sources`` — **viewer+** in the active dept.
- ``PUT  /api/department-sources/{source_name}`` — **dept_lead+** (or
  superadmin) in the active dept. Validates that the source exists in
  ``crawl_config`` first (404 otherwise).

The active department is resolved from the ``X-Active-Department``
header by :func:`api.dependencies.get_active_department` (which also
verifies membership), so cross-dept toggling is impossible.

Mounted at ``/api/department-sources`` (prefix applied in ``main.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    ActiveDepartment,
    get_active_department,
    get_session,
    require_role,
)
from api.schemas import (
    DepartmentSourceResponse,
    DepartmentSourceUpdateRequest,
    DepartmentSourcesListResponse,
)
from core.models import CrawlConfig, DepartmentSource

router = APIRouter()


def _require_dept_lead(
    active: ActiveDepartment = Depends(get_active_department),
) -> ActiveDepartment:
    """Allow only ``dept_lead`` (or superadmin override) for write ops."""

    if active.is_superadmin_override:
        return active
    if active.role != "dept_lead":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dept_lead role required to manage source subscriptions",
        )
    return active


@router.get(
    "/department-sources",
    response_model=DepartmentSourcesListResponse,
)
async def list_department_sources(
    active: ActiveDepartment = Depends(
        require_role("viewer", "analyst", "dept_lead")
    ),
    session: AsyncSession = Depends(get_session),
) -> DepartmentSourcesListResponse:
    """Return every known source joined with this dept's enabled flag.

    LEFT JOIN ``crawl_config -> department_sources`` so sources the dept
    has never touched still render (with ``enabled=false``). Ordered by
    ``source_name`` for stable UI rendering.
    """

    stmt = (
        select(
            CrawlConfig.source_name,
            CrawlConfig.top_n,
            CrawlConfig.capture_summary,
            CrawlConfig.verify_ssl,
            CrawlConfig.feed_url,
            DepartmentSource.enabled,
        )
        .select_from(CrawlConfig)
        .outerjoin(
            DepartmentSource,
            (DepartmentSource.source_name == CrawlConfig.source_name)
            & (DepartmentSource.department_id == active.department.id),
        )
        .order_by(CrawlConfig.source_name)
    )
    rows = (await session.execute(stmt)).all()
    sources = [
        DepartmentSourceResponse(
            source_name=r.source_name,
            enabled=bool(r.enabled) if r.enabled is not None else False,
            top_n=r.top_n,
            capture_summary=r.capture_summary,
            verify_ssl=r.verify_ssl,
            feed_url=r.feed_url,
        )
        for r in rows
    ]
    return DepartmentSourcesListResponse(sources=sources, total=len(sources))


@router.put(
    "/department-sources/{source_name}",
    response_model=DepartmentSourceResponse,
)
async def update_department_source(
    source_name: str,
    body: DepartmentSourceUpdateRequest,
    active: ActiveDepartment = Depends(_require_dept_lead),
    session: AsyncSession = Depends(get_session),
) -> DepartmentSourceResponse:
    """Upsert the active dept's subscription flag for one source.

    Returns 404 if the source isn't in ``crawl_config`` — superadmins
    define which sources exist; per-dept users only toggle their view.
    """

    cfg = await session.get(CrawlConfig, source_name)
    if cfg is None:
        raise HTTPException(
            status_code=404, detail=f"Source '{source_name}' not found"
        )

    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(DepartmentSource)
        .values(
            department_id=active.department.id,
            source_name=source_name,
            enabled=body.enabled,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["department_id", "source_name"],
            set_={"enabled": body.enabled, "updated_at": now},
        )
    )
    await session.execute(stmt)
    await session.commit()

    return DepartmentSourceResponse(
        source_name=source_name,
        enabled=body.enabled,
        top_n=cfg.top_n,
        capture_summary=cfg.capture_summary,
        verify_ssl=cfg.verify_ssl,
        feed_url=cfg.feed_url,
    )


__all__ = ["router"]
