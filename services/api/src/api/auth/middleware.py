"""Signed-cookie session middleware for app-level authentication.

Protects all /api/* routes EXCEPT /api/login and /api/healthz.
Returns 401 JSON for API requests without a valid session cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Paths that do NOT require authentication
_PUBLIC_PATHS = frozenset({"/api/login", "/api/healthz", "/api/logout"})

COOKIE_NAME = "tr_session"


def _sign(payload: dict[str, Any], secret: str) -> str:
    """Create a signed cookie value: base64(json) + '.' + hmac."""
    import base64

    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.HMAC(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def _verify(cookie: str, secret: str) -> dict[str, Any] | None:
    """Verify and decode a signed cookie. Returns None if invalid/expired."""
    import base64

    parts = cookie.split(".", 1)
    if len(parts) != 2:
        return None
    data, sig = parts
    expected = hmac.HMAC(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(data))
    except Exception:
        return None
    # Check expiry
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def create_session_cookie(username: str, secret: str, ttl_hours: int) -> str:
    """Create a signed session cookie value."""
    payload = {
        "sub": username,
        "exp": time.time() + ttl_hours * 3600,
    }
    return _sign(payload, secret)


class AuthMiddleware(BaseHTTPMiddleware):
    """Reject unauthenticated requests to protected API routes."""

    def __init__(self, app: Any, secret_key: str) -> None:
        super().__init__(app)
        self.secret_key = secret_key

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Allow public paths and non-API paths (SPA static files)
        if path in _PUBLIC_PATHS or not path.startswith("/api/"):
            return await call_next(request)

        # Check session cookie
        cookie = request.cookies.get(COOKIE_NAME)
        if not cookie:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401
            )

        session = _verify(cookie, self.secret_key)
        if session is None:
            return JSONResponse(
                {"detail": "Session expired or invalid"}, status_code=401
            )

        # Attach user info to request state
        request.state.user = session.get("sub")
        return await call_next(request)


__all__ = ["AuthMiddleware", "COOKIE_NAME", "create_session_cookie"]
