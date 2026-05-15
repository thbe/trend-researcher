"""``GET /healthz`` — liveness + DB-reachability probe.

Returns 200 + ``{status: ok, db: reachable}`` when the per-request session
can execute ``SELECT 1`` against Postgres. On any ``DBAPIError`` (which
covers ``OperationalError`` for connection failures) returns 503 +
``{status: degraded, db: unreachable}``.

We deliberately catch ``DBAPIError`` (the SQLAlchemy ancestor) rather than
``OperationalError`` alone so transient driver-level failures (e.g. asyncpg
``InterfaceError``, auth errors during boot) also surface as 'degraded'
instead of leaking a 500 — the operator-facing semantic is binary
(reachable / not), nothing else belongs on this endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas import HealthzResponse

router = APIRouter()


@router.get("/healthz", response_model=HealthzResponse)
async def healthz(session: AsyncSession = Depends(get_session)) -> HealthzResponse | JSONResponse:
    """Liveness + DB ping. 200 when reachable, 503 when not."""

    try:
        await session.execute(text("SELECT 1"))
    except DBAPIError:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "unreachable"},
        )
    return HealthzResponse(status="ok", db="reachable")


__all__ = ["router"]
