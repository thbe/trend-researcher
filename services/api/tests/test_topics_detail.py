"""Tests for ``GET /api/topics/{id}`` (CONTEXT G7 contract).

Eight concerns this endpoint owes consumers:

1. Existing topic → 200 with full 10-field detail payload + correct breadth.
2. Non-existent UUID → 404 with detail starting "Topic ".
3. Malformed UUID → 422 (FastAPI Path UUID validation, no handler invocation).
4. ``sources`` array ordered ``observed_at DESC`` (newest first).
5. Topic with no sources → 200 with ``sources == []`` and ``breadth == 0``.
6. ``topic_metadata`` dict round-trips verbatim.
7. ``raw_payload`` is NEVER present in the source projection (lean per G7).
8. ``longevity_seconds`` matches ``v_topic_stats`` view exactly.

DB-touching tests skip-gate on ``TEST_DATABASE_URL``; the malformed-UUID case
is DB-free (FastAPI rejects before the handler / session dependency runs).
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
async def _db_setup(monkeypatch):
    """Create extension + view + tables; tear them down. Yields (engine, sessionmaker)."""

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
        await conn.execute(text(drop_view_sql))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(create_view_sql))

    yield engine, sessionmaker

    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE topic_sources, topics RESTART IDENTITY CASCADE")
        )
        await conn.execute(text(drop_view_sql))
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    deps._engine = None
    deps._sessionmaker = None


async def _insert_topic(
    sessionmaker,
    *,
    title: str = "Sample",
    description: str | None = "desc",
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
    observation_count: int = 0,
    topic_metadata: dict | None = None,
    sources: list[tuple[str, str, int, datetime, dict | None]] | None = None,
) -> str:
    """Insert one topic + N sources, return topic_id as str.

    Each source tuple: ``(source_name, url, native_rank, observed_at, raw_payload)``.
    """

    topic_id = str(uuid.uuid4())
    base = datetime.now(UTC).replace(microsecond=0)
    first_seen = first_seen or base
    last_seen = last_seen or base

    async with sessionmaker() as session:
        topic = Topic(
            id=topic_id,
            title=title,
            description=description,
            first_seen_at=first_seen,
            last_seen_at=last_seen,
            observation_count=observation_count,
        )
        if topic_metadata is not None:
            topic.topic_metadata = topic_metadata
        session.add(topic)
        await session.flush()
        for src_name, url, rank, observed_at, raw in sources or []:
            ts = TopicSource(
                topic_id=topic_id,
                source_name=src_name,
                url=url,
                native_rank=rank,
                observed_at=observed_at,
            )
            if raw is not None:
                ts.raw_payload = raw
            session.add(ts)
        await session.commit()
    return topic_id


# ---------- DB-free test (FastAPI Path UUID validation) ----------


async def test_malformed_uuid_returns_422(client):
    """``GET /api/topics/garbage`` → 422 (no handler invocation, no DB)."""

    response = await client.get("/api/topics/garbage")
    assert response.status_code == 422


# ---------- DB-backed tests ----------


async def test_get_existing_topic_returns_full_detail(client, _db_setup):
    _, sessionmaker = _db_setup
    base = datetime.now(UTC).replace(microsecond=0)
    topic_id = await _insert_topic(
        sessionmaker,
        title="Real Topic",
        first_seen=base,
        last_seen=base + timedelta(seconds=120),
        observation_count=2,
        sources=[
            ("hackernews", "https://hn.example/1", 1, base, None),
            ("nyt_homepage", "https://nyt.example/1", 3, base + timedelta(seconds=60), None),
        ],
    )

    response = await client.get(f"/api/topics/{topic_id}")
    assert response.status_code == 200
    body = response.json()

    expected_fields = {
        "id",
        "title",
        "description",
        "first_seen_at",
        "last_seen_at",
        "observation_count",
        "breadth",
        "longevity_seconds",
        "topic_metadata",
        "sources",
    }
    assert set(body) == expected_fields
    assert body["title"] == "Real Topic"
    assert body["breadth"] == 2
    assert len(body["sources"]) == 2


async def test_nonexistent_topic_returns_404(client, _db_setup):
    fresh_id = uuid.uuid4()
    response = await client.get(f"/api/topics/{fresh_id}")
    assert response.status_code == 404
    assert response.json()["detail"].startswith("Topic ")


async def test_sources_ordered_observed_at_desc(client, _db_setup):
    _, sessionmaker = _db_setup
    base = datetime.now(UTC).replace(microsecond=0)
    oldest = base
    middle = base + timedelta(seconds=60)
    newest = base + timedelta(seconds=120)
    topic_id = await _insert_topic(
        sessionmaker,
        first_seen=base,
        last_seen=newest,
        observation_count=3,
        sources=[
            ("src_a", "https://a.example", 1, oldest, None),
            ("src_b", "https://b.example", 2, middle, None),
            ("src_c", "https://c.example", 3, newest, None),
        ],
    )

    response = await client.get(f"/api/topics/{topic_id}")
    assert response.status_code == 200
    source_names = [s["source_name"] for s in response.json()["sources"]]
    assert source_names == ["src_c", "src_b", "src_a"]


async def test_topic_with_no_sources_returns_empty_array(client, _db_setup):
    _, sessionmaker = _db_setup
    topic_id = await _insert_topic(sessionmaker, observation_count=0, sources=[])

    response = await client.get(f"/api/topics/{topic_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert body["breadth"] == 0


async def test_response_includes_topic_metadata_dict(client, _db_setup):
    _, sessionmaker = _db_setup
    payload = {"foo": "bar", "nested": {"k": 1}}
    topic_id = await _insert_topic(sessionmaker, topic_metadata=payload)

    response = await client.get(f"/api/topics/{topic_id}")
    assert response.status_code == 200
    assert response.json()["topic_metadata"] == payload


async def test_response_omits_raw_payload(client, _db_setup):
    _, sessionmaker = _db_setup
    base = datetime.now(UTC).replace(microsecond=0)
    topic_id = await _insert_topic(
        sessionmaker,
        sources=[("hackernews", "https://hn.example", 1, base, {"secret": "leak-me-if-you-dare"})],
    )

    response = await client.get(f"/api/topics/{topic_id}")
    assert response.status_code == 200
    source = response.json()["sources"][0]
    assert "raw_payload" not in source
    # Belt-and-braces: also ensure no key leaks the payload value.
    assert "leak-me-if-you-dare" not in response.text


async def test_longevity_matches_view(client, _db_setup):
    _, sessionmaker = _db_setup
    base = datetime.now(UTC).replace(microsecond=0)
    topic_id = await _insert_topic(
        sessionmaker,
        first_seen=base,
        last_seen=base + timedelta(seconds=60),
        observation_count=1,
        sources=[("hackernews", "https://hn.example", 1, base, None)],
    )

    response = await client.get(f"/api/topics/{topic_id}")
    assert response.status_code == 200
    assert response.json()["longevity_seconds"] == 60
