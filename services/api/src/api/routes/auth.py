"""Auth API routes — POST /api/login, POST /api/logout, GET /api/me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from api.auth import normalize_username, verify_password
from api.auth.middleware import COOKIE_NAME, create_session_cookie
from api.dependencies import get_session
from api.schemas import LoginDepartment, LoginResponse
from core import get_settings
from core.models import Department, User, UserDepartment

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


async def _resolve_login_payload(
    user: User, session: AsyncSession
) -> LoginResponse:
    """Build the full LoginResponse payload for ``user`` from fresh DB state.

    Shared by ``/api/login`` and ``/api/me`` so the SPA can refresh its
    session cache (departments, role memberships, superadmin flag) without
    a re-login whenever the server state changes (eg. an admin creates a
    new department or grants a role).
    """
    if user.is_superadmin:
        # Superadmin sees ALL departments with a synthesised dept_lead role.
        dept_rows = (
            await session.execute(select(Department).order_by(Department.created_at))
        ).scalars().all()
        departments = [
            LoginDepartment(id=d.id, name=d.name, slug=d.slug, role="dept_lead")
            for d in dept_rows
        ]
    else:
        membership_rows = (
            await session.execute(
                select(UserDepartment, Department)
                .join(Department, Department.id == UserDepartment.department_id)
                .where(UserDepartment.user_id == user.id)
                .order_by(Department.created_at)
            )
        ).all()
        departments = [
            LoginDepartment(id=d.id, name=d.name, slug=d.slug, role=ud.role)
            for ud, d in membership_rows
        ]

    return LoginResponse(
        ok=True,
        username=user.username,
        is_superadmin=user.is_superadmin,
        departments=departments,
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Authenticate user and set signed session cookie."""
    username = normalize_username(body.username)
    result = await session.execute(
        select(User).where(User.username == username, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        return JSONResponse(
            {"detail": "Invalid username or password"}, status_code=401
        )

    settings = get_settings()
    cookie_value = create_session_cookie(
        username=user.username,
        secret=settings.auth_secret_key,
        ttl_hours=settings.auth_session_ttl_hours,
    )

    # Phase 10: include departments + superadmin flag so SPA can populate
    # the department switcher without a follow-up roundtrip.
    payload = await _resolve_login_payload(user, session)
    response = JSONResponse(payload.model_dump(mode="json"))
    response.set_cookie(
        key=COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        samesite="strict",
        max_age=settings.auth_session_ttl_hours * 3600,
        path="/",
    )
    return response


@router.post("/logout")
async def logout() -> JSONResponse:
    """Clear session cookie."""
    response = JSONResponse({"ok": True})
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response


@router.get("/me")
async def me(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Return the current user's session payload (full LoginResponse shape).

    Used by the SPA both as a cookie liveness probe (legacy) and as the
    authoritative source for session state on hydrate/refresh. Re-reads
    departments + role memberships from the DB on every call so the SPA
    self-heals after admin mutations (eg. creating a department, granting
    a role) without requiring the user to log out and back in.

    The auth middleware has already validated the cookie before reaching
    this handler and stored the username on ``request.state.user``. If
    the cookie referenced a user that has since been deleted/deactivated,
    we return 401 so the SPA bounces to /login.
    """
    username = getattr(request.state, "user", None)
    if not username:
        # Middleware should have rejected this already; defensive 401.
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    result = await session.execute(
        select(User).where(User.username == username, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        return JSONResponse(
            {"detail": "Session user no longer exists"}, status_code=401
        )

    payload = await _resolve_login_payload(user, session)
    return JSONResponse(payload.model_dump(mode="json"))


__all__ = ["router"]
