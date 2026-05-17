"""Tests for ``GET /api/topics`` (CONTEXT G5 contract).

Ten concerns this endpoint owes consumers:

1. Empty list → ``{topics: [], limit, sort}`` (no DB rows → still 200).
2. Default sort ``-last_seen_at`` orders newest-first.
3. Sort ``-breadth`` orders by distinct source count desc.
4. Sort ``-longevity`` orders by ``EXTRACT(EPOCH FROM (last_seen_at - first_seen_at))::bigint`` desc.
5. ``?limit=0`` → 422 (FastAPI ``ge=1``).
6. ``?limit=101`` → 422 (FastAPI ``le=100``).
7. ``?sort=unknown`` → 400 with helpful detail (CONTEXT G5).
8. List rows must NOT carry a nested ``sources`` field (deferred to detail in 04-03).
9. List rows must NOT carry a ``topic_metadata`` field (deferred to detail in 04-03).
10. Response ``sort`` echoes back exactly what was sent (including leading ``-``).

DB-touching tests skip-gate on ``TEST_DATABASE_URL``; pure 422/400 cases run
without DB by stubbing the session dependency (same pattern as test_runs).
The seeded rows + the ``v_topic_stats`` view are created in-fixture (the
view DDL is sourced from the 0003 migration so this stays single-sourced
with the migration that ships).
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

import core
from api import dependencies as deps
from core.models import Base, Topic, TopicSource

from .conftest import db_available


# Single-source the view DDL with the Alembic migration (same trick as
# packages/core/tests/conftest.py). Avoids drift between test setup and
# the migration that ships.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "core"
    / "alembic"
    / "versions"
    / "0003_topic_stats_view.py"
)


def _load_view_sql() -> tuple[str, str]:
    spec = importlib.util.spec_from_file_location("_m0003", _MIGRATION_PATH)
    assert spec and spec.loader, f"could not load {_MIGRATION_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._CREATE_VIEW_SQL, module._DROP_VIEW_SQL


@pytest_asyncio.fixture
async def seeded_topics(monkeypatch):
    """Insert 3 topics with controlled timestamps + source counts; clean up.

    Topic A: 1 source (``hackernews``), span = 10s
    Topic B: 2 sources (``hackernews``, ``nyt_homepage``), span = 100s
    Topic C: 3 sources (``hackernews``, ``nyt_homepage``, ``reddit``), span = 1000s

    Expected breadth ordering desc: C, B, A
    Expected longevity ordering desc: C, B, A
    """

    if not db_available():
        pytest.skip("set TEST_DATABASE_URL to a reachable Postgres to run this test")

    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    deps._engine = None
    deps._sessionmaker = None

    create_view_sql, drop_view_sql = _load_view_sql()

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.execute(text(drop_view_sql))  # idempotent prior-run cleanup
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(create_view_sql))

    base = datetime.now(UTC).replace(microsecond=0)
    topic_specs = [
        ("A", base, base + timedelta(seconds=10), ["hackernews"]),
        ("B", base, base + timedelta(seconds=100), ["hackernews", "nyt_homepage"]),
        ("C", base, base + timedelta(seconds=1000), ["hackernews", "nyt_homepage", "reddit"]),
    ]

    inserted_topic_ids: list[str] = []
    async with sessionmaker() as session:
        for label, first_seen, last_seen, sources in topic_specs:
            topic_id = str(uuid.uuid4())
            inserted_topic_ids.append(topic_id)
            session.add(
                Topic(
                    id=topic_id,
                    title=f"Topic {label}",
                    description=f"Seeded test topic {label}",
                    first_seen_at=first_seen,
                    last_seen_at=last_seen,
                    observation_count=len(sources),
                )
            )
            await session.flush()
            for src in sources:
                session.add(
                    TopicSource(
                        topic_id=topic_id,
                        source_name=src,
                        url=f"https://{src}.example/{label.lower()}",
                        observed_at=last_seen,
                    )
                )
        await session.commit()

    yield inserted_topic_ids

    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE topic_sources, topics RESTART IDENTITY CASCADE")
        )
        await conn.execute(text(drop_view_sql))
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    deps._engine = None
    deps._sessionmaker = None


# ---------- DB-free tests (Query validation + sort whitelist) ----------


@pytest.fixture
def _noop_session_override():
    """Override get_session with a stub so 400/422 tests don't need a DB."""

    from api.dependencies import get_session
    from api.main import app

    async def _stub():
        yield None

    app.dependency_overrides[get_session] = _stub
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.parametrize("bad_limit", [0, 101, -1])
async def test_topics_rejects_out_of_range_limit(client, _noop_session_override, bad_limit):
    """``?limit`` outside [1, 100] → 422 (FastAPI Query validation)."""

    response = await client.get(f"/api/topics?limit={bad_limit}")
    assert response.status_code == 422


async def test_topics_rejects_unknown_sort_key(client, _noop_session_override):
    """``?sort=unknown`` → 400 with helpful detail listing allowed keys (G5)."""

    response = await client.get("/api/topics?sort=unknown")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "breadth" in detail and "longevity" in detail and "last_seen_at" in detail


async def test_topics_rejects_unknown_sort_key_with_minus_prefix(
    client, _noop_session_override
):
    """``?sort=-bogus`` → 400 — minus prefix doesn't bypass the whitelist."""

    response = await client.get("/api/topics?sort=-bogus")
    assert response.status_code == 400


# ---------- DB-backed tests (seeded fixture) ----------


async def test_topics_empty_list_returns_200(client, monkeypatch):
    """No seeded rows → 200 with empty list and echoed envelope."""

    if not db_available():
        pytest.skip("set TEST_DATABASE_URL to a reachable Postgres to run this test")

    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    deps._engine = None
    deps._sessionmaker = None

    create_view_sql, drop_view_sql = _load_view_sql()
    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.execute(text(drop_view_sql))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(create_view_sql))
        await conn.execute(text("TRUNCATE topic_sources, topics RESTART IDENTITY CASCADE"))

    try:
        response = await client.get("/api/topics")
        assert response.status_code == 200
        body = response.json()
        assert body == {"topics": [], "limit": 20, "sort": "-last_seen_at"}
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(drop_view_sql))
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
        deps._engine = None
        deps._sessionmaker = None


async def test_topics_default_sort_is_last_seen_at_desc(client, seeded_topics):
    """Default ``-last_seen_at`` → C, B, A (C has latest last_seen_at)."""

    response = await client.get("/api/topics")
    assert response.status_code == 200
    body = response.json()
    titles = [t["title"] for t in body["topics"]]
    assert titles == ["Topic C", "Topic B", "Topic A"]
    assert body["sort"] == "-last_seen_at"
    assert body["limit"] == 20


async def test_topics_sort_by_breadth_desc(client, seeded_topics):
    """``?sort=-breadth`` → C (3 sources), B (2), A (1)."""

    response = await client.get("/api/topics?sort=-breadth")
    assert response.status_code == 200
    body = response.json()
    titles = [t["title"] for t in body["topics"]]
    assert titles == ["Topic C", "Topic B", "Topic A"]
    breadths = [t["breadth"] for t in body["topics"]]
    assert breadths == [3, 2, 1]


async def test_topics_sort_by_longevity_desc(client, seeded_topics):
    """``?sort=-longevity`` → C (1000s), B (100s), A (10s)."""

    response = await client.get("/api/topics?sort=-longevity")
    assert response.status_code == 200
    body = response.json()
    titles = [t["title"] for t in body["topics"]]
    assert titles == ["Topic C", "Topic B", "Topic A"]
    longevities = [t["longevity_seconds"] for t in body["topics"]]
    assert longevities == [1000, 100, 10]
    # Sanity: bigint, not float
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in longevities)


async def test_topics_list_rows_have_no_nested_sources(client, seeded_topics):
    """G5: list shape must not include ``sources`` (deferred to detail in 04-03)."""

    response = await client.get("/api/topics")
    assert response.status_code == 200
    for row in response.json()["topics"]:
        assert "sources" not in row


async def test_topics_list_rows_have_no_topic_metadata(client, seeded_topics):
    """G5: list shape must not include ``topic_metadata`` (deferred to detail in 04-03)."""

    response = await client.get("/api/topics")
    assert response.status_code == 200
    for row in response.json()["topics"]:
        assert "topic_metadata" not in row
        assert "metadata" not in row


async def test_topics_sort_echoed_verbatim(client, seeded_topics):
    """Validated sort param round-trips (with leading ``-``)."""

    response = await client.get("/api/topics?sort=-breadth")
    assert response.json()["sort"] == "-breadth"

    response = await client.get("/api/topics?sort=breadth")
    assert response.json()["sort"] == "breadth"
