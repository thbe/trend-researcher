"""Tests for Phase 10 (plan 10-03 T09) frameworks API + dept default lookup.

Covers the surface added in T08:

- ``GET  /api/frameworks``        — list all 3 registered frameworks.
- ``GET  /api/frameworks/mine``   — list this dept's enabled frameworks with
  a single ``is_default`` flag.
- ``PUT  /api/frameworks/mine``   — dept_lead replaces the enabled set and
  picks a default; analyst is rejected (403); default-not-in-enabled is 422.
- ``POST /api/assess``            — uses the dept default when ``framework_id``
  is omitted, rejects a framework_id that is not enabled for the dept (422).
- ``POST /api/departments``       — auto-enables all 3 frameworks with
  verdict as the default for any newly-created department (superadmin only).
- ``GET  /api/business-cases``    — response now embeds the framework block
  (id/key/display_component) and the ``structured_output`` JSONB.

All tests skip-gate on ``TEST_DATABASE_URL`` via the existing
:func:`db_available` helper and reuse the :func:`seeded_db` /
:func:`make_authed_client` fixtures from conftest.

The conftest fixture builds the schema with ``Base.metadata.create_all`` and
does NOT replay migration 0019, so this module seeds the framework rows +
``department_frameworks`` opt-ins itself (mirrors what the FastAPI lifespan
+ the POST /departments handler do in production).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text

import core
from assessor.domain.frameworks.pestle import PESTLE_FRAMEWORK_ID
from assessor.domain.frameworks.swot import SWOT_FRAMEWORK_ID
from assessor.domain.frameworks.verdict import VERDICT_FRAMEWORK_ID
from core.models import (
    BusinessCase,
    Topic,
)

from .conftest import SeededDb, db_available


pytestmark = pytest.mark.asyncio


# Minimal JSON schemas for the seeded framework rows. Real schemas live in
# the assessor modules; the API doesn't validate against them in these tests
# so a stub object is enough to satisfy the NOT NULL JSONB column.
_STUB_SCHEMA = {"type": "object"}


# ---------------------------------------------------------------------------
# Fixture: extend seeded_db with framework registry + per-dept opt-ins
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def frameworks_db(seeded_db: SeededDb):
    """Seed the 3 frameworks + auto-enable them on both seeded departments.

    Mirrors migration 0019 (framework rows with hardcoded UUIDs) and the
    auto-enable behaviour added to ``POST /api/departments`` in T08
    (verdict flagged as default).
    """

    if not db_available():
        pytest.skip("set TEST_DATABASE_URL to a reachable Postgres")

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    framework_rows = [
        (VERDICT_FRAMEWORK_ID, "verdict", "Verdict", "VerdictView", "v1"),
        (SWOT_FRAMEWORK_ID, "swot", "SWOT", "SwotView", "swot.v1"),
        (PESTLE_FRAMEWORK_ID, "pestle", "PESTLE", "PestleView", "pestle.v1"),
    ]

    async with sessionmaker() as session:
        for fw_id, key, name, display, prompt_ver in framework_rows:
            await session.execute(
                text(
                    """
                    INSERT INTO assessment_frameworks
                        (id, key, name, description, display_component,
                         json_schema, prompt_version)
                    VALUES
                        (:id, :key, :name, :name, :display,
                         (:schema)::jsonb, :prompt_ver)
                    """
                ),
                {
                    "id": fw_id,
                    "key": key,
                    "name": name,
                    "display": display,
                    "schema": json.dumps(_STUB_SCHEMA),
                    "prompt_ver": prompt_ver,
                },
            )

        # Auto-enable all three on both depts; verdict is default.
        for dept_id in (seeded_db.default_dept_id, seeded_db.other_dept_id):
            for fw_id, key, *_ in framework_rows:
                await session.execute(
                    text(
                        """
                        INSERT INTO department_frameworks
                            (department_id, framework_id, is_default)
                        VALUES (:dept_id, :fw_id, :is_default)
                        """
                    ),
                    {
                        "dept_id": dept_id,
                        "fw_id": fw_id,
                        "is_default": key == "verdict",
                    },
                )
        await session.commit()

    yield seeded_db
    # seeded_db's teardown drops every table, so no extra cleanup needed.


# ---------------------------------------------------------------------------
# GET /api/frameworks
# ---------------------------------------------------------------------------


async def test_list_frameworks_returns_three(
    frameworks_db: SeededDb, make_authed_client
) -> None:
    """Any authed user (with an active dept) can read the global registry."""

    client = await make_authed_client(
        frameworks_db.lead_a, active_dept=frameworks_db.default_dept_id
    )
    resp = await client.get("/api/frameworks")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    keys = sorted(it["key"] for it in items)
    assert keys == ["pestle", "swot", "verdict"]


# ---------------------------------------------------------------------------
# GET /api/frameworks/mine
# ---------------------------------------------------------------------------


async def test_my_frameworks_default_dept_has_verdict_default(
    frameworks_db: SeededDb, make_authed_client
) -> None:
    """Default dept ships with all 3 enabled and verdict flagged as default."""

    client = await make_authed_client(
        frameworks_db.lead_a, active_dept=frameworks_db.default_dept_id
    )
    resp = await client.get("/api/frameworks/mine")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body

    by_key = {it["key"]: it for it in items}
    assert set(by_key) == {"verdict", "swot", "pestle"}
    assert by_key["verdict"]["is_default"] is True
    assert by_key["swot"]["is_default"] is False
    assert by_key["pestle"]["is_default"] is False


# ---------------------------------------------------------------------------
# PUT /api/frameworks/mine
# ---------------------------------------------------------------------------


async def test_put_my_frameworks_replaces_set(
    frameworks_db: SeededDb, make_authed_client
) -> None:
    """dept_lead can replace the enabled set + change the default."""

    client = await make_authed_client(
        frameworks_db.lead_a, active_dept=frameworks_db.default_dept_id
    )
    resp = await client.put(
        "/api/frameworks/mine",
        json={
            "enabled_framework_ids": [SWOT_FRAMEWORK_ID, PESTLE_FRAMEWORK_ID],
            "default_framework_id": SWOT_FRAMEWORK_ID,
        },
    )
    assert resp.status_code == 200, resp.text

    follow = await client.get("/api/frameworks/mine")
    body = follow.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    by_key = {it["key"]: it for it in items}
    assert set(by_key) == {"swot", "pestle"}
    assert by_key["swot"]["is_default"] is True
    assert by_key["pestle"]["is_default"] is False


async def test_put_my_frameworks_default_must_be_in_enabled(
    frameworks_db: SeededDb, make_authed_client
) -> None:
    """Default not in enabled set is a 422 (pydantic model_validator)."""

    client = await make_authed_client(
        frameworks_db.lead_a, active_dept=frameworks_db.default_dept_id
    )
    resp = await client.put(
        "/api/frameworks/mine",
        json={
            "enabled_framework_ids": [SWOT_FRAMEWORK_ID, PESTLE_FRAMEWORK_ID],
            "default_framework_id": VERDICT_FRAMEWORK_ID,
        },
    )
    assert resp.status_code == 422, resp.text


async def test_put_my_frameworks_requires_dept_lead(
    frameworks_db: SeededDb, make_authed_client
) -> None:
    """Analyst lacks dept_lead role → 403."""

    client = await make_authed_client(
        frameworks_db.analyst_a, active_dept=frameworks_db.default_dept_id
    )
    resp = await client.put(
        "/api/frameworks/mine",
        json={
            "enabled_framework_ids": [VERDICT_FRAMEWORK_ID],
            "default_framework_id": VERDICT_FRAMEWORK_ID,
        },
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Assessment endpoints — framework resolution
# ---------------------------------------------------------------------------


async def test_assessment_uses_dept_default_when_framework_id_omitted(
    frameworks_db: SeededDb, make_authed_client
) -> None:
    """POST /api/assess with empty body picks the dept default framework."""

    client = await make_authed_client(
        frameworks_db.lead_a, active_dept=frameworks_db.default_dept_id
    )
    resp = await client.post("/api/assess", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Default dept's default is verdict.
    assert body["framework_id"] == VERDICT_FRAMEWORK_ID
    assert body["department_id"] == frameworks_db.default_dept_id

    # And the row persisted on assessment_jobs carries the same framework_id.
    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)
    async with sessionmaker() as session:
        row = (
            await session.execute(
                text(
                    "SELECT framework_id FROM assessment_jobs WHERE id = :id"
                ),
                {"id": body["job_id"]},
            )
        ).first()
    assert row is not None
    assert str(row[0]) == VERDICT_FRAMEWORK_ID


async def test_assessment_rejects_disabled_framework(
    frameworks_db: SeededDb, make_authed_client
) -> None:
    """Disable pestle on Default, then POST with pestle's id → 422."""

    lead = await make_authed_client(
        frameworks_db.lead_a, active_dept=frameworks_db.default_dept_id
    )
    drop = await lead.put(
        "/api/frameworks/mine",
        json={
            "enabled_framework_ids": [VERDICT_FRAMEWORK_ID, SWOT_FRAMEWORK_ID],
            "default_framework_id": VERDICT_FRAMEWORK_ID,
        },
    )
    assert drop.status_code == 200, drop.text

    resp = await lead.post(
        "/api/assess",
        json={"framework_id": PESTLE_FRAMEWORK_ID},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# POST /api/departments — auto-enable
# ---------------------------------------------------------------------------


async def test_new_department_auto_enables_all_frameworks(
    frameworks_db: SeededDb, make_authed_client
) -> None:
    """A new dept created via the API gets all 3 frameworks + verdict default."""

    super_client = await make_authed_client(
        frameworks_db.superadmin, active_dept=frameworks_db.default_dept_id
    )
    slug = f"phase10-fw-{uuid.uuid4().hex[:8]}"
    create = await super_client.post(
        "/api/departments",
        json={"name": f"FW Auto {slug}", "slug": slug},
    )
    assert create.status_code in (200, 201), create.text
    new_dept_id = create.json()["id"]

    # Switch active dept to the freshly created one (superadmin can pick any).
    new_client = await make_authed_client(
        frameworks_db.superadmin, active_dept=new_dept_id
    )
    resp = await new_client.get("/api/frameworks/mine")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    by_key = {it["key"]: it for it in items}
    assert set(by_key) == {"verdict", "swot", "pestle"}
    assert by_key["verdict"]["is_default"] is True


# ---------------------------------------------------------------------------
# GET /api/business-cases — response shape (T08 JOIN)
# ---------------------------------------------------------------------------


async def test_business_case_response_includes_structured_output_and_framework(
    frameworks_db: SeededDb, make_authed_client
) -> None:
    """Verifies the T08 SELECT join populates ``framework`` + ``structured_output``.

    We bypass the LLM entirely by inserting a BusinessCase row directly
    (the assessment pipeline is exercised in the assessor suite). This test
    asserts the API response shape only.
    """

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    topic_id = str(uuid.uuid4())
    now = datetime.now(UTC).replace(microsecond=0)
    structured = {"verdict": "relevant", "reason": "structured payload"}

    async with sessionmaker() as session:
        session.add(
            Topic(
                id=topic_id,
                title="Framework JOIN topic",
                first_seen_at=now,
                last_seen_at=now,
                observation_count=1,
            )
        )
        await session.flush()
        session.add(
            BusinessCase(
                topic_id=topic_id,
                department_id=frameworks_db.default_dept_id,
                framework_id=VERDICT_FRAMEWORK_ID,
                relevance_verdict="relevant",
                relevance_reason="seeded for T09",
                model_used="test-model",
                prompt_version="v1",
                raw_response={"parsed": {"category": "opportunity"}},
                structured_output=structured,
            )
        )
        await session.commit()

    client = await make_authed_client(
        frameworks_db.lead_a, active_dept=frameworks_db.default_dept_id
    )
    resp = await client.get("/api/business-cases")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert isinstance(rows, list) and rows, rows

    row = next((r for r in rows if r["topic_id"] == topic_id), None)
    assert row is not None
    assert row["structured_output"] == structured
    assert row["framework"]["id"] == VERDICT_FRAMEWORK_ID
    assert row["framework"]["key"] == "verdict"
    assert row["framework"]["display_component"] == "VerdictView"
