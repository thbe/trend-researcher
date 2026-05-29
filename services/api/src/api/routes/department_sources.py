"""``GET/PUT /department-sources`` — per-dept crawl source subscriptions.

Phase 10 (MT-006), updated 2026-05 for source ownership:

- ``GET /api/department-sources`` — **viewer+** in the active dept. Returns
  every known source joined with the active dept's effective subscription
  state. Sources the active dept *owns* are always returned with
  ``enabled=true`` and ``owned=true`` (owners are implicitly subscribed
  and cannot toggle themselves off). Other sources reflect the row in
  ``department_sources`` (``false`` if no row).

- ``PUT /api/department-sources/{source_name}`` — **analyst+** (or
  superadmin) in the active dept. Toggles the active dept's subscription
  to a source it does **not** own. Toggling a source the active dept owns
  returns 400 (use ``/api/crawl-config`` to delete it instead).

The active department is resolved from the ``X-Active-Department``
header by :func:`api.dependencies.get_active_department`, so cross-dept
toggling is impossible.

Mounted at ``/api/department-sources`` (prefix applied in ``main.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID as UUIDType

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
from core.models import CrawlConfig, Department, DepartmentSource

router = APIRouter()


def _require_writer(
    active: ActiveDepartment = Depends(get_active_department),
) -> ActiveDepartment:
    """Allow analyst+ (or superadmin override) for write ops."""

    if active.is_superadmin_override:
        return active
    if active.role not in ("analyst", "dept_lead"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="analyst or dept_lead role required to manage source subscriptions",
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
    """Return every known source joined with the active dept's flag + owner.

    Owned sources are always enabled (owners are implicitly subscribed).
    Non-owned sources reflect any row the active dept has in
    ``department_sources`` (``false`` if no row). Ordered by source_name.
    """

    active_dept_id = str(active.department.id)
    stmt = (
        select(
            CrawlConfig.source_name,
            CrawlConfig.department_id,
            Department.name.label("owner_name"),
            CrawlConfig.top_n,
            CrawlConfig.capture_summary,
            CrawlConfig.verify_ssl,
            CrawlConfig.feed_url,
            DepartmentSource.enabled,
        )
        .select_from(CrawlConfig)
        .join(Department, Department.id == CrawlConfig.department_id)
        .outerjoin(
            DepartmentSource,
            (DepartmentSource.source_name == CrawlConfig.source_name)
            & (DepartmentSource.department_id == active_dept_id),
        )
        .order_by(CrawlConfig.source_name)
    )
    rows = (await session.execute(stmt)).all()
    sources: list[DepartmentSourceResponse] = []
    for r in rows:
        owned = str(r.department_id) == active_dept_id
        # Owners are implicitly subscribed; otherwise honour the subscription row.
        enabled = True if owned else (bool(r.enabled) if r.enabled is not None else False)
        sources.append(
            DepartmentSourceResponse(
                source_name=r.source_name,
                enabled=enabled,
                owned=owned,
                owner_department_id=UUIDType(str(r.department_id)),
                owner_department_name=r.owner_name,
                top_n=r.top_n,
                capture_summary=r.capture_summary,
                verify_ssl=r.verify_ssl,
                feed_url=r.feed_url,
            )
        )
    return DepartmentSourcesListResponse(sources=sources, total=len(sources))


@router.put(
    "/department-sources/{source_name}",
    response_model=DepartmentSourceResponse,
)
async def update_department_source(
    source_name: str,
    body: DepartmentSourceUpdateRequest,
    active: ActiveDepartment = Depends(_require_writer),
    session: AsyncSession = Depends(get_session),
) -> DepartmentSourceResponse:
    """Upsert the active dept's subscription flag for one non-owned source.

    - 404 if the source doesn't exist in ``crawl_config``.
    - 400 if the active dept owns the source (owners are always subscribed;
      to stop crawling it, delete the source via ``/api/crawl-config``).
    """

    stmt = (
        select(CrawlConfig, Department)
        .join(Department, Department.id == CrawlConfig.department_id)
        .where(CrawlConfig.source_name == source_name)
    )
    result = (await session.execute(stmt)).first()
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"Source '{source_name}' not found"
        )
    cfg, owner = result

    active_dept_id = str(active.department.id)
    owned = str(cfg.department_id) == active_dept_id
    if owned:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Source '{source_name}' is owned by this department and is "
                "always subscribed. Delete it via /api/crawl-config to stop "
                "crawling."
            ),
        )

    now = datetime.now(timezone.utc)
    stmt_upsert = (
        pg_insert(DepartmentSource)
        .values(
            department_id=active_dept_id,
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
    await session.execute(stmt_upsert)
    await session.commit()

    return DepartmentSourceResponse(
        source_name=source_name,
        enabled=body.enabled,
        owned=False,
        owner_department_id=UUIDType(str(cfg.department_id)),
        owner_department_name=owner.name,
        top_n=cfg.top_n,
        capture_summary=cfg.capture_summary,
        verify_ssl=cfg.verify_ssl,
        feed_url=cfg.feed_url,
    )


__all__ = ["router"]
