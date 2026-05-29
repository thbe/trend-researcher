"""``GET/POST/PUT/DELETE /crawl-config`` — sources with dept ownership.

Each crawl source is owned by exactly one department (``crawl_config.
department_id``, added in migration 0022). The crawler still fetches each
source once globally (``source_name`` is the primary key), but ownership
governs who can manage the row:

- **Superadmin** — sees every source; may CRUD any; must pick / may
  change ``department_id`` (owner) on create / update.
- **Dept lead / analyst** — sees only sources owned by their active
  department; may create, edit, delete those. ``department_id`` on
  create is forced to the active dept; on update it is rejected (only
  superadmins can reassign ownership).
- **Viewer** — sees only sources owned by their active department;
  read-only.

Other departments consume a source they don't own by toggling a row in
``department_sources`` (see ``/api/department-sources``). Owner depts are
implicitly always subscribed.

Mounted at ``/api/crawl-config`` (prefix applied in ``main.py``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID as UUIDType

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    ActiveDepartment,
    get_active_department,
    get_current_user,
    get_session,
)
from api.schemas import CrawlConfigCreateRequest, CrawlConfigResponse, CrawlConfigUpdateRequest
from core.models import CrawlConfig, Department, User

router = APIRouter()


def _require_writer(
    active: ActiveDepartment = Depends(get_active_department),
) -> ActiveDepartment:
    """Allow analyst+ in the active dept (or superadmin override)."""

    if active.is_superadmin_override:
        return active
    if active.role not in ("analyst", "dept_lead"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="analyst or dept_lead role required to manage sources",
        )
    return active


def _serialize(row: CrawlConfig, dept: Department) -> CrawlConfigResponse:
    """Shared row → response shape (need dept name from a join)."""

    return CrawlConfigResponse(
        source_name=row.source_name,
        department_id=UUIDType(str(row.department_id)),
        department_name=dept.name,
        top_n=row.top_n,
        capture_summary=row.capture_summary,
        verify_ssl=row.verify_ssl,
        feed_url=row.feed_url,
        updated_at=row.updated_at,
    )


@router.get(
    "/crawl-config",
    response_model=list[CrawlConfigResponse],
)
async def list_crawl_config(
    active: ActiveDepartment = Depends(get_active_department),
    session: AsyncSession = Depends(get_session),
) -> list[CrawlConfigResponse]:
    """List sources.

    Superadmins (or anyone using the superadmin override) see every row;
    everyone else sees only rows owned by the active department.
    """

    stmt = (
        select(CrawlConfig, Department)
        .join(Department, Department.id == CrawlConfig.department_id)
        .order_by(CrawlConfig.source_name)
    )
    if not active.is_superadmin_override:
        stmt = stmt.where(CrawlConfig.department_id == active.department.id)

    rows = (await session.execute(stmt)).all()
    return [_serialize(cfg, dept) for cfg, dept in rows]


@router.post(
    "/crawl-config",
    response_model=CrawlConfigResponse,
    status_code=201,
)
async def create_crawl_config(
    body: CrawlConfigCreateRequest,
    active: ActiveDepartment = Depends(_require_writer),
    session: AsyncSession = Depends(get_session),
) -> CrawlConfigResponse:
    """Create a new crawl source.

    For superadmins, ``department_id`` in the body is required (must
    reference an existing department). For dept-scoped users, any
    ``department_id`` they send is ignored — ownership is forced to the
    active department.
    """

    if active.is_superadmin_override:
        if body.department_id is None:
            raise HTTPException(
                status_code=422,
                detail="department_id is required when creating a source as superadmin",
            )
        owner_id = str(body.department_id)
    else:
        owner_id = str(active.department.id)

    owner = await session.get(Department, owner_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"Department '{owner_id}' not found")

    existing = await session.get(CrawlConfig, body.source_name)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Source '{body.source_name}' already exists")

    row = CrawlConfig(
        source_name=body.source_name,
        department_id=owner_id,
        top_n=body.top_n,
        capture_summary=body.capture_summary,
        verify_ssl=body.verify_ssl,
        feed_url=body.feed_url,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _serialize(row, owner)


async def _load_owned_or_403(
    session: AsyncSession,
    active: ActiveDepartment,
    source_name: str,
) -> tuple[CrawlConfig, Department]:
    """Fetch a source + its owner, enforcing ownership for non-superadmins."""

    stmt = (
        select(CrawlConfig, Department)
        .join(Department, Department.id == CrawlConfig.department_id)
        .where(CrawlConfig.source_name == source_name)
    )
    result = (await session.execute(stmt)).first()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Source '{source_name}' not found")
    cfg, dept = result
    if not active.is_superadmin_override and str(cfg.department_id) != str(active.department.id):
        # Hide ownership: 404 (not 403) to avoid leaking the source's existence
        # to dept users who shouldn't see it. They literally don't see it in
        # the list, so a 404 here is consistent.
        raise HTTPException(status_code=404, detail=f"Source '{source_name}' not found")
    return cfg, dept


@router.put(
    "/crawl-config/{source_name}",
    response_model=CrawlConfigResponse,
)
async def update_crawl_config(
    source_name: str,
    body: CrawlConfigUpdateRequest,
    active: ActiveDepartment = Depends(_require_writer),
    session: AsyncSession = Depends(get_session),
) -> CrawlConfigResponse:
    """Update mutable tech fields for one source.

    Dept-scoped writers may not reassign ``department_id`` — that is a
    superadmin-only operation.
    """

    cfg, current_owner = await _load_owned_or_403(session, active, source_name)

    values: dict = {"updated_at": datetime.now(timezone.utc)}
    if body.top_n is not None:
        values["top_n"] = body.top_n
    if body.capture_summary is not None:
        values["capture_summary"] = body.capture_summary
    if body.verify_ssl is not None:
        values["verify_ssl"] = body.verify_ssl
    if body.feed_url is not None:
        values["feed_url"] = body.feed_url

    new_owner = current_owner
    if body.department_id is not None and str(body.department_id) != str(cfg.department_id):
        if not active.is_superadmin_override:
            raise HTTPException(
                status_code=403,
                detail="Only superadmins can reassign source ownership",
            )
        new_owner_id = str(body.department_id)
        candidate = await session.get(Department, new_owner_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"Department '{new_owner_id}' not found")
        values["department_id"] = new_owner_id
        new_owner = candidate

    if len(values) == 1:
        raise HTTPException(status_code=400, detail="No fields to update")

    stmt = (
        update(CrawlConfig)
        .where(CrawlConfig.source_name == source_name)
        .values(**values)
        .returning(CrawlConfig)
    )
    result = (await session.execute(stmt)).first()
    if result is None:  # defensive — already verified above
        raise HTTPException(status_code=404, detail=f"Source '{source_name}' not found")
    await session.commit()
    return _serialize(result[0], new_owner)


@router.delete(
    "/crawl-config/{source_name}",
    status_code=204,
)
async def delete_crawl_config(
    source_name: str,
    active: ActiveDepartment = Depends(_require_writer),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a source. Dept writers can only delete sources they own."""

    # Reuse the ownership check (raises 404 for non-owners).
    await _load_owned_or_403(session, active, source_name)

    stmt = delete(CrawlConfig).where(CrawlConfig.source_name == source_name)
    await session.execute(stmt)
    await session.commit()


__all__ = ["router"]
