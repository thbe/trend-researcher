"""User management endpoints (superadmin only).

Auth matrix:
- ``GET /api/users``          — superadmin only; lists all users.
- ``POST /api/users``         — superadmin only; creates a new user.
- ``DELETE /api/users/{id}``  — superadmin only; deactivates user (soft-delete).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import hash_password
from api.dependencies import get_current_user, get_session
from core.models import User

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=6)
    is_superadmin: bool = False


class UserResponse(BaseModel):
    id: UUID
    username: str
    is_active: bool
    is_superadmin: bool
    created_at: str


class UsersListResponse(BaseModel):
    users: list[UserResponse]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_superadmin(user: User) -> None:
    if not user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin required",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/users", response_model=UsersListResponse)
async def list_users(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UsersListResponse:
    """List all users (superadmin only)."""
    _require_superadmin(current_user)
    result = await session.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.created_at)
    )
    users = result.scalars().all()
    return UsersListResponse(
        users=[
            UserResponse(
                id=UUID(u.id),
                username=u.username,
                is_active=u.is_active,
                is_superadmin=u.is_superadmin,
                created_at=str(u.created_at),
            )
            for u in users
        ]
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Create a new user (superadmin only)."""
    _require_superadmin(current_user)

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        is_active=True,
        is_superadmin=body.is_superadmin,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        ) from exc
    await session.refresh(user)
    return UserResponse(
        id=UUID(user.id),
        username=user.username,
        is_active=user.is_active,
        is_superadmin=user.is_superadmin,
        created_at=str(user.created_at),
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Deactivate a user (superadmin only). Cannot deactivate yourself."""
    _require_superadmin(current_user)

    if str(user_id) == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate yourself",
        )

    user = await session.get(User, str(user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    user.is_active = False
    await session.commit()
