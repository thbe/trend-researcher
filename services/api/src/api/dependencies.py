"""DI wiring for the api service.

Lazy module-level engine + sessionmaker, built on first use, so importing
``api.main`` does NOT touch the database (tests can patch ``core.get_settings``
before the first request). FastAPI ``Depends(get_session)`` yields an
``AsyncSession`` per request and closes it on completion.

Phase 10 (MT-001/MT-002) additions:
- ``get_current_user`` — resolves the authenticated User row from the
  signed-cookie ``request.state.user`` (username string) set by
  :class:`api.auth.middleware.AuthMiddleware`.
- ``ActiveDepartment`` DTO + ``get_active_department`` — resolves the
  per-request active tenant from the ``X-Active-Department`` header,
  verifying membership server-side (the header is operator-supplied via the
  SPA and MUST NOT be trusted on its own).
- ``require_role(*allowed)`` — dependency factory that enforces the caller's
  role within the active department. ``is_superadmin`` bypasses the role
  check and is treated as ``dept_lead`` for any department.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast, get_args

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import core
from core.models import Department, RoleLiteral, User, UserDepartment

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    """Return the lazily-built process-wide engine."""

    global _engine
    if _engine is None:
        _engine = core.get_engine(core.get_settings().database_url)
    return _engine


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the lazily-built process-wide sessionmaker."""

    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = core.get_sessionmaker(_get_engine())
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield one ``AsyncSession`` per request."""

    sessionmaker = _get_sessionmaker()
    async with sessionmaker() as session:
        yield session


async def dispose_engine() -> None:
    """Tear down the process-wide engine (FastAPI lifespan shutdown).

    Idempotent: safe to call when no engine was ever built (e.g. import-only
    test runs). Resets the module-level singletons so a subsequent request
    rebuilds cleanly — useful when tests patch settings between cases.
    """

    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


def get_web_dist_dir() -> Path | None:
    """Return the SPA build directory if WEB_DIST_DIR points at a real dir.

    Returns ``None`` when the env var is unset or doesn't resolve to an existing
    directory — ``api.main`` then skips mounting StaticFiles (e.g. local dev
    where the SPA is served by ``vite`` on :5173 and proxies ``/api/*``).
    """

    raw = os.environ.get("WEB_DIST_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


# ---------------------------------------------------------------------------
# Phase 10: current-user + active-department dependencies (MT-001 / MT-002)
# ---------------------------------------------------------------------------


_ACTIVE_DEPARTMENT_HEADER = "X-Active-Department"
_VALID_ROLES: frozenset[str] = frozenset(get_args(RoleLiteral))


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the authenticated :class:`User` row for this request.

    ``AuthMiddleware`` validates the signed cookie and sets
    ``request.state.user`` to the username string. This dependency turns
    that into the actual ORM row so route handlers can read ``is_superadmin``,
    ``id``, etc. directly.

    Raises 401 if the cookie is missing/invalid (defensive — the middleware
    should have already rejected) or the user no longer exists / is inactive.
    """

    username = getattr(request.state, "user", None)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    result = await session.execute(
        select(User).where(User.username == username, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user no longer exists or is inactive",
        )
    return user


@dataclass(frozen=True)
class ActiveDepartment:
    """Per-request active-tenant context (MT-001 / MT-002).

    Attributes
    ----------
    department:
        The resolved :class:`Department` ORM row.
    role:
        The caller's role within ``department``. For ``is_superadmin`` users
        this is synthesised as ``"dept_lead"`` (system-wide admin acts as
        dept_lead in any department, even without an explicit membership).
    is_superadmin_override:
        ``True`` when the resolution succeeded *only* because the caller is
        ``is_superadmin`` (no real :class:`UserDepartment` row exists). Used
        by :func:`require_role` so that superadmin always passes any role
        check.
    """

    department: Department
    role: RoleLiteral
    is_superadmin_override: bool = False


async def get_active_department(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ActiveDepartment:
    """Resolve the active department for this request.

    Reads the ``X-Active-Department`` header (a department UUID) and verifies
    that ``current_user`` is a member of that department. The header is
    operator-supplied (SPA injects it from its active-dept Pinia store) — we
    MUST NOT trust it without a membership check, or any authenticated user
    could access any tenant's data.

    Fallback rules:
    - Superadmin without the header → 400 (must pick a dept explicitly).
    - Non-superadmin without the header → fall back to the user's oldest
      membership (deterministic). If the user has zero memberships → 403.

    Returns an :class:`ActiveDepartment` containing the dept + the caller's
    role in it (synthesised as ``"dept_lead"`` for superadmin overrides).
    """

    header_value = request.headers.get(_ACTIVE_DEPARTMENT_HEADER)

    if not header_value:
        if current_user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Active department required: superadmin must set the "
                    f"{_ACTIVE_DEPARTMENT_HEADER} header explicitly."
                ),
            )
        # Non-superadmin: fall back to oldest membership.
        result = await session.execute(
            select(UserDepartment, Department)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(UserDepartment.user_id == current_user.id)
            .order_by(UserDepartment.created_at.asc())
            .limit(1)
        )
        row = result.first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no department memberships",
            )
        membership, department = row
        return ActiveDepartment(
            department=department,
            role=cast(RoleLiteral, membership.role),
        )

    # Header supplied: resolve the department by id and verify membership.
    dept_result = await session.execute(
        select(Department).where(Department.id == header_value)
    )
    department = dept_result.scalar_one_or_none()
    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active department not found",
        )

    membership_result = await session.execute(
        select(UserDepartment).where(
            UserDepartment.user_id == current_user.id,
            UserDepartment.department_id == department.id,
        )
    )
    membership = membership_result.scalar_one_or_none()

    if membership is None:
        if current_user.is_superadmin:
            # Superadmin acts as dept_lead in any department even without a
            # real membership row.
            return ActiveDepartment(
                department=department,
                role="dept_lead",
                is_superadmin_override=True,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this department",
        )

    return ActiveDepartment(
        department=department,
        role=cast(RoleLiteral, membership.role),
    )


def require_role(
    *allowed: RoleLiteral,
) -> Callable[[ActiveDepartment], ActiveDepartment]:
    """Dependency factory enforcing the caller's role in the active dept.

    Usage::

        @router.post(
            "/something",
            dependencies=[Depends(require_role("dept_lead"))],
        )
        async def handler(...): ...

    Superadmin (via :attr:`ActiveDepartment.is_superadmin_override`) always
    passes regardless of ``allowed`` — system-wide admin overrides any per-
    dept role check.
    """

    if not allowed:
        raise ValueError("require_role() needs at least one allowed role")
    for role in allowed:
        if role not in _VALID_ROLES:
            raise ValueError(
                f"Unknown role {role!r}; expected one of {sorted(_VALID_ROLES)}"
            )
    allowed_set: frozenset[str] = frozenset(allowed)

    def _dep(
        ad: ActiveDepartment = Depends(get_active_department),
    ) -> ActiveDepartment:
        if ad.is_superadmin_override:
            return ad
        if ad.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role {ad.role!r} not permitted; requires one of "
                    f"{sorted(allowed_set)}"
                ),
            )
        return ad

    return _dep


__all__ = [
    "ActiveDepartment",
    "dispose_engine",
    "get_active_department",
    "get_current_user",
    "get_session",
    "get_web_dist_dir",
    "require_role",
]
