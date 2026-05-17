"""DB-free tests for POST /api/internal/crawl (sync execution).

Patch ``api.routes.internal._run_crawl_isolated`` with a fake so the crawler
dep graph never actually executes. Asserts:
  - happy path: returns 200 with merged status + stats body
  - slow handler returns within reasonable wall-clock
  - exception inside the wrapper bubbles up as 500 (Cloud Scheduler will
    retry on 5xx, which is what we want)
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
async def test_returns_200_with_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: 200 + merged status/stats body."""

    monkeypatch.setenv("TREND_INTERNAL_PAT", _PAT)
    calls: list[int] = []

    async def _fake() -> dict:
        calls.append(1)
        return {"crawl_run_id": "fake-run-1", "totals": {"inserted": 3, "updated": 1}}

    monkeypatch.setattr(internal_routes, "_run_crawl_isolated", _fake)

    resp = await _post_crawl(_make_app())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["crawl_run_id"] == "fake-run-1"
    assert body["totals"] == {"inserted": 3, "updated": 1}
    assert calls == [1]


@pytest.mark.asyncio
async def test_sync_handler_waits_for_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Response only comes back after the crawl coroutine finishes."""

    monkeypatch.setenv("TREND_INTERNAL_PAT", _PAT)

    async def _slow() -> dict:
        await asyncio.sleep(0.05)
        return {"crawl_run_id": "slow-1", "totals": {}}

    monkeypatch.setattr(internal_routes, "_run_crawl_isolated", _slow)

    t0 = time.perf_counter()
    resp = await _post_crawl(_make_app())
    elapsed = time.perf_counter() - t0
    assert resp.status_code == 200
    # Sync handler MUST have waited for the 50ms sleep.
    assert elapsed >= 0.05
    # And still well under a second.
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_returns_500_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the crawl wrapper raises, the endpoint returns 500.

    Cloud Scheduler retries on 5xx, which is the behavior we want for
    transient crawl failures.
    """

    monkeypatch.setenv("TREND_INTERNAL_PAT", _PAT)

    async def _boom() -> dict:
        raise RuntimeError("boom from crawl")

    monkeypatch.setattr(internal_routes, "_run_crawl_isolated", _boom)

    resp = await _post_crawl(_make_app())
    assert resp.status_code == 500
    assert "boom" in resp.json()["detail"]
