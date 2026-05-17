"""PAT (Personal Access Token) bearer-auth dependency for internal endpoints.

Used by /api/internal/crawl. Token lives in env var TREND_INTERNAL_PAT,
sourced from GCP Secret Manager in prod (Cloud Run --set-secrets) and from
a gitignored .env file in local dev.

Fail-closed semantics:
  - env unset or empty            -> 503 (service not configured)
  - Authorization header missing  -> 401
  - wrong scheme                  -> 401
  - token does not match          -> 403

Constant-time compare via hmac.compare_digest — no timing pivot.
"""
from __future__ import annotations

import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

_ENV_VAR = "TREND_INTERNAL_PAT"


def _get_configured_pat() -> str | None:
    raw = os.environ.get(_ENV_VAR)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


async def require_pat(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Raise HTTPException unless the request carries the configured PAT."""

    configured = _get_configured_pat()
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="internal-endpoint disabled: TREND_INTERNAL_PAT not configured",
        )
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="bearer scheme required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(creds.credentials.encode(), configured.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid token",
        )


__all__ = ["require_pat"]
