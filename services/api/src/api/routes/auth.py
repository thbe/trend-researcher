"""Login API route — POST /api/login."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from api.auth import verify_password
from api.auth.middleware import COOKIE_NAME, create_session_cookie
from api.dependencies import get_session
from core import get_settings
from core.models import User

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Authenticate user and set signed session cookie."""
    result = await session.execute(
        select(User).where(User.username == body.username, User.is_active.is_(True))
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

    response = JSONResponse({"ok": True, "username": user.username})
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
async def me() -> JSONResponse:
    """Return 200 if session is valid (used by SPA auth guard).

    The middleware already validates the cookie — if we reach here, it's valid.
    """
    return JSONResponse({"ok": True})


__all__ = ["router"]
