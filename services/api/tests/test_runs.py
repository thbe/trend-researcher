"""Tests for ``GET /runs``.

Three concerns this endpoint owes the operator (per Phase 3 CONTEXT.md):

1. **Newest-first ordering** — paging always wants the recent tail of the
   run-history table. Skip-gated; seeds 5 rows with monotonic
   ``started_at`` and asserts the response is descending.
2. **Default page size** — 20 unless ``?limit`` is set. Skip-gated (needs
   the seeded rows so the response actually contains a ``limit`` echo;
   could run without DB but the integration check is the more meaningful
   one).
3. **Range validation** — ``?limit=0`` and ``?limit=101`` both 422 from
   FastAPI's ``Query(ge=1, le=100)``. No DB needed.

The seeded rows are deleted in fixture teardown so the test is isolated
from any other crawl_runs already in the test DB.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, text

import core
from api import dependencies as deps
from core.models import CrawlRun

from .conftest import db_available


@pytest_asyncio.fixture
async def seeded_runs(monkeypatch):
    """Insert 5 crawl_runs with monotonically-increasing started_at; clean up."""

    if not db_available():
        pytest.skip("set TEST_DATABASE_URL to a reachable Postgres to run this test")

    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    deps._engine = None
    deps._sessionmaker = None

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    base = datetime.now(UTC).replace(microsecond=0)
    inserted_ids: list[str] = []
    async with sessionmaker() as session:
        # pgcrypto for gen_random_uuid() server-default; harmless if already there.
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await session.execute(text("CREATE TABLE IF NOT EXISTS crawl_runs ("
            "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
            "started_at timestamptz NOT NULL, "
            "finished_at timestamptz NOT NULL, "
            "duration_ms integer NOT NULL, "
            "top_n integer NOT NULL, "
            "totals_fetched integer NOT NULL DEFAULT 0, "
            "totals_inserted integer NOT NULL DEFAULT 0, "
            "totals_updated integer NOT NULL DEFAULT 0, "
            "totals_skipped_within_run integer NOT NULL DEFAULT 0, "
            "totals_errors integer NOT NULL DEFAULT 0, "
            "per_source jsonb NOT NULL DEFAULT '{}'::jsonb, "
            "failed_sources text[] NOT NULL DEFAULT '{}'::text[], "
            "created_at timestamptz NOT NULL DEFAULT now()"
            ")"))
        for i in range(5):
            row_id = str(uuid.uuid4())
            inserted_ids.append(row_id)
            session.add(CrawlRun(
                id=row_id,
                started_at=base + timedelta(seconds=i),
                finished_at=base + timedelta(seconds=i, milliseconds=500),
                duration_ms=500,
                top_n=10,
                totals_fetched=10,
                totals_inserted=10,
                totals_updated=0,
                totals_skipped_within_run=0,
                totals_errors=0,
                per_source={"hackernews": {"fetched": 10, "inserted": 10, "updated": 0, "skipped_within_run": 0, "errors": 0}},
                failed_sources=[],
            ))
        await session.commit()

    yield inserted_ids

    async with sessionmaker() as session:
        await session.execute(delete(CrawlRun).where(CrawlRun.id.in_(inserted_ids)))
        await session.commit()
    await engine.dispose()
    deps._engine = None
    deps._sessionmaker = None


async def test_runs_returns_newest_first(client, seeded_runs):
    """5 monotonically-increasing rows → response newest-first."""

    response = await client.get("/api/runs?limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5
    assert len(body["runs"]) == 5
    started = [r["started_at"] for r in body["runs"]]
    assert started == sorted(started, reverse=True), "expected newest-first"


async def test_runs_default_limit_20(client, seeded_runs):
    """No ``?limit`` → response.limit == 20."""

    response = await client.get("/api/runs")

    assert response.status_code == 200
    assert response.json()["limit"] == 20


@pytest.mark.parametrize("bad_limit", [0, 101, -1])
async def test_runs_rejects_out_of_range_limit(client, bad_limit):
    """``?limit`` outside [1, 100] → 422 (no DB needed).

    FastAPI param-validation runs as part of dependency solving, so we
    override ``get_session`` to a no-op stub to keep the engine from being
    built (no ``DATABASE_URL`` in the test environment).
    """

    from api.dependencies import get_session
    from api.main import app

    async def _noop_session():
        yield None

    app.dependency_overrides[get_session] = _noop_session
    try:
        response = await client.get(f"/api/runs?limit={bad_limit}")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 422


async def test_unprefixed_path_returns_404(client):
    """Phase 4 G2 regression pin: bare ``/runs`` must 404 — prefix moved to ``/api``."""

    response = await client.get("/runs")
    assert response.status_code == 404
