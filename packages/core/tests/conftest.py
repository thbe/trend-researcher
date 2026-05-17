"""Shared pytest fixtures for the ``packages/core`` test suite.

Phase 4 first introduces tests at this layer (Phase 1/2/3 kept tests inside
the consuming services). The pattern mirrors ``services/crawler/tests/
conftest.py`` exactly:

- Skip cleanly when ``TEST_DATABASE_URL`` is unset OR the target Postgres
  is unreachable (cheap TCP probe, no hang).
- Session-scoped async engine that calls ``Base.metadata.create_all`` for
  ORM-mapped tables, then executes the raw ``CREATE VIEW v_topic_stats``
  SQL directly so the view exists alongside the metadata-managed tables.
  Tests stay independent of the Alembic apply step but still exercise the
  exact view DDL shipped in migration 0003 (a `__view_sql__` constant is
  imported from the migration file so the SQL is single-sourced).
- ``NullPool`` so pytest-asyncio's per-test event loops don't trip the
  "engine attached to a different loop" trap on the session-scoped engine.
- ``clean_tables`` autouse fixture truncates topics + topic_sources +
  crawl_runs between every test (the view is read-through; no separate
  view truncation step).

When ``TEST_DATABASE_URL`` is unset, every test depending on the engine
fixture skips with a clear reason; this is the same fail-shape Phase 1/2/3
already use, so the existing CI/dev ergonomics carry forward.
"""

from __future__ import annotations

import importlib.util
import os
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.models import Base


DEFAULT_TEST_DSN = (
    "postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test"
)


def _test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


def _can_reach(dsn: str) -> bool:
    """Cheap TCP probe so we skip rather than fail when no DB is up."""
    parsed = urlparse(dsn.replace("postgresql+asyncpg", "postgresql"))
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def db_available() -> bool:
    dsn = _test_database_url()
    if not dsn:
        return False
    return _can_reach(dsn)


def _load_view_sql() -> tuple[str, str]:
    """Load the CREATE VIEW + DROP VIEW SQL from the 0003 migration module.

    Single-sourcing: the migration file is the canonical SQL definition.
    Tests import the constants so any future edit to the view formula only
    has to land in one place and is exercised by these tests automatically.
    """
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0003_topic_stats_view.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_v_topic_stats_migration", migration_path
    )
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise RuntimeError(f"could not load migration at {migration_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._CREATE_VIEW_SQL, module._DROP_VIEW_SQL


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Session-scoped async engine with ORM tables + the v_topic_stats VIEW.

    Skips the whole fixture (and any test depending on it) when no Postgres
    is reachable, instead of failing at engine init time.
    """
    if not db_available():
        pytest.skip("set TEST_DATABASE_URL to a reachable Postgres")
    dsn = _test_database_url() or DEFAULT_TEST_DSN
    create_view_sql, drop_view_sql = _load_view_sql()
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    async with eng.begin() as conn:
        # pgcrypto for gen_random_uuid() server-side defaults on Topic /
        # TopicSource / CrawlRun primary keys.
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        # Drop the view first in case a prior run died mid-teardown; the
        # ORM drop_all below cannot drop a view-dependent object cleanly.
        await conn.exec_driver_sql(drop_view_sql)
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(create_view_sql)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.exec_driver_sql(drop_view_sql)
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """Function-scoped sessionmaker bound to the test engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean_tables(request) -> AsyncIterator[None]:
    """Truncate topic_sources + topics + crawl_runs between view tests.

    The view itself is read-through over the truncated base tables, so no
    explicit view truncation is needed.
    """
    _DB_TEST_FILES = ("test_topic_stats_view",)
    if not any(name in request.node.nodeid for name in _DB_TEST_FILES):
        yield
        return
    eng = request.getfixturevalue("engine")
    async with eng.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE topic_sources, topics, crawl_runs RESTART IDENTITY CASCADE"
        )
    yield
