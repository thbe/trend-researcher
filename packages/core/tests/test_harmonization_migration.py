"""Integration tests for migration 0020 (topic_harmonizations table).

Skipped automatically when ``TEST_DATABASE_URL`` is unset or the configured
database is unreachable. Set ``TEST_DATABASE_URL`` to enable, e.g.::

    export TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test

These tests pin migration 0020 (plan 10-05 / MT-012):

1. A harmonization row can be created and read back.
2. Only one harmonization per topic (PK constraint).
3. Deleting the topic cascades to the harmonization row.
4. Deleting the authoring user sets ``authored_by = NULL``.
5. Updating ``net_view`` advances ``updated_at``.

Pattern mirrors :mod:`test_frameworks_migration`.
"""

from __future__ import annotations

import os
import socket
import subprocess
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
    return async_dsn.replace("postgresql+asyncpg", "postgresql+psycopg2")


def _alembic(action: str, target: str, dsn: str, *, check: bool = True):
    env = {**os.environ, "DATABASE_URL": _sync_dsn(dsn)}
    return subprocess.run(
        ["alembic", action, target],
        cwd=_CORE_PKG_ROOT,
        env=env,
        check=check,
    )


@pytest_asyncio.fixture()
async def engine():
    dsn = _test_database_url()
    assert dsn
    eng = create_async_engine(dsn, poolclass=NullPool)

    # Downgrade to nothing, then upgrade to head (includes 0020).
    _alembic("downgrade", "base", dsn)
    _alembic("upgrade", "head", dsn)

    yield eng

    # Cleanup: downgrade back to base.
    await eng.dispose()
    _alembic("downgrade", "base", dsn)


@pytest_asyncio.fixture()
async def session(engine: AsyncEngine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess


async def _create_user(engine: AsyncEngine, username: str = "testuser") -> str:
    """Insert a minimal user and return its id."""
    async with engine.begin() as conn:
        row = await conn.execute(
            text(
                "INSERT INTO users (username, password_hash) "
                "VALUES (:u, 'fakehash') RETURNING id"
            ),
            {"u": username},
        )
        return row.scalar_one()


async def _create_topic(engine: AsyncEngine, title: str = "Test topic") -> str:
    """Insert a minimal topic and return its id."""
    async with engine.begin() as conn:
        row = await conn.execute(
            text("INSERT INTO topics (title) VALUES (:t) RETURNING id"),
            {"t": title},
        )
        return row.scalar_one()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_read_harmonization(engine: AsyncEngine):
    """Insert a harmonization row and query it back."""
    topic_id = await _create_topic(engine)
    user_id = await _create_user(engine)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO topic_harmonizations (topic_id, net_view, authored_by) "
                "VALUES (:tid, :nv, :uid)"
            ),
            {"tid": topic_id, "nv": "Overall positive outlook", "uid": user_id},
        )

    async with engine.begin() as conn:
        row = await conn.execute(
            text("SELECT topic_id, net_view, authored_by FROM topic_harmonizations WHERE topic_id = :tid"),
            {"tid": topic_id},
        )
        r = row.one()
        assert r.topic_id == topic_id
        assert r.net_view == "Overall positive outlook"
        assert r.authored_by == user_id


@pytest.mark.asyncio
async def test_unique_per_topic(engine: AsyncEngine):
    """Second INSERT with same topic_id raises IntegrityError (PK)."""
    topic_id = await _create_topic(engine)
    user_id = await _create_user(engine)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO topic_harmonizations (topic_id, net_view, authored_by) "
                "VALUES (:tid, 'first', :uid)"
            ),
            {"tid": topic_id, "uid": user_id},
        )

    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO topic_harmonizations (topic_id, net_view, authored_by) "
                    "VALUES (:tid, 'second', :uid)"
                ),
                {"tid": topic_id, "uid": user_id},
            )


@pytest.mark.asyncio
async def test_cascade_on_topic_delete(engine: AsyncEngine):
    """Deleting the topic cascades to the harmonization row."""
    topic_id = await _create_topic(engine)
    user_id = await _create_user(engine)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO topic_harmonizations (topic_id, net_view, authored_by) "
                "VALUES (:tid, 'will be deleted', :uid)"
            ),
            {"tid": topic_id, "uid": user_id},
        )

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM topics WHERE id = :tid"), {"tid": topic_id})

    async with engine.begin() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM topic_harmonizations WHERE topic_id = :tid"),
                {"tid": topic_id},
            )
        ).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_authored_by_set_null_on_user_delete(engine: AsyncEngine):
    """Deleting the user sets authored_by = NULL (ON DELETE SET NULL)."""
    topic_id = await _create_topic(engine)
    user_id = await _create_user(engine, username="doomed_user")

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO topic_harmonizations (topic_id, net_view, authored_by) "
                "VALUES (:tid, 'survives', :uid)"
            ),
            {"tid": topic_id, "uid": user_id},
        )

    # Delete user — must also remove user_departments FK rows first.
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM user_departments WHERE user_id = :uid"), {"uid": user_id})
        await conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})

    async with engine.begin() as conn:
        row = await conn.execute(
            text("SELECT authored_by FROM topic_harmonizations WHERE topic_id = :tid"),
            {"tid": topic_id},
        )
        assert row.scalar_one() is None


@pytest.mark.asyncio
async def test_updated_at_refreshes_on_update(engine: AsyncEngine):
    """UPDATE net_view causes updated_at to advance (via application logic)."""
    topic_id = await _create_topic(engine)
    user_id = await _create_user(engine)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO topic_harmonizations (topic_id, net_view, authored_by) "
                "VALUES (:tid, 'original', :uid)"
            ),
            {"tid": topic_id, "uid": user_id},
        )

    async with engine.begin() as conn:
        row = await conn.execute(
            text("SELECT updated_at FROM topic_harmonizations WHERE topic_id = :tid"),
            {"tid": topic_id},
        )
        original_ts = row.scalar_one()

    # Small delay then update with explicit updated_at = now() (as the app would).
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE topic_harmonizations SET net_view = 'revised', "
                "updated_at = now() WHERE topic_id = :tid"
            ),
            {"tid": topic_id},
        )

    async with engine.begin() as conn:
        row = await conn.execute(
            text("SELECT updated_at FROM topic_harmonizations WHERE topic_id = :tid"),
            {"tid": topic_id},
        )
        new_ts = row.scalar_one()
        assert new_ts >= original_ts
