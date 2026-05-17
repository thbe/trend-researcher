"""FastAPI app entrypoint for the api service.

Exposes three operational/product routes:
- ``GET /api/healthz`` — liveness + DB ping (operational)
- ``GET /api/runs`` — last N ``crawl_runs`` rows newest-first (operational)
- ``GET /api/topics`` — paginated topic list w/ derived stats (product, Phase 4)

All routes are under ``/api/*`` (CONTEXT G2) so the SPA catch-all at ``/``
(mounted in 04-05) doesn't swallow them. Router order matters: ``/api/*``
first, StaticFiles last.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.dependencies import dispose_engine
from api.routes import healthz as healthz_routes
from api.routes import runs as runs_routes
from api.routes import topics as topics_routes


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
app.include_router(topics_routes.router, prefix="/api")


__all__ = ["app"]
