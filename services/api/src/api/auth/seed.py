"""Seed user upsert — runs on app startup to ensure the configured user exists."""

from __future__ import annotations

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import hash_password
from core.models import User, UserDepartment

_log = structlog.get_logger(__name__)

# Must match the UUID in migration 0016
DEFAULT_DEPARTMENT_ID = "00000000-0000-0000-0000-000000000001"


async def ensure_seed_user(
    session: AsyncSession, *, username: str, password: str
) -> None:
    """Create or update the seed user.

    - If user doesn't exist: create with hashed password, superadmin, dept membership.
    - If user exists but password hash doesn't match: update hash.
    - If user exists and hash matches: no-op (except ensuring superadmin + dept).
    """
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(password),
            is_active=True,
            is_superadmin=True,
        )
        session.add(user)
        await session.flush()  # get user.id populated
        _log.info("auth.seed_user.created", username=username)
    else:
        # Update password if it changed
        from api.auth import verify_password

        if not verify_password(password, user.password_hash):
            user.password_hash = hash_password(password)
            _log.info("auth.seed_user.password_updated", username=username)
        else:
            _log.debug("auth.seed_user.unchanged", username=username)

        # Ensure superadmin
        if not user.is_superadmin:
            user.is_superadmin = True
            _log.info("auth.seed_user.promoted_superadmin", username=username)

    # Ensure membership in Default department
    dept_exists = await session.execute(
        select(UserDepartment).where(
            UserDepartment.user_id == user.id,
            UserDepartment.department_id == DEFAULT_DEPARTMENT_ID,
        )
    )
    if dept_exists.scalar_one_or_none() is None:
        # Check if Default department actually exists before inserting
        dept_check = await session.execute(
            text("SELECT 1 FROM departments WHERE id = :id"),
            {"id": DEFAULT_DEPARTMENT_ID},
        )
        if dept_check.scalar_one_or_none() is not None:
            session.add(
                UserDepartment(
                    user_id=user.id,
                    department_id=DEFAULT_DEPARTMENT_ID,
                    role="dept_lead",
                )
            )
            _log.info("auth.seed_user.dept_membership_added", username=username)

    await session.commit()


__all__ = ["ensure_seed_user"]
