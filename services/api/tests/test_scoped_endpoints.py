"""Tests for Phase 10 (MT-006/MT-009) per-department endpoint scoping.

Covers the contract from ``10-02-PLAN.md`` T07: every endpoint that was
re-scoped under the active-department header must enforce membership,
filter writes/reads by ``department_id``, and refuse cross-dept access.

Test matrix (all run only when ``TEST_DATABASE_URL`` is reachable):

1. ``test_active_department_required_for_superadmin`` — superadmin without
   ``X-Active-Department`` → 400 (operator must pick explicitly).
2. ``test_active_department_403_when_not_member`` — non-superadmin asking
   for a dept they don't belong to → 403.
3. ``test_ai_config_isolation`` — PUT under Default, GET under Other → 404
   (each dept has its own row; absence is honest).
4. ``test_dashboard_counts_isolated`` — BC inserted under Default → Default
   dashboard reports it, Other dashboard reports 0.
5. ``test_topics_filtered_by_subscription`` — topic seen only via source S;
   Default subscribes (enabled=true), Other does not → topic visible to
   Default, invisible to Other.
6. ``test_breadth_is_global`` — a topic with 2 source observations carries
   ``breadth=2`` even when the active dept only subscribes to one of those
   sources (breadth is a global topic property per G5).
7. ``test_department_sources_crud`` — dept_lead PUT toggle enabled=true,
   subsequent GET reflects it; viewer cannot PUT (403).

The fixture extends :func:`seeded_db` with the ``v_topic_stats`` view (so
``/api/topics`` works against ``create_all``-only schemas) and seeds the
``crawl_config`` rows the dept-source endpoints validate against.
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
from core.models import (
    BusinessCase,
    CrawlConfig,
    DepartmentSource,
    Topic,
    TopicSource,
)

from .conftest import SeededDb, db_available


pytestmark = pytest.mark.asyncio


# Single-source the v_topic_stats DDL with the Alembic migration so the
# test schema matches what ships in prod (same trick as test_topics_list).
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "core"
    / "alembic"
    / "versions"
    / "0003_topic_stats_view.py"
)


def _load_view_sql() -> tuple[str, str]:
    spec = importlib.util.spec_from_file_location("_m0003_t07", _MIGRATION_PATH)
    assert spec and spec.loader, f"could not load {_MIGRATION_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._CREATE_VIEW_SQL, module._DROP_VIEW_SQL


@pytest_asyncio.fixture
async def scoped_db(seeded_db: SeededDb):
    """Extend :func:`seeded_db` with the topic-stats view + crawl_config seed.

    Yields the same :class:`SeededDb` handle so tests can mix dept/user IDs
    with the extra fixtures we install here. Cleanup of the view is done in
    the finally block; the underlying ``seeded_db`` fixture drops every
    table on exit so we don't TRUNCATE here.
    """

    if not db_available():
        pytest.skip("set TEST_DATABASE_URL to a reachable Postgres")

    create_view_sql, drop_view_sql = _load_view_sql()

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    async with engine.begin() as conn:
        # The view may exist from a prior partial run; drop-then-create.
        await conn.execute(text(drop_view_sql))
        await conn.execute(text(create_view_sql))

    # Seed two crawl_config sources so dept-source endpoints have something
    # to validate against. These are GLOBAL tech config (no `enabled`).
    async with sessionmaker() as session:
        session.add_all(
            [
                # default dept owns hackernews; other dept owns nyt_homepage
                # so the cross-ownership / opt-in cases are exercised.
                CrawlConfig(
                    source_name="hackernews",
                    top_n=30,
                    department_id=seeded_db.default_dept_id,
                ),
                CrawlConfig(
                    source_name="nyt_homepage",
                    top_n=20,
                    department_id=seeded_db.other_dept_id,
                ),
            ]
        )
        await session.commit()

    try:
        yield seeded_db
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(drop_view_sql))


# ---------------------------------------------------------------------------
# 1-2. Active-department dependency guards
# ---------------------------------------------------------------------------


async def test_active_department_required_for_superadmin(
    scoped_db: SeededDb, make_authed_client
) -> None:
    """Superadmin MUST pass the header explicitly (no fallback)."""

    client = await make_authed_client(scoped_db.superadmin)
    response = await client.get("/api/dashboard")
    assert response.status_code == 400


async def test_active_department_403_when_not_member(
    scoped_db: SeededDb, make_authed_client
) -> None:
    """viewer_b is NOT a member of Default → 403 on any scoped endpoint."""

    client = await make_authed_client(
        scoped_db.viewer_b, active_dept=scoped_db.default_dept_id
    )
    response = await client.get("/api/dashboard")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 3. AIConfig isolation
# ---------------------------------------------------------------------------


async def test_ai_config_isolation(
    scoped_db: SeededDb, make_authed_client
) -> None:
    """PUT under Default; GET under Other returns 404 (no shared row)."""

    lead_default = await make_authed_client(
        scoped_db.lead_a, active_dept=scoped_db.default_dept_id
    )
    put_resp = await lead_default.put(
        "/api/ai-config",
        json={"model": "qwen3.5:latest", "base_url": "http://ollama:11434"},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["model"] == "qwen3.5:latest"

    # Same identity, different dept → 404 (analyst_a is viewer of Other).
    analyst_other = await make_authed_client(
        scoped_db.analyst_a, active_dept=scoped_db.other_dept_id
    )
    get_resp = await analyst_other.get("/api/ai-config")
    assert get_resp.status_code == 404

    # Default dept still has it.
    get_default = await lead_default.get("/api/ai-config")
    assert get_default.status_code == 200
    assert get_default.json()["model"] == "qwen3.5:latest"


# ---------------------------------------------------------------------------
# 4. Dashboard isolation
# ---------------------------------------------------------------------------


async def test_dashboard_counts_isolated(
    scoped_db: SeededDb, make_authed_client
) -> None:
    """A BC under Default must not bleed into Other's dashboard counts."""

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    topic_id = str(uuid.uuid4())
    now = datetime.now(UTC).replace(microsecond=0)
    async with sessionmaker() as session:
        session.add(
            Topic(
                id=topic_id,
                title="BC-bound topic",
                first_seen_at=now,
                last_seen_at=now,
                observation_count=1,
            )
        )
        await session.flush()
        session.add(
            TopicSource(
                topic_id=topic_id,
                source_name="hackernews",
                url="https://hackernews.example/x",
                observed_at=now,
            )
        )
        session.add(
            BusinessCase(
                topic_id=topic_id,
                department_id=scoped_db.default_dept_id,
                relevance_verdict="opportunity",
                relevance_reason="seeded for T07",
                model_used="test-model",
                prompt_version="v1",
                raw_response={"parsed": {"category": "opportunity"}},
            )
        )
        await session.commit()

    default_client = await make_authed_client(
        scoped_db.lead_a, active_dept=scoped_db.default_dept_id
    )
    default_body = (await default_client.get("/api/dashboard")).json()
    assert default_body["assessed_topics"] == 1
    assert default_body["opportunities"] == 1

    other_client = await make_authed_client(
        scoped_db.viewer_b, active_dept=scoped_db.other_dept_id
    )
    other_body = (await other_client.get("/api/dashboard")).json()
    assert other_body["assessed_topics"] == 0
    assert other_body["opportunities"] == 0


# ---------------------------------------------------------------------------
# 5. Topic list filtered by department subscription
# ---------------------------------------------------------------------------


async def test_topics_filtered_by_subscription(
    scoped_db: SeededDb, make_authed_client
) -> None:
    """Topic seen only via a source the active dept doesn't subscribe to is
    filtered out of ``GET /api/topics``."""

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    topic_id = str(uuid.uuid4())
    now = datetime.now(UTC).replace(microsecond=0)
    async with sessionmaker() as session:
        session.add(
            Topic(
                id=topic_id,
                title="HN-only topic",
                first_seen_at=now,
                last_seen_at=now,
                observation_count=1,
            )
        )
        await session.flush()
        session.add(
            TopicSource(
                topic_id=topic_id,
                source_name="hackernews",
                url="https://hackernews.example/y",
                observed_at=now,
            )
        )
        # Default subscribes to hackernews; Other does not subscribe to any.
        session.add(
            DepartmentSource(
                department_id=scoped_db.default_dept_id,
                source_name="hackernews",
                enabled=True,
            )
        )
        await session.commit()

    default_client = await make_authed_client(
        scoped_db.lead_a, active_dept=scoped_db.default_dept_id
    )
    default_body = (await default_client.get("/api/topics")).json()
    assert default_body["total"] >= 1
    assert any(t["id"] == topic_id for t in default_body["topics"])

    other_client = await make_authed_client(
        scoped_db.viewer_b, active_dept=scoped_db.other_dept_id
    )
    other_body = (await other_client.get("/api/topics")).json()
    assert all(t["id"] != topic_id for t in other_body["topics"])


# ---------------------------------------------------------------------------
# 6. Breadth is global (G5 carve-out)
# ---------------------------------------------------------------------------


async def test_breadth_is_global(
    scoped_db: SeededDb, make_authed_client
) -> None:
    """``breadth`` counts distinct sources globally, not per-dept."""

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    topic_id = str(uuid.uuid4())
    base = datetime.now(UTC).replace(microsecond=0)
    async with sessionmaker() as session:
        session.add(
            Topic(
                id=topic_id,
                title="Two-source topic",
                first_seen_at=base,
                last_seen_at=base + timedelta(seconds=60),
                observation_count=2,
            )
        )
        await session.flush()
        session.add_all(
            [
                TopicSource(
                    topic_id=topic_id,
                    source_name="hackernews",
                    url="https://hackernews.example/z",
                    observed_at=base,
                ),
                TopicSource(
                    topic_id=topic_id,
                    source_name="nyt_homepage",
                    url="https://nyt.example/z",
                    observed_at=base + timedelta(seconds=60),
                ),
            ]
        )
        # Default subscribes only to hackernews (one of the two sources).
        session.add(
            DepartmentSource(
                department_id=scoped_db.default_dept_id,
                source_name="hackernews",
                enabled=True,
            )
        )
        await session.commit()

    default_client = await make_authed_client(
        scoped_db.lead_a, active_dept=scoped_db.default_dept_id
    )
    body = (await default_client.get("/api/topics")).json()
    match = next((t for t in body["topics"] if t["id"] == topic_id), None)
    assert match is not None, "topic must be visible (dept subscribes to HN)"
    assert match["breadth"] == 2, "breadth is global; both sources counted"


# ---------------------------------------------------------------------------
# 7. department_sources CRUD + RBAC
# ---------------------------------------------------------------------------


async def test_department_sources_crud(
    scoped_db: SeededDb, make_authed_client
) -> None:
    """dept_lead can toggle a subscription; viewer cannot; GET reflects state."""

    lead_default = await make_authed_client(
        scoped_db.lead_a, active_dept=scoped_db.default_dept_id
    )

    # Initial GET returns all crawl_config sources with enabled=False.
    initial = (await lead_default.get("/api/department-sources")).json()
    assert initial["total"] == 2  # seeded: hackernews + nyt_homepage
    by_name = {s["source_name"]: s for s in initial["sources"]}
    assert by_name["hackernews"]["enabled"] is False
    assert by_name["nyt_homepage"]["enabled"] is False

    # Toggle hackernews on as dept_lead.
    put_resp = await lead_default.put(
        "/api/department-sources/hackernews", json={"enabled": True}
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["enabled"] is True

    # GET reflects the toggle.
    after = (await lead_default.get("/api/department-sources")).json()
    after_by_name = {s["source_name"]: s for s in after["sources"]}
    assert after_by_name["hackernews"]["enabled"] is True
    assert after_by_name["nyt_homepage"]["enabled"] is False

    # Unknown source → 404 (validated against crawl_config).
    missing = await lead_default.put(
        "/api/department-sources/does-not-exist", json={"enabled": True}
    )
    assert missing.status_code == 404

    # Viewer in Other cannot PUT in Other dept (viewer role, not analyst/dept_lead).
    viewer_other = await make_authed_client(
        scoped_db.viewer_b, active_dept=scoped_db.other_dept_id
    )
    forbidden = await viewer_other.put(
        "/api/department-sources/hackernews", json={"enabled": True}
    )
    assert forbidden.status_code == 403

    # Analyst in Default CAN toggle (widened from dept_lead-only — analysts
    # need to manage their own dept's source set, same trust level as
    # running crawls and curating topics).
    analyst_default = await make_authed_client(
        scoped_db.analyst_a, active_dept=scoped_db.default_dept_id
    )
    analyst_put = await analyst_default.put(
        "/api/department-sources/nyt_homepage", json={"enabled": True}
    )
    assert analyst_put.status_code == 200
    assert analyst_put.json()["enabled"] is True
