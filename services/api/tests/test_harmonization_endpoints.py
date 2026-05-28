"""Tests for Phase 10 (plan 10-05 T05) harmonization API endpoints.

Covers:
- GET  /api/topics/{topic_id}/harmonization — any authed user, cross-dept read
- PUT  /api/topics/{topic_id}/harmonization — dept_lead or superadmin only
- DELETE /api/topics/{topic_id}/harmonization — idempotent 204

10 tests total:
1. GET empty topic → 200, business_cases=[], net_view=null
2. GET nonexistent topic → 404
3. GET with business cases → populated response
4. GET as viewer (cross-dept read) → 200
5. PUT as dept_lead → creates net_view, returns full response
6. PUT as superadmin → creates net_view
7. PUT as analyst → 403
8. PUT overwrites (last-write-wins) → updated text
9. DELETE as dept_lead → 204, subsequent GET shows net_view=null
10. DELETE idempotent → 204 even when no harmonization exists
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
from assessor.domain.frameworks.verdict import VERDICT_FRAMEWORK_ID
from core.models import BusinessCase, Topic

from .conftest import SeededDb, db_available

pytestmark = pytest.mark.asyncio


_STUB_SCHEMA = {"type": "object"}


# ---------------------------------------------------------------------------
# Fixture: extend seeded_db with frameworks + a topic with business case
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def harmonization_db(seeded_db: SeededDb):
    """Seed a topic + framework + business case for harmonization tests."""

    if not db_available():
        pytest.skip("set TEST_DATABASE_URL to a reachable Postgres")

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    topic_id = str(uuid.uuid4())
    empty_topic_id = str(uuid.uuid4())
    now = datetime.now(UTC).replace(microsecond=0)

    async with sessionmaker() as session:
        # Seed verdict framework
        await session.execute(
            text(
                """
                INSERT INTO assessment_frameworks
                    (id, key, name, description, display_component,
                     json_schema, prompt_version)
                VALUES
                    (:id, 'verdict', 'Verdict', 'Verdict', 'VerdictView',
                     (:schema)::jsonb, 'v1')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": VERDICT_FRAMEWORK_ID, "schema": json.dumps(_STUB_SCHEMA)},
        )

        # Seed two topics
        for tid, title in [
            (topic_id, "Harmonization Test Topic"),
            (empty_topic_id, "Empty Topic"),
        ]:
            session.add(
                Topic(
                    id=tid,
                    title=title,
                    first_seen_at=now,
                    last_seen_at=now,
                    observation_count=1,
                )
            )
        await session.flush()

        # Seed a business case on the first topic
        session.add(
            BusinessCase(
                topic_id=topic_id,
                department_id=seeded_db.default_dept_id,
                framework_id=VERDICT_FRAMEWORK_ID,
                relevance_verdict="relevant",
                relevance_reason="test harmonization",
                model_used="test-model",
                prompt_version="v1",
                raw_response={"parsed": {"category": "opportunity"}},
                structured_output={
                    "verdict": "relevant",
                    "importance": 8,
                    "confidence": 0.9,
                },
            )
        )
        await session.commit()

    # Attach IDs to the fixture for use in tests
    seeded_db.__class__.topic_id = topic_id
    seeded_db.__class__.empty_topic_id = empty_topic_id

    yield seeded_db


# ---------------------------------------------------------------------------
# GET /api/topics/{topic_id}/harmonization
# ---------------------------------------------------------------------------


async def test_get_harmonization_empty_topic(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """Empty topic returns 200 with business_cases=[] and net_view=null."""

    client = await make_authed_client(
        harmonization_db.lead_a, active_dept=harmonization_db.default_dept_id
    )
    resp = await client.get(
        f"/api/topics/{harmonization_db.empty_topic_id}/harmonization"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["business_cases"] == []
    assert body["net_view"] is None
    assert body["topic"]["id"] == harmonization_db.empty_topic_id


async def test_get_harmonization_nonexistent_topic(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """Nonexistent topic returns 404."""

    client = await make_authed_client(
        harmonization_db.lead_a, active_dept=harmonization_db.default_dept_id
    )
    fake_id = str(uuid.uuid4())
    resp = await client.get(f"/api/topics/{fake_id}/harmonization")
    assert resp.status_code == 404, resp.text


async def test_get_harmonization_with_business_cases(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """Topic with business cases returns populated response."""

    client = await make_authed_client(
        harmonization_db.lead_a, active_dept=harmonization_db.default_dept_id
    )
    resp = await client.get(
        f"/api/topics/{harmonization_db.topic_id}/harmonization"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["business_cases"]) == 1
    bc = body["business_cases"][0]
    assert bc["department"]["id"] == harmonization_db.default_dept_id
    assert bc["framework"]["key"] == "verdict"
    assert bc["structured_output"]["importance"] == 8
    assert bc["relevance_verdict"] == "relevant"


async def test_get_harmonization_cross_dept_read_as_viewer(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """Viewer from Other dept can read harmonization (cross-dept visibility)."""

    client = await make_authed_client(
        harmonization_db.viewer_b, active_dept=harmonization_db.other_dept_id
    )
    resp = await client.get(
        f"/api/topics/{harmonization_db.topic_id}/harmonization"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["business_cases"]) == 1


# ---------------------------------------------------------------------------
# PUT /api/topics/{topic_id}/harmonization
# ---------------------------------------------------------------------------


async def test_put_harmonization_as_dept_lead(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """dept_lead can create a net_view."""

    client = await make_authed_client(
        harmonization_db.lead_a, active_dept=harmonization_db.default_dept_id
    )
    resp = await client.put(
        f"/api/topics/{harmonization_db.topic_id}/harmonization",
        json={"net_view": "This topic is highly relevant across departments."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["net_view"] is not None
    assert body["net_view"]["text"] == "This topic is highly relevant across departments."
    assert body["net_view"]["authored_by"]["username"] == harmonization_db.lead_a


async def test_put_harmonization_as_superadmin(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """Superadmin can create a net_view."""

    client = await make_authed_client(
        harmonization_db.superadmin, active_dept=harmonization_db.default_dept_id
    )
    resp = await client.put(
        f"/api/topics/{harmonization_db.empty_topic_id}/harmonization",
        json={"net_view": "Superadmin assessment."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["net_view"]["text"] == "Superadmin assessment."


async def test_put_harmonization_as_analyst_forbidden(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """Analyst lacks dept_lead role → 403."""

    client = await make_authed_client(
        harmonization_db.analyst_a, active_dept=harmonization_db.default_dept_id
    )
    resp = await client.put(
        f"/api/topics/{harmonization_db.topic_id}/harmonization",
        json={"net_view": "Should fail."},
    )
    assert resp.status_code == 403, resp.text


async def test_put_harmonization_overwrites_last_write_wins(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """Second PUT overwrites the first (last-write-wins)."""

    client = await make_authed_client(
        harmonization_db.lead_a, active_dept=harmonization_db.default_dept_id
    )
    topic_id = harmonization_db.topic_id

    # First write
    await client.put(
        f"/api/topics/{topic_id}/harmonization",
        json={"net_view": "First version."},
    )

    # Second write overwrites
    resp = await client.put(
        f"/api/topics/{topic_id}/harmonization",
        json={"net_view": "Updated version."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["net_view"]["text"] == "Updated version."


# ---------------------------------------------------------------------------
# DELETE /api/topics/{topic_id}/harmonization
# ---------------------------------------------------------------------------


async def test_delete_harmonization(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """DELETE removes net_view; subsequent GET shows net_view=null."""

    client = await make_authed_client(
        harmonization_db.lead_a, active_dept=harmonization_db.default_dept_id
    )
    topic_id = harmonization_db.topic_id

    # Create first
    await client.put(
        f"/api/topics/{topic_id}/harmonization",
        json={"net_view": "To be deleted."},
    )

    # Delete
    resp = await client.delete(f"/api/topics/{topic_id}/harmonization")
    assert resp.status_code == 204, resp.text

    # Verify gone
    get_resp = await client.get(f"/api/topics/{topic_id}/harmonization")
    assert get_resp.status_code == 200
    assert get_resp.json()["net_view"] is None


async def test_delete_harmonization_idempotent(
    harmonization_db: SeededDb, make_authed_client
) -> None:
    """DELETE returns 204 even when no harmonization exists."""

    client = await make_authed_client(
        harmonization_db.lead_a, active_dept=harmonization_db.default_dept_id
    )
    resp = await client.delete(
        f"/api/topics/{harmonization_db.empty_topic_id}/harmonization"
    )
    assert resp.status_code == 204, resp.text
