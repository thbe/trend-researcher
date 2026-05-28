"""Assessment frameworks endpoints (Phase 10, plan 10-03 T08).

GET  /api/frameworks         — list all system frameworks (any logged-in user).
GET  /api/frameworks/mine    — list frameworks enabled for the active dept,
                                with the dept's default flagged.
PUT  /api/frameworks/mine    — replace the active dept's enabled set + default
                                (dept_lead or superadmin).

The full ``json_schema`` is intentionally NOT exposed in either listing —
it's large and only needed for client-side validation, which is a v2
concern. The SPA renders rows by switching on ``display_component``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    ActiveDepartment,
    get_active_department,
    get_current_user,
    get_session,
    require_role,
)
from api.schemas import (
    DepartmentFrameworkResponse,
    DepartmentFrameworksListResponse,
    DepartmentFrameworksUpdate,
    FrameworkResponse,
    FrameworksListResponse,
)
from core.models import AssessmentFramework, DepartmentFramework, User

router = APIRouter()


@router.get("/frameworks", response_model=FrameworksListResponse)
async def list_frameworks(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FrameworksListResponse:
    """List all system-level assessment frameworks (any authenticated user).

    No dept context required — this is the catalogue surface a dept_lead
    sees when picking which frameworks to enable for their dept.
    """

    stmt = select(AssessmentFramework).order_by(AssessmentFramework.name)
    rows = (await session.execute(stmt)).scalars().all()
    items = [FrameworkResponse.model_validate(r) for r in rows]
    return FrameworksListResponse(frameworks=items, total=len(items))


@router.get(
    "/frameworks/mine", response_model=DepartmentFrameworksListResponse
)
async def list_my_frameworks(
    ad: ActiveDepartment = Depends(get_active_department),
    session: AsyncSession = Depends(get_session),
) -> DepartmentFrameworksListResponse:
    """List frameworks enabled for the active department.

    Each row carries the framework metadata + the dept-scoped ``is_default``
    flag. The DB partial unique index guarantees at most one default per
    dept (migration 0019).
    """

    stmt = (
        select(AssessmentFramework, DepartmentFramework.is_default)
        .join(
            DepartmentFramework,
            DepartmentFramework.framework_id == AssessmentFramework.id,
        )
        .where(DepartmentFramework.department_id == ad.department.id)
        .order_by(AssessmentFramework.name)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        DepartmentFrameworkResponse(
            id=UUID(fw.id),
            key=fw.key,
            name=fw.name,
            description=fw.description,
            display_component=fw.display_component,
            prompt_version=fw.prompt_version,
            is_default=bool(is_default),
        )
        for fw, is_default in rows
    ]
    return DepartmentFrameworksListResponse(frameworks=items, total=len(items))


@router.put(
    "/frameworks/mine",
    response_model=DepartmentFrameworksListResponse,
    dependencies=[Depends(require_role("dept_lead"))],
)
async def update_my_frameworks(
    body: DepartmentFrameworksUpdate,
    ad: ActiveDepartment = Depends(get_active_department),
    session: AsyncSession = Depends(get_session),
) -> DepartmentFrameworksListResponse:
    """Replace the active dept's ``department_frameworks`` rows.

    Pydantic-level validation already enforces ``default ∈ enabled``. The
    server additionally verifies every ``enabled`` id exists in
    ``assessment_frameworks`` (else 422) and then DELETE+INSERTs in one
    transaction. Drop is safe — ``department_frameworks.framework_id`` uses
    ``ON DELETE RESTRICT`` only against ``assessment_frameworks``, not the
    other way around.
    """

    enabled_ids = [str(fid) for fid in body.enabled]

    # Verify every requested framework exists.
    existing = (
        await session.execute(
            select(AssessmentFramework.id).where(
                AssessmentFramework.id.in_(enabled_ids)
            )
        )
    ).scalars().all()
    missing = set(enabled_ids) - set(existing)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown framework id(s): {sorted(missing)}",
        )

    default_id = str(body.default)
    dept_id = ad.department.id

    # Replace the set atomically. Note: department_frameworks is the LINK
    # table; deleting link rows is always safe (RESTRICT only fires when
    # deleting from assessment_frameworks itself).
    await session.execute(
        delete(DepartmentFramework).where(
            DepartmentFramework.department_id == dept_id
        )
    )
    for fid in enabled_ids:
        session.add(
            DepartmentFramework(
                department_id=dept_id,
                framework_id=fid,
                is_default=(fid == default_id),
            )
        )
    await session.commit()

    # Re-read to return the canonical response.
    stmt = (
        select(AssessmentFramework, DepartmentFramework.is_default)
        .join(
            DepartmentFramework,
            DepartmentFramework.framework_id == AssessmentFramework.id,
        )
        .where(DepartmentFramework.department_id == dept_id)
        .order_by(AssessmentFramework.name)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        DepartmentFrameworkResponse(
            id=UUID(fw.id),
            key=fw.key,
            name=fw.name,
            description=fw.description,
            display_component=fw.display_component,
            prompt_version=fw.prompt_version,
            is_default=bool(is_default),
        )
        for fw, is_default in rows
    ]
    return DepartmentFrameworksListResponse(frameworks=items, total=len(items))


__all__ = ["router"]
