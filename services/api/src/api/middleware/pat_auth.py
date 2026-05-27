"""PAT (Personal Access Token) bearer-auth dependencies for internal endpoints.

Two flavours:

1. :func:`require_pat` — validates the bearer against the global
   ``TREND_INTERNAL_PAT`` env var (sourced from GCP Secret Manager in prod
   via Cloud Run ``--set-secrets``, .env in dev). Protects the legacy
   ``POST /api/internal/crawl`` route used by Cloud Scheduler.

2. :func:`require_dept_pat` — validates the bearer against
   ``department_pats.token_hash`` (SHA-256 hex of the plaintext). Protects
   the per-department ``POST /api/internal/departments/{slug}/crawl``
   route introduced in plan 10-02 T09. Returns the resolved
   ``(Department, DepartmentPAT)`` pair so the route can verify the slug
   match. Bumps ``last_used_at`` on every successful auth.

Fail-closed semantics for both:
  - Authorization header missing  -> 401
  - wrong scheme                  -> 401
  - token does not match          -> 403

``require_pat`` additionally returns 503 if the env secret is unset.

``require_pat`` uses ``hmac.compare_digest`` for constant-time compare. The
dept PAT path uses a hash lookup (the stored value is already a digest, so
DB index lookup leaks no more than the existence of any other row).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update as _sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from core.models import Department, DepartmentPAT

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
    """Raise HTTPException unless the request carries the configured global PAT."""

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


def hash_pat_token(plaintext: str) -> str:
    """SHA-256 hex of a plaintext bearer token (lower-case)."""

    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def require_dept_pat(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> tuple[Department, DepartmentPAT]:
    """Resolve the bearer to an active ``DepartmentPAT`` + its ``Department``.

    Returns the pair so callers can match against the route's path slug.
    Updates ``last_used_at`` on every successful auth (best-effort commit).
    """

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

    token_hash = hash_pat_token(creds.credentials)
    stmt = (
        select(DepartmentPAT, Department)
        .join(Department, Department.id == DepartmentPAT.department_id)
        .where(
            DepartmentPAT.token_hash == token_hash,
            DepartmentPAT.revoked_at.is_(None),
        )
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid token",
        )
    pat, dept = row
    await session.execute(
        _sql_update(DepartmentPAT)
        .where(DepartmentPAT.id == pat.id)
        .values(last_used_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return dept, pat


__all__ = ["require_pat", "require_dept_pat", "hash_pat_token"]
