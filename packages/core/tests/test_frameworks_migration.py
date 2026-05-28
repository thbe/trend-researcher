"""Integration tests for migration 0019 (assessment frameworks + per-dept
enablement + business_cases.framework_id / structured_output).

Skipped automatically when ``TEST_DATABASE_URL`` is unset or the configured
database is unreachable. Set ``TEST_DATABASE_URL`` to enable, e.g.::

    export TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test

These tests pin migration 0019 (plan 10-03 / MT-005 + MT-007):

1. The three system frameworks (verdict / swot / pestle) are seeded with
   their hardcoded UUIDs.
2. The Default department gets all three frameworks enabled via
   ``department_frameworks``, with ``verdict`` marked as the default.
3. Every pre-existing ``business_cases`` row receives ``framework_id =
   verdict_uuid`` (NOT NULL post-migration, indexed).
4. ``structured_output`` is backfilled from ``raw_response`` when present.
5. When ``raw_response`` is NULL, ``structured_output`` falls back to
   ``{'verdict': relevance_verdict, 'reason': relevance_reason}`` — the
   minimal shape required by ``_VERDICT_SCHEMA``.
6. The composite ``UNIQUE (topic_id, department_id, framework_id,
   prompt_version, model_used)`` is enforced.
7. The partial unique index ``(department_id) WHERE is_default = true``
   on ``department_frameworks`` is enforced.

Pattern mirrors :mod:`test_scope_migration` — real ``alembic upgrade``
subprocesses against a live test DB, with seed data inserted at 0018
BEFORE upgrading to 0019 (head).
"""

from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


DEFAULT_DEPARTMENT_ID = "00000000-0000-0000-0000-000000000001"
VERDICT_FRAMEWORK_ID = "00000000-0000-0000-0000-000000000010"
SWOT_FRAMEWORK_ID = "00000000-0000-0000-0000-000000000011"
PESTLE_FRAMEWORK_ID = "00000000-0000-0000-0000-000000000012"

_CORE_PKG_ROOT = Path(__file__).resolve().parents[1]


def _test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


def _can_reach(dsn: str) -> bool:
    parsed = urlparse(dsn.replace("postgresql+asyncpg", "postgresql"))
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _db_available() -> bool:
    dsn = _test_database_url()
    return dsn is not None and _can_reach(dsn)


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="set TEST_DATABASE_URL to a reachable Postgres to run these tests",
)


def _sync_dsn(async_dsn: str) -> str:
    """Alembic uses a sync driver; rewrite asyncpg DSN to psycopg2/psycopg."""
    return async_dsn.replace("postgresql+asyncpg", "postgresql+psycopg2")


def _alembic(action: str, target: str, dsn: str, *, check: bool = True
             ) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": _sync_dsn(dsn)}
    return subprocess.run(
        ["alembic", action, target],
        cwd=_CORE_PKG_ROOT,
        env=env,
        check=check,
    )


# Seed data planted at 0018 BEFORE upgrading to 0019.
#
# - ``_RAW_RESPONSE_ROW`` carries a full parsed-LLM JSON payload — proves
#   structured_output backfill copies raw_response verbatim.
# - ``_NULL_RAW_ROW`` has raw_response = NULL — proves the COALESCE fallback
#   yields ``{'verdict', 'reason'}`` from the NOT-NULL columns.
_RAW_RESPONSE_PAYLOAD = {
    "reasoning": "test reasoning",
    "verdict": "relevant",
    "category": "opportunity",
    "reason": "matters because retail",
}


async def _seed_at_0018(eng: AsyncEngine) -> dict[str, str]:
    """Insert a topic + two business_cases rows at revision 0018.

    Both rows belong to Default dept (seeded by 0016) since Default is the
    only department present after 0017 in a clean test DB. Returns the
    topic UUID so tests can reference it.
    """
    async with eng.begin() as conn:
        topic_id = (
            await conn.execute(
                text(
                    "INSERT INTO topics (title) VALUES ('Framework test topic') "
                    "RETURNING id"
                )
            )
        ).scalar_one()

        # Row 1 — full raw_response. Distinct (prompt_version, model_used) so
        # the 0017 composite-uniqueness pre-check is also satisfied within
        # this single dept.
        await conn.execute(
            text(
                """
                INSERT INTO business_cases
                    (topic_id, department_id, relevance_verdict,
                     relevance_reason, model_used, prompt_version,
                     raw_response)
                VALUES (:tid, :did, 'relevant', 'matters because retail',
                        'test-model-a', 'v4', (:raw)::jsonb)
                """
            ),
            {
                "tid": topic_id,
                "did": DEFAULT_DEPARTMENT_ID,
                "raw": __import__("json").dumps(_RAW_RESPONSE_PAYLOAD),
            },
        )

        # Row 2 — raw_response NULL (legacy parse-failure shape).
        await conn.execute(
            text(
                """
                INSERT INTO business_cases
                    (topic_id, department_id, relevance_verdict,
                     relevance_reason, model_used, prompt_version,
                     raw_response)
                VALUES (:tid, :did, 'not-relevant',
                        'LLM response parse failure: foo',
                        'test-model-b', 'v4', NULL)
                """
            ),
            {"tid": topic_id, "did": DEFAULT_DEPARTMENT_ID},
        )

        return {"topic_id": str(topic_id)}


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_state() -> AsyncIterator[tuple[AsyncEngine, dict[str, str]]]:
    """Per-test engine. Upgrades to 0018, seeds pre-0019 data, upgrades to
    head. Teardown downgrades to base."""
    dsn = _test_database_url()
    assert dsn is not None  # gated by pytestmark
    _alembic("downgrade", "base", dsn, check=False)
    _alembic("upgrade", "0018", dsn)
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    seeded = await _seed_at_0018(eng)
    await eng.dispose()
    _alembic("upgrade", "head", dsn)
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    try:
        yield eng, seeded
    finally:
        await eng.dispose()
        _alembic("downgrade", "base", dsn)


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_session_factory(
    migrated_state: tuple[AsyncEngine, dict[str, str]],
) -> async_sessionmaker:
    eng, _ = migrated_state
    return async_sessionmaker(eng, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_three_frameworks_seeded(migrated_session_factory) -> None:
    """assessment_frameworks contains exactly verdict / swot / pestle with
    their hardcoded UUIDs."""
    async with migrated_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, key, display_component "
                    "FROM assessment_frameworks ORDER BY key"
                )
            )
        ).mappings().all()
    got = {r["key"]: (r["id"], r["display_component"]) for r in rows}
    assert got == {
        "pestle": (PESTLE_FRAMEWORK_ID, "PestleCard"),
        "swot": (SWOT_FRAMEWORK_ID, "SwotCard"),
        "verdict": (VERDICT_FRAMEWORK_ID, "VerdictCard"),
    }


async def test_default_dept_has_verdict_default(
    migrated_session_factory,
) -> None:
    """Default dept enabled for all 3 frameworks; verdict is the default."""
    async with migrated_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT f.key, df.is_default "
                    "FROM department_frameworks df "
                    "JOIN assessment_frameworks f ON f.id = df.framework_id "
                    "WHERE df.department_id = :did "
                    "ORDER BY f.key"
                ),
                {"did": DEFAULT_DEPARTMENT_ID},
            )
        ).mappings().all()
    got = {r["key"]: r["is_default"] for r in rows}
    assert got == {"pestle": False, "swot": False, "verdict": True}


async def test_business_cases_backfilled_with_framework_id(
    migrated_session_factory,
) -> None:
    """Every pre-existing row backfilled with framework_id = verdict UUID,
    NOT NULL."""
    async with migrated_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT framework_id FROM business_cases"
                )
            )
        ).mappings().all()
    assert len(rows) == 2
    for r in rows:
        assert r["framework_id"] == VERDICT_FRAMEWORK_ID


async def test_structured_output_round_trips_for_verdict_rows(
    migrated_session_factory,
) -> None:
    """Rows with raw_response present get that JSONB copied into
    structured_output verbatim."""
    async with migrated_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT structured_output FROM business_cases "
                    "WHERE model_used = 'test-model-a'"
                )
            )
        ).mappings().one()
    assert row["structured_output"] == _RAW_RESPONSE_PAYLOAD


async def test_null_raw_response_row_gets_fallback_structured_output(
    migrated_session_factory,
) -> None:
    """Rows whose raw_response was NULL fall back to the minimal
    ``{'verdict', 'reason'}`` shape rebuilt from the NOT NULL columns —
    enough to satisfy ``_VERDICT_SCHEMA.required``."""
    async with migrated_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT structured_output FROM business_cases "
                    "WHERE model_used = 'test-model-b'"
                )
            )
        ).mappings().one()
    assert row["structured_output"] == {
        "verdict": "not-relevant",
        "reason": "LLM response parse failure: foo",
    }


async def test_composite_unique_enforced(
    migrated_session_factory,
    migrated_state: tuple[AsyncEngine, dict[str, str]],
) -> None:
    """Inserting a row with the same (topic_id, department_id, framework_id,
    prompt_version, model_used) as an existing row raises IntegrityError."""
    _, seeded = migrated_state
    topic_id = seeded["topic_id"]
    with pytest.raises(IntegrityError) as exc_info:
        async with migrated_session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO business_cases
                        (topic_id, department_id, framework_id,
                         relevance_verdict, relevance_reason,
                         model_used, prompt_version, structured_output)
                    VALUES (:tid, :did, :fid, 'relevant', 'dup',
                            'test-model-a', 'v4', '{}'::jsonb)
                    """
                ),
                {
                    "tid": topic_id,
                    "did": DEFAULT_DEPARTMENT_ID,
                    "fid": VERDICT_FRAMEWORK_ID,
                },
            )
            await session.commit()
    msg = str(exc_info.value).lower()
    assert "uq_business_cases_topic_dept_fw_prompt_model" in msg or \
        "unique" in msg


async def test_partial_unique_one_default_per_dept(
    migrated_session_factory,
) -> None:
    """Marking a second framework as default for Default dept violates the
    partial unique index ``(department_id) WHERE is_default = true``."""
    with pytest.raises(IntegrityError) as exc_info:
        async with migrated_session_factory() as session:
            # Flip swot's is_default → true while verdict is still default.
            await session.execute(
                text(
                    "UPDATE department_frameworks SET is_default = true "
                    "WHERE department_id = :did AND framework_id = :fid"
                ),
                {
                    "did": DEFAULT_DEPARTMENT_ID,
                    "fid": SWOT_FRAMEWORK_ID,
                },
            )
            await session.commit()
    msg = str(exc_info.value).lower()
    assert "uq_department_frameworks_one_default_per_dept" in msg or \
        "unique" in msg
