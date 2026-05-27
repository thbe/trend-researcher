"""Integration tests for migration 0018 (per-department PATs).

Skipped automatically when ``TEST_DATABASE_URL`` is unset or the database
is unreachable. Pattern mirrors :mod:`test_scope_migration` — real
``alembic upgrade`` subprocesses against a live test DB.

Contracts under test (plan 10-02 T09):

1. Upgrade creates ``department_pats`` plus both indexes.
2. FK ``department_id`` has ``ON DELETE CASCADE`` — deleting the parent
   dept removes child PAT rows.
3. The partial unique index on ``(token_hash) WHERE revoked_at IS NULL``
   allows multiple *revoked* rows with the same hash, but rejects a
   second *active* row with that hash.
4. Downgrade drops the table cleanly.
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
from sqlalchemy.exc import IntegrityError, ProgrammingError
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


async def _seed_user(eng: AsyncEngine) -> str:
    """Seed a single user the PAT rows can reference via ``created_by``.

    Returns the user_id (UUID string)."""

    async with eng.begin() as conn:
        user_id = (
            await conn.execute(
                text(
                    """
                    INSERT INTO users
                        (username, password_hash, is_active, is_superadmin)
                    VALUES ('pat-test-user', 'unused', true, false)
                    RETURNING id
                    """
                )
            )
        ).scalar_one()
    return str(user_id)


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_engine() -> AsyncIterator[AsyncEngine]:
    """Per-test engine. Upgrades to head (0018), yields, teardown
    downgrades to base.
    """
    dsn = _test_database_url()
    assert dsn is not None
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


# --------------------------------------------------------------------------
# 1. Table + indexes exist after upgrade.
# --------------------------------------------------------------------------


async def test_table_and_indexes_present(migrated_session_factory) -> None:
    """``department_pats`` and both expected indexes exist after upgrade."""

    async with migrated_session_factory() as session:
        cols = (
            await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'department_pats' "
                    "ORDER BY ordinal_position"
                )
            )
        ).scalars().all()
        indexes = (
            await session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'department_pats' "
                    "ORDER BY indexname"
                )
            )
        ).scalars().all()
    assert set(cols) == {
        "id",
        "department_id",
        "name",
        "token_hash",
        "created_by",
        "created_at",
        "last_used_at",
        "revoked_at",
    }
    assert "ix_department_pats_department_id" in indexes
    assert "ix_department_pats_token_hash_active" in indexes


# --------------------------------------------------------------------------
# 2. ON DELETE CASCADE on departments → pats.
# --------------------------------------------------------------------------


async def test_department_delete_cascades_to_pats(
    migrated_engine: AsyncEngine,
    migrated_session_factory,
) -> None:
    """Deleting a department removes all its PAT rows (FK CASCADE)."""

    user_id = await _seed_user(migrated_engine)
    async with migrated_engine.begin() as conn:
        # Stand up an ephemeral dept we can DROP at will (Default is
        # protected by app code but not by SQL — still, use a fresh row).
        ephemeral_dept = (
            await conn.execute(
                text(
                    "INSERT INTO departments (name, slug) "
                    "VALUES ('PAT Cascade Test', 'pat-cascade-test') "
                    "RETURNING id"
                )
            )
        ).scalar_one()
        await conn.execute(
            text(
                """
                INSERT INTO department_pats
                    (department_id, name, token_hash, created_by)
                VALUES (:dept, 'cascade-pat', 'hash-cascade', :uid)
                """
            ),
            {"dept": str(ephemeral_dept), "uid": user_id},
        )
        await conn.execute(
            text("DELETE FROM departments WHERE id = :dept"),
            {"dept": str(ephemeral_dept)},
        )

    async with migrated_session_factory() as session:
        leftover = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM department_pats "
                    "WHERE department_id = :dept"
                ),
                {"dept": str(ephemeral_dept)},
            )
        ).scalar_one()
    assert leftover == 0


# --------------------------------------------------------------------------
# 3. Partial unique index — multiple revoked rows OK, two active rows NOT.
# --------------------------------------------------------------------------


async def test_partial_unique_allows_multiple_revoked_with_same_hash(
    migrated_engine: AsyncEngine,
) -> None:
    """Two revoked rows with identical ``token_hash`` insert cleanly —
    the partial unique only constrains active (revoked_at IS NULL) rows."""

    user_id = await _seed_user(migrated_engine)
    async with migrated_engine.begin() as conn:
        for i in range(2):
            await conn.execute(
                text(
                    """
                    INSERT INTO department_pats
                        (department_id, name, token_hash, created_by,
                         revoked_at)
                    VALUES (:dept, :name, 'shared-hash', :uid, now())
                    """
                ),
                {
                    "dept": DEFAULT_DEPARTMENT_ID,
                    "name": f"revoked-{i}",
                    "uid": user_id,
                },
            )
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM department_pats "
                    "WHERE token_hash = 'shared-hash'"
                )
            )
        ).scalar_one()
    assert count == 2


async def test_partial_unique_rejects_two_active_with_same_hash(
    migrated_engine: AsyncEngine,
) -> None:
    """A second ACTIVE row with the same hash raises IntegrityError."""

    user_id = await _seed_user(migrated_engine)
    async with migrated_engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO department_pats
                    (department_id, name, token_hash, created_by)
                VALUES (:dept, 'first', 'duplicate-hash', :uid)
                """
            ),
            {"dept": DEFAULT_DEPARTMENT_ID, "uid": user_id},
        )

    with pytest.raises(IntegrityError):
        async with migrated_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO department_pats
                        (department_id, name, token_hash, created_by)
                    VALUES (:dept, 'second', 'duplicate-hash', :uid)
                    """
                ),
                {"dept": DEFAULT_DEPARTMENT_ID, "uid": user_id},
            )


# --------------------------------------------------------------------------
# 4. Downgrade drops the table cleanly.
# --------------------------------------------------------------------------


async def test_downgrade_removes_table() -> None:
    """``alembic downgrade 0017`` drops ``department_pats`` entirely."""

    dsn = _test_database_url()
    assert dsn is not None
    _alembic("upgrade", "head", dsn)
    _alembic("downgrade", "0017", dsn)
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    try:
        with pytest.raises(ProgrammingError):
            async with eng.begin() as conn:
                await conn.execute(text("SELECT 1 FROM department_pats"))
    finally:
        await eng.dispose()
        # Restore for any subsequent test in the same run.
        _alembic("upgrade", "head", dsn)
        _alembic("downgrade", "base", dsn)
