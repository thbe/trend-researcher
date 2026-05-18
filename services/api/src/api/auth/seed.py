"""Seed user upsert — runs on app startup to ensure the configured user exists."""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import hash_password
from core.models import User

_log = structlog.get_logger(__name__)


async def ensure_seed_user(
    session: AsyncSession, *, username: str, password: str
) -> None:
    """Create or update the seed user.

    - If user doesn't exist: create with hashed password.
    - If user exists but password hash doesn't match: update hash.
    - If user exists and hash matches: no-op.
    """
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(password),
            is_active=True,
        )
        session.add(user)
        await session.commit()
        _log.info("auth.seed_user.created", username=username)
    else:
        # Update password if it changed
        from api.auth import verify_password

        if not verify_password(password, user.password_hash):
            user.password_hash = hash_password(password)
            await session.commit()
            _log.info("auth.seed_user.password_updated", username=username)
        else:
            _log.debug("auth.seed_user.unchanged", username=username)


__all__ = ["ensure_seed_user"]
