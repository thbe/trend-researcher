"""Departments + memberships CRUD endpoints (Phase 10, MT-001 / MT-002).

Auth matrix:
- ``GET /api/departments``                        — any logged-in user; result
  filtered to memberships unless ``is_superadmin``.
- ``GET /api/departments/{id}``                   — superadmin or member.
- ``POST /api/departments``                       — superadmin only.
- ``PUT /api/departments/{id}``                   — superadmin or dept_lead of
  this dept.
- ``DELETE /api/departments/{id}``                — superadmin only; 409 if
  the dept is the Default seed (slug == ``"default"``).
- ``GET /api/departments/{id}/members``           — superadmin or dept_lead.
- ``POST /api/departments/{id}/members``          — superadmin or dept_lead;
  409 on duplicate.
- ``PUT /api/departments/{id}/members/{user_id}`` — superadmin or dept_lead;
  409 if the change would leave the dept with zero ``dept_lead`` members.
- ``DELETE /api/departments/{id}/members/{user_id}`` — same; 409 on last
  dept_lead.

The active-department header (``X-Active-Department``) is NOT required for
this router — ``/api/departments`` is the discovery surface the SPA hits
*before* picking an active department, and would deadlock if it required
one. Per-dept authorisation here is done by direct membership/superadmin
checks instead of via :func:`require_role`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, get_session
from api.schemas import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentsListResponse,
    DepartmentUpdate,
    MemberCreate,
    MemberResponse,
    MembersListResponse,
    MemberUpdate,
)
from core.models import Department, User, UserDepartment

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_department_or_404(
    session: AsyncSession, dept_id: UUID
) -> Department:
    dept = await session.get(Department, str(dept_id))
    if dept is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Department not found"
        )
    return dept


async def _assert_member_or_superadmin(
    session: AsyncSession, user: User, dept_id: str
) -> UserDepartment | None:
    """Return the membership row, or None if the caller is superadmin.

    Raises 403 when the caller is neither superadmin nor a member.
    """

    if user.is_superadmin:
        return None
    membership = await session.get(UserDepartment, (user.id, dept_id))
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this department",
        )
    return membership


async def _assert_dept_lead_or_superadmin(
    session: AsyncSession, user: User, dept_id: str
) -> None:
    if user.is_superadmin:
        return
    membership = await session.get(UserDepartment, (user.id, dept_id))
    if membership is None or membership.role != "dept_lead":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires dept_lead role in this department",
        )


def _require_superadmin(user: User) -> None:
    if not user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires superadmin",
        )


async def _count_dept_leads(session: AsyncSession, dept_id: str) -> int:
    from sqlalchemy import func

    result = await session.execute(
        select(func.count())
        .select_from(UserDepartment)
        .where(
            UserDepartment.department_id == dept_id,
            UserDepartment.role == "dept_lead",
        )
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Department CRUD
# ---------------------------------------------------------------------------


@router.get("/departments", response_model=DepartmentsListResponse)
async def list_departments(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DepartmentsListResponse:
    """List departments. Non-superadmin sees only their memberships."""

    if current_user.is_superadmin:
        stmt = select(Department).order_by(Department.name)
    else:
        stmt = (
            select(Department)
            .join(
                UserDepartment, UserDepartment.department_id == Department.id
            )
            .where(UserDepartment.user_id == current_user.id)
            .order_by(Department.name)
        )
    rows = (await session.execute(stmt)).scalars().all()
    items = [DepartmentResponse.model_validate(r) for r in rows]
    return DepartmentsListResponse(departments=items, total=len(items))


@router.post(
    "/departments",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_department(
    body: DepartmentCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DepartmentResponse:
    _require_superadmin(current_user)

    dept = Department(
        name=body.name, slug=body.slug, description=body.description
    )
    session.add(dept)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Department with this name or slug already exists",
        ) from exc
    await session.refresh(dept)
    return DepartmentResponse.model_validate(dept)


@router.get("/departments/{dept_id}", response_model=DepartmentResponse)
async def get_department(
    dept_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DepartmentResponse:
    dept = await _get_department_or_404(session, dept_id)
    await _assert_member_or_superadmin(session, current_user, dept.id)
    return DepartmentResponse.model_validate(dept)


@router.put("/departments/{dept_id}", response_model=DepartmentResponse)
async def update_department(
    dept_id: UUID,
    body: DepartmentUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DepartmentResponse:
    dept = await _get_department_or_404(session, dept_id)
    await _assert_dept_lead_or_superadmin(session, current_user, dept.id)

    changed = False
    if body.name is not None:
        dept.name = body.name
        changed = True
    if body.description is not None:
        dept.description = body.description
        changed = True
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    dept.updated_at = datetime.now(timezone.utc)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Department with this name already exists",
        ) from exc
    await session.refresh(dept)
    return DepartmentResponse.model_validate(dept)


@router.delete(
    "/departments/{dept_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_department(
    dept_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    _require_superadmin(current_user)
    dept = await _get_department_or_404(session, dept_id)
    if dept.slug == "default":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete the Default department",
        )
    await session.delete(dept)
    await session.commit()


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------


@router.get(
    "/departments/{dept_id}/members", response_model=MembersListResponse
)
async def list_members(
    dept_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MembersListResponse:
    dept = await _get_department_or_404(session, dept_id)
    await _assert_dept_lead_or_superadmin(session, current_user, dept.id)

    stmt = (
        select(UserDepartment, User)
        .join(User, User.id == UserDepartment.user_id)
        .where(UserDepartment.department_id == dept.id)
        .order_by(User.username)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        MemberResponse(
            user_id=UUID(membership.user_id),
            username=user.username,
            role=membership.role,
            created_at=membership.created_at,
            updated_at=membership.updated_at,
        )
        for membership, user in rows
    ]
    return MembersListResponse(members=items, total=len(items))


@router.post(
    "/departments/{dept_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    dept_id: UUID,
    body: MemberCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MemberResponse:
    dept = await _get_department_or_404(session, dept_id)
    await _assert_dept_lead_or_superadmin(session, current_user, dept.id)

    user = await session.get(User, str(body.user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    membership = UserDepartment(
        user_id=user.id, department_id=dept.id, role=body.role
    )
    session.add(membership)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this department",
        ) from exc
    await session.refresh(membership)
    return MemberResponse(
        user_id=UUID(membership.user_id),
        username=user.username,
        role=membership.role,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


@router.put(
    "/departments/{dept_id}/members/{user_id}", response_model=MemberResponse
)
async def update_member(
    dept_id: UUID,
    user_id: UUID,
    body: MemberUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MemberResponse:
    dept = await _get_department_or_404(session, dept_id)
    await _assert_dept_lead_or_superadmin(session, current_user, dept.id)

    membership = await session.get(UserDepartment, (str(user_id), dept.id))
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this department",
        )

    # Prevent demoting the last dept_lead.
    if membership.role == "dept_lead" and body.role != "dept_lead":
        leads = await _count_dept_leads(session, dept.id)
        if leads <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot demote the last dept_lead of this department",
            )

    membership.role = body.role
    membership.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(membership)

    user = await session.get(User, membership.user_id)
    assert user is not None  # FK guarantees this
    return MemberResponse(
        user_id=UUID(membership.user_id),
        username=user.username,
        role=membership.role,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


@router.delete(
    "/departments/{dept_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    dept_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    dept = await _get_department_or_404(session, dept_id)
    await _assert_dept_lead_or_superadmin(session, current_user, dept.id)

    membership = await session.get(UserDepartment, (str(user_id), dept.id))
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this department",
        )

    if membership.role == "dept_lead":
        leads = await _count_dept_leads(session, dept.id)
        if leads <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot remove the last dept_lead of this department",
            )

    await session.delete(membership)
    await session.commit()


__all__ = ["router"]
