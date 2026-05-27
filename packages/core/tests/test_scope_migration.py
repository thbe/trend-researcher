"""Integration tests for migration 0017 (scope existing tables per-department).

Skipped automatically when ``TEST_DATABASE_URL`` is unset or the configured
database is unreachable. Set ``TEST_DATABASE_URL`` to enable, e.g.::

    export TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test

These tests pin migration 0017 (plan 10-02) — the cleanup pass that makes
the single-tenant schema multi-tenant by attaching every per-tenant table
to the Default department seeded in 0016:

1. ``ai_config`` is rekeyed from ``key='default'`` → ``department_id``,
   and the pre-existing ``default`` row lands on Default with every column
   value preserved.
2. ``business_cases`` rows get backfilled with ``department_id =
   Default`` (NOT NULL, indexed).
3. ``assessment_jobs`` rows get backfilled the same way.
4. ``department_sources`` is seeded with one row per ``crawl_config``
   row for Default, preserving the original ``enabled`` value.
5. ``crawl_config.enabled`` column is dropped (single source of truth
   is now ``department_sources``).
6. A pre-check refuses to upgrade if duplicate (topic_id, prompt_version,
   model_used) rows exist in ``business_cases`` — otherwise the
   10-03 UNIQUE constraint would silently break the migration.

Pattern mirrors :mod:`test_departments_migration` — real
``alembic upgrade`` subprocesses against a live test DB.
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
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


DEFAULT_DEPARTMENT_ID = "00000000-0000-0000-0000-000000000001"
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


def _alembic(action: str, target: str, dsn: str, *, check: bool = True,
             capture_output: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": _sync_dsn(dsn)}
    return subprocess.run(
        ["alembic", action, target],
        cwd=_CORE_PKG_ROOT,
        env=env,
        check=check,
        capture_output=capture_output,
        text=True,
    )


# Seed data we plant at revision 0016 BEFORE upgrading to 0017.
# Values chosen so every assertion can pin "this exact value survived".
_AI_CONFIG_SEED = {
    "base_url": "http://ollama-test:11434",
    "model": "test-model:latest",
    "api_token": "test-token-xyz",
    "business_context": "Retail v1 context for migration test",
    "opportunity_criteria": "Test opp criteria",
    "risk_criteria": "Test risk criteria",
    "thinking_effort": "medium",
    "request_timeout_seconds": 240,
}

# Three crawl_config rows with mixed enabled flags. The 0007 seed inserts
# (hackernews, nyt_homepage, google_news) already exist at 0007; we just
# UPDATE their enabled column to known values so the assertion is precise.
_CRAWL_CONFIG_ENABLED = {
    "hackernews": True,
    "nyt_homepage": False,
    "google_news": True,
}


async def _seed_at_0016(eng: AsyncEngine) -> None:
    """Insert pre-0017 fixture data: ai_config row, mixed crawl_config
    enabled flags, a topic + 3 business_cases (distinct prompt_version),
    and one assessment_job."""
    async with eng.begin() as conn:
        # ai_config — UPDATE the pre-seeded 'default' row (created by 0010).
        await conn.execute(
            text(
                """
                UPDATE ai_config SET
                    base_url = :base_url,
                    model = :model,
                    api_token = :api_token,
                    business_context = :business_context,
                    opportunity_criteria = :opportunity_criteria,
                    risk_criteria = :risk_criteria,
                    thinking_effort = :thinking_effort,
                    request_timeout_seconds = :request_timeout_seconds
                WHERE key = 'default'
                """
            ),
            _AI_CONFIG_SEED,
        )

        # crawl_config — flip enabled flags to known mix.
        for src, enabled in _CRAWL_CONFIG_ENABLED.items():
            await conn.execute(
                text(
                    "UPDATE crawl_config SET enabled = :en "
                    "WHERE source_name = :s"
                ),
                {"en": enabled, "s": src},
            )

        # One topic.
        topic_id = (
            await conn.execute(
                text(
                    "INSERT INTO topics (title) VALUES ('Test topic') "
                    "RETURNING id"
                )
            )
        ).scalar_one()

        # Three business_cases with DISTINCT (prompt_version, model_used)
        # so the 0017 pre-check does NOT trip.
        for i in range(3):
            await conn.execute(
                text(
                    """
                    INSERT INTO business_cases
                        (topic_id, relevance_verdict, relevance_reason,
                         model_used, prompt_version)
                    VALUES (:tid, 'relevant', 'because',
                            :model, :pv)
                    """
                ),
                {
                    "tid": topic_id,
                    "model": f"test-model-{i}",
                    "pv": f"v1.{i}",
                },
            )

        # One assessment_job.
        await conn.execute(
            text(
                "INSERT INTO assessment_jobs (state, total_topics) "
                "VALUES ('done', 1)"
            )
        )


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_engine() -> AsyncIterator[AsyncEngine]:
    """Per-test engine. Upgrades to 0016, seeds pre-0017 data, upgrades
    to head. Teardown downgrades to base.
    """
    dsn = _test_database_url()
    assert dsn is not None  # gated by pytestmark
    _alembic("upgrade", "0016", dsn)
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    await _seed_at_0016(eng)
    await eng.dispose()
    _alembic("upgrade", "head", dsn)
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    try:
        yield eng
    finally:
        await eng.dispose()
        _alembic("downgrade", "base", dsn)


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_session_factory(
    migrated_engine: AsyncEngine,
) -> async_sessionmaker:
    return async_sessionmaker(migrated_engine, expire_on_commit=False)


async def test_ai_config_migrated_to_default_dept(
    migrated_session_factory,
) -> None:
    """Single ai_config row, keyed by Default dept, every column preserved."""
    async with migrated_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT department_id, base_url, model, api_token, "
                    "business_context, opportunity_criteria, risk_criteria, "
                    "thinking_effort, request_timeout_seconds FROM ai_config"
                )
            )
        ).mappings().all()
    assert len(rows) == 1
    row = rows[0]
    assert row["department_id"] == DEFAULT_DEPARTMENT_ID
    for col, expected in _AI_CONFIG_SEED.items():
        assert row[col] == expected, f"ai_config.{col} not preserved"


async def test_business_cases_backfilled(
    migrated_session_factory,
) -> None:
    """Every pre-existing business_cases row attached to Default dept;
    column is NOT NULL."""
    async with migrated_session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT department_id FROM business_cases")
            )
        ).mappings().all()
    assert len(rows) == 3
    for row in rows:
        assert row["department_id"] == DEFAULT_DEPARTMENT_ID


async def test_assessment_jobs_backfilled(
    migrated_session_factory,
) -> None:
    """Every pre-existing assessment_jobs row attached to Default dept."""
    async with migrated_session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT department_id FROM assessment_jobs")
            )
        ).mappings().all()
    assert len(rows) == 1
    assert rows[0]["department_id"] == DEFAULT_DEPARTMENT_ID


async def test_department_sources_seeded_from_crawl_config(
    migrated_session_factory,
) -> None:
    """One department_sources row per pre-existing crawl_config source,
    enabled flag carried over verbatim."""
    async with migrated_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT source_name, enabled FROM department_sources "
                    "WHERE department_id = :did "
                    "ORDER BY source_name"
                ),
                {"did": DEFAULT_DEPARTMENT_ID},
            )
        ).mappings().all()
    got = {r["source_name"]: r["enabled"] for r in rows}
    assert got == _CRAWL_CONFIG_ENABLED


async def test_crawl_config_enabled_column_dropped(
    migrated_session_factory,
) -> None:
    """Selecting crawl_config.enabled post-0017 raises a column-missing
    error."""
    with pytest.raises(ProgrammingError) as exc_info:
        async with migrated_session_factory() as session:
            await session.execute(text("SELECT enabled FROM crawl_config"))
    assert "enabled" in str(exc_info.value).lower()


async def test_duplicate_business_cases_block_migration() -> None:
    """0017 must REFUSE to run when duplicate (topic_id, prompt_version,
    model_used) rows exist — otherwise the 10-03 UNIQUE would silently
    break the migration."""
    dsn = _test_database_url()
    assert dsn is not None
    # Fresh schema at 0016 (the previous test's teardown may not have run
    # if it's the first test; either way downgrade-base + upgrade-0016
    # is idempotent).
    _alembic("downgrade", "base", dsn, check=False)
    _alembic("upgrade", "0016", dsn)
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    try:
        async with eng.begin() as conn:
            topic_id = (
                await conn.execute(
                    text(
                        "INSERT INTO topics (title) VALUES ('Dup topic') "
                        "RETURNING id"
                    )
                )
            ).scalar_one()
            # Two rows with IDENTICAL (topic_id, prompt_version, model_used).
            for _ in range(2):
                await conn.execute(
                    text(
                        """
                        INSERT INTO business_cases
                            (topic_id, relevance_verdict, relevance_reason,
                             model_used, prompt_version)
                        VALUES (:tid, 'relevant', 'r',
                                'same-model', 'v1.0')
                        """
                    ),
                    {"tid": topic_id},
                )
    finally:
        await eng.dispose()

    result = _alembic("upgrade", "head", dsn, check=False, capture_output=True)
    try:
        assert result.returncode != 0, (
            "alembic upgrade should have failed but returned 0"
        )
        combined = (result.stderr or "") + (result.stdout or "")
        assert "duplicate" in combined.lower(), (
            f"expected duplicate-message in output, got: {combined!r}"
        )
    finally:
        # Cleanup so subsequent tests start clean.
        _alembic("downgrade", "base", dsn, check=False)
