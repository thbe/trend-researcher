"""Per-department Personal Access Token (PAT) management (plan 10-02 T09).

Endpoints:

- ``POST   /api/departments/{dept_id}/pats``        — dept_lead+ or superadmin.
  Mints a fresh bearer token, returns the plaintext **once**. Stores only
  its SHA-256 hash in ``department_pats.token_hash``.
- ``GET    /api/departments/{dept_id}/pats``        — viewer+ or superadmin.
  Lists metadata for this dept's PATs (active + revoked). Never returns
  plaintext or hash.
- ``DELETE /api/departments/{dept_id}/pats/{pat_id}`` — dept_lead+ or
  superadmin. Soft-deletes by setting ``revoked_at = now()``. Revoked
  tokens are kept indefinitely for audit. Idempotent: re-revoking a
  revoked row returns 204.

Authorisation mirrors :mod:`api.routes.departments` — direct
membership/superadmin checks rather than :func:`require_role`, because
the SPA hits these endpoints from the management panel rather than via
the per-request ``X-Active-Department`` header.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, get_session
from api.middleware.pat_auth import hash_pat_token
from api.routes.departments import (
    _assert_dept_lead_or_superadmin,
    _assert_member_or_superadmin,
    _get_department_or_404,
)
from api.schemas import (
    DepartmentPATCreate,
    DepartmentPATCreateResponse,
    DepartmentPATResponse,
    DepartmentPATsListResponse,
)
from core.models import DepartmentPAT, User

router = APIRouter()


@router.post(
    "/departments/{dept_id}/pats",
    response_model=DepartmentPATCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_department_pat(
    dept_id: UUID,
    body: DepartmentPATCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DepartmentPATCreateResponse:
    """Mint a new dept-scoped bearer. Plaintext returned once; never stored."""

    dept = await _get_department_or_404(session, dept_id)
    await _assert_dept_lead_or_superadmin(session, current_user, dept.id)

    plaintext = secrets.token_urlsafe(32)
    token_hash = hash_pat_token(plaintext)

    pat = DepartmentPAT(
        department_id=dept.id,
        name=body.name,
        token_hash=token_hash,
        created_by=current_user.id,
    )
    session.add(pat)
    await session.commit()
    await session.refresh(pat)

    return DepartmentPATCreateResponse(
        id=pat.id,
        name=pat.name,
        token=plaintext,
        created_at=pat.created_at,
    )


@router.get(
    "/departments/{dept_id}/pats",
    response_model=DepartmentPATsListResponse,
)
async def list_department_pats(
    dept_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DepartmentPATsListResponse:
    """Metadata for every PAT (active and revoked) on this department."""

    dept = await _get_department_or_404(session, dept_id)
    await _assert_member_or_superadmin(session, current_user, dept.id)

    stmt = (
        select(DepartmentPAT)
        .where(DepartmentPAT.department_id == dept.id)
        .order_by(DepartmentPAT.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    pats = [DepartmentPATResponse.model_validate(p) for p in rows]
    return DepartmentPATsListResponse(pats=pats, total=len(pats))


@router.delete(
    "/departments/{dept_id}/pats/{pat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_department_pat(
    dept_id: UUID,
    pat_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft-delete the PAT. Idempotent — re-revoking still returns 204."""

    dept = await _get_department_or_404(session, dept_id)
    await _assert_dept_lead_or_superadmin(session, current_user, dept.id)

    pat = await session.get(DepartmentPAT, str(pat_id))
    if pat is None or pat.department_id != dept.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="PAT not found"
        )
    if pat.revoked_at is None:
        pat.revoked_at = datetime.now(timezone.utc)
        await session.commit()
