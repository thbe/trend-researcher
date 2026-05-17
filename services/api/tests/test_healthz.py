"""Tests for ``GET /healthz``.

Two cases that exercise the binary semantic of the endpoint:

1. **Reachable**: with a live ``TEST_DATABASE_URL`` Postgres, the endpoint
   returns 200 + ``{status:ok, db:reachable}``. Skip-gated.
2. **Unreachable**: monkeypatch ``api.dependencies.get_session`` to raise a
   ``DBAPIError`` so we exercise the error path without needing a broken
   Postgres on hand. Asserts 503 + ``{status:degraded, db:unreachable}``.

Approach 2 patches the FastAPI dependency override map (``app.dependency_
overrides``) which is the canonical way to inject failures from tests.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.exc import DBAPIError

from api.dependencies import get_session
from api.main import app

from .conftest import db_available


@pytest.mark.skipif(
    not db_available(),
    reason="set TEST_DATABASE_URL to a reachable Postgres to run this test",
)
async def test_healthz_ok_when_db_reachable(client, monkeypatch):
    """Live DB → 200 + ok/reachable."""

    # Point lazy DI at the test DB by overriding the configured DSN.
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    # Force engine rebuild so the new DSN is picked up.
    from api import dependencies as deps

    deps._engine = None
    deps._sessionmaker = None

    response = await client.get("/api/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "reachable"}


async def test_healthz_503_when_db_unreachable(client):
    """``session.execute('SELECT 1')`` raises DBAPIError → 503 + degraded/unreachable.

    We override ``get_session`` to yield a stub whose ``.execute(...)`` raises.
    Raising inside the dependency itself would surface as a 500 (FastAPI
    re-raises), which is the wrong contract — the route's ``try/except`` must
    catch the failure on the first query, which is the realistic failure mode
    for a Postgres that accepted the TCP connection but cannot serve queries.
    """

    class _BoomSession:
        async def execute(self, *_args, **_kwargs):
            raise DBAPIError("SELECT 1", params=None, orig=Exception("no db"))

    async def _override():
        yield _BoomSession()

    app.dependency_overrides[get_session] = _override
    try:
        response = await client.get("/api/healthz")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "unreachable"}


async def test_unprefixed_path_returns_404(client):
    """Phase 4 G2 regression pin: bare ``/healthz`` must 404 — prefix moved to ``/api``."""

    response = await client.get("/healthz")
    assert response.status_code == 404
