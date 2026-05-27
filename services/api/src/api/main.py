"""FastAPI app entrypoint for the api service.

Exposes three operational/product routes:
- ``GET /api/healthz`` — liveness + DB ping (operational)
- ``GET /api/runs`` — last N ``crawl_runs`` rows newest-first (operational)
- ``GET /api/topics`` — paginated topic list w/ derived stats (product, Phase 4)
- ``POST /api/login`` — authenticate and set session cookie (v0.5.2)

All routes are under ``/api/*`` (CONTEXT G2) so the SPA catch-all at ``/``
(mounted below via StaticFiles when ``WEB_DIST_DIR`` is set) doesn't swallow
them. Order matters: ``/api/*`` routers first, dump-debouncer middleware in
between, StaticFiles mount LAST.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

import core
from api.auth.middleware import AuthMiddleware
from api.auth.seed import ensure_seed_user
from api.dependencies import dispose_engine, get_web_dist_dir
from api.middleware.dump_debouncer import (
    DumpDebouncerMiddleware,
    build_dump_debouncer,
)
from api.routes import healthz as healthz_routes
from api.routes import internal as internal_routes
from api.routes import runs as runs_routes
from api.routes import topics as topics_routes
from api.routes import auth as auth_routes
from api.routes import crawl_config as crawl_config_routes
from api.routes import assessment as assessment_routes
from api.routes import ai_config as ai_config_routes
from api.routes import dashboard as dashboard_routes
from api.routes import departments as departments_routes
from api.routes import department_pats as department_pats_routes
from api.routes import department_sources as department_sources_routes


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Lifespan handler: seed user on startup; dispose engine on shutdown."""

    # Seed the configured user into the users table
    settings = core.get_settings()
    engine = core.get_engine(settings.database_url)
    session_factory = core.get_sessionmaker(engine)
    async with session_factory() as session:
        await ensure_seed_user(
            session,
            username=settings.auth_seed_username,
            password=settings.auth_seed_password,
        )
    await engine.dispose()

    yield
    await dispose_engine()


app = FastAPI(
    title="Trend Researcher API",
    version="0.1.0",
    lifespan=_lifespan,
)

app.include_router(healthz_routes.router, prefix="/api")
app.include_router(auth_routes.router, prefix="/api")
app.include_router(runs_routes.router, prefix="/api")
app.include_router(topics_routes.router, prefix="/api")
app.include_router(crawl_config_routes.router, prefix="/api")
app.include_router(assessment_routes.router, prefix="/api")
app.include_router(ai_config_routes.router, prefix="/api")
app.include_router(dashboard_routes.router, prefix="/api")
app.include_router(departments_routes.router, prefix="/api")
app.include_router(department_pats_routes.router, prefix="/api")
app.include_router(department_sources_routes.router, prefix="/api")
app.include_router(internal_routes.router, prefix="/api")

# Auth middleware: protects all /api/* except /api/login and /api/healthz
_settings = core.get_settings()
app.add_middleware(AuthMiddleware, secret_key=_settings.auth_secret_key)

# Register the post-write debouncer when DB_DUMP_SCRIPT is configured (prod
# container). Local dev / pytest leaves it unset, so no subprocess fires.
_debouncer = build_dump_debouncer()
if _debouncer is not None:
    app.add_middleware(DumpDebouncerMiddleware, debouncer=_debouncer)

# Mount the SPA LAST so ``/api/*`` routers always win. Custom subclass
# serves index.html for any path that doesn't match a real static file,
# which is what Vue Router's HTML5 history mode expects.
_web_dist = get_web_dist_dir()
if _web_dist is not None:
    class _SPAStaticFiles(StaticFiles):
        """StaticFiles that falls back to index.html for SPA routes."""

        async def get_response(self, path: str, scope):  # type: ignore[override]
            try:
                response = await super().get_response(path, scope)
                if response.status_code == 404:
                    return FileResponse(str(_web_dist / "index.html"), media_type="text/html")
                return response
            except Exception:
                return FileResponse(str(_web_dist / "index.html"), media_type="text/html")

    app.mount("/", _SPAStaticFiles(directory=str(_web_dist), html=True), name="spa")


__all__ = ["app"]
