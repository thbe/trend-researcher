"""Shared pytest fixtures for the crawler test suite.

Phase 1 fixtures here support repository integration tests against a real
Postgres. Tests skip cleanly when ``TEST_DATABASE_URL`` is unset OR when the
configured database is unreachable.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

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


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Session-scoped async engine. Creates schema directly via metadata
    (NOT alembic) so tests stay independent of the migration apply step.

    Skips the entire fixture (and any test that depends on it) when no
    Postgres is reachable, instead of failing at engine init time.
    """
    if not db_available():
        pytest.skip("set TEST_DATABASE_URL to a reachable Postgres")
    dsn = _test_database_url() or DEFAULT_TEST_DSN
    eng = create_async_engine(dsn, future=True)
    async with eng.begin() as conn:
        # Ensure pgcrypto for gen_random_uuid() on Topic/TopicSource defaults.
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    """Function-scoped sessionmaker bound to the test engine.

    We do NOT wrap in transaction-rollback isolation because the repository
    under test commits its own sessions. Tests truncate between cases via
    the `clean_tables` fixture below.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(request) -> AsyncIterator[None]:
    """Truncate topics + topic_sources before each repository test.

    Only triggers for repository integration tests so unit tests don't
    transitively depend on the engine fixture (and so don't need a DB).
    """
    if "test_sqlalchemy_topic_repository" not in request.node.nodeid:
        yield
        return
    eng = request.getfixturevalue("engine")
    async with eng.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE topic_sources, topics RESTART IDENTITY CASCADE"
        )
    yield
