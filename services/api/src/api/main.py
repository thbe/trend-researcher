"""FastAPI app entrypoint for the api service.

Exposes two routes in Phase 3:
- ``GET /healthz`` — liveness + DB ping (operational)
- ``GET /runs`` — last N ``crawl_runs`` rows newest-first (operational)

Phase 4 will add the topic-read product API on top of this same app
(see ``services/api/src/api/routes/`` for where new routers will land).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.dependencies import dispose_engine
from api.routes import healthz as healthz_routes
from api.routes import runs as runs_routes


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Lifespan handler: nothing to warm up; dispose engine on shutdown."""

    yield
    await dispose_engine()


app = FastAPI(
    title="Trend Researcher API",
    version="0.1.0",
    lifespan=_lifespan,
)

app.include_router(healthz_routes.router, prefix="/api")
app.include_router(runs_routes.router, prefix="/api")


__all__ = ["app"]
