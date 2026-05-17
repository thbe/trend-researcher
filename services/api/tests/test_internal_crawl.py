"""DB-free tests for POST /api/internal/crawl.

Patch ``api.routes.internal._run_crawl_isolated`` with a recorder so the
crawler dep graph never actually executes. Asserts:
  - background task is invoked exactly once with no args
  - response returns 202 within <500ms even if the task sleeps
  - exceptions raised inside the bg task do not bubble to the client
    (the route owns the try/except in _run_crawl_isolated; here we
    confirm the route still returned 202 even though the task ran)
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes import internal as internal_routes

_PAT = "test-pat-value"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(internal_routes.router, prefix="/api")
    return app


async def _post_crawl(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post(
            "/api/internal/crawl", headers={"Authorization": f"Bearer {_PAT}"}
        )


@pytest.mark.asyncio
async def test_invokes_background_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hitting the endpoint schedules _run_crawl_isolated exactly once."""

    monkeypatch.setenv("TREND_INTERNAL_PAT", _PAT)
    calls: list[int] = []

    async def _fake() -> None:
        calls.append(1)

    monkeypatch.setattr(internal_routes, "_run_crawl_isolated", _fake)

    resp = await _post_crawl(_make_app())
    assert resp.status_code == 202
    assert resp.json() == {"status": "queued"}
    # BackgroundTasks runs after response is sent; httpx ASGITransport awaits it.
    assert calls == [1]


@pytest.mark.asyncio
async def test_returns_immediately_even_if_task_slow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Response is 202; total roundtrip well under 1s even though bg sleeps."""

    monkeypatch.setenv("TREND_INTERNAL_PAT", _PAT)

    async def _slow() -> None:
        await asyncio.sleep(0.05)

    monkeypatch.setattr(internal_routes, "_run_crawl_isolated", _slow)

    t0 = time.perf_counter()
    resp = await _post_crawl(_make_app())
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 202
    # 500ms is generous; the bg task only sleeps 50ms.
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_swallows_task_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real _run_crawl_isolated wrapper must swallow inner failures.

    We let the real wrapper run but force ``build_repository`` to raise.
    The wrapper's try/except logs and swallows; the route had already
    returned 202 before the bg task ran, so the client sees 202 either
    way — but a leaking exception would surface as a test framework
    error from Starlette's BackgroundTasks runner.
    """

    monkeypatch.setenv("TREND_INTERNAL_PAT", _PAT)

    # Patch the lazy imports inside _run_crawl_isolated. We can't monkeypatch
    # crawler.app.composition before it's imported, so install a fake module
    # in sys.modules and let the function's `from crawler...` pick it up.
    import sys
    import types

    fake_composition = types.ModuleType("crawler.app.composition")

    def _boom_build_sources():
        return []

    def _boom_build_repository():
        raise RuntimeError("boom from build_repository")

    fake_composition.build_sources = _boom_build_sources
    fake_composition.build_repository = _boom_build_repository

    fake_orchestrator = types.ModuleType("crawler.app.orchestrator")

    async def _noop_run_once(*_args, **_kwargs):  # pragma: no cover
        return {}

    fake_orchestrator.run_once = _noop_run_once

    monkeypatch.setitem(sys.modules, "crawler.app.composition", fake_composition)
    monkeypatch.setitem(sys.modules, "crawler.app.orchestrator", fake_orchestrator)

    resp = await _post_crawl(_make_app())
    assert resp.status_code == 202
