"""Integration tests for migration 0016 (departments + RBAC + default seed).

Skipped automatically when ``TEST_DATABASE_URL`` is unset or the configured
database is unreachable. Set ``TEST_DATABASE_URL`` to enable, e.g.::

    export TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test

These tests pin the multi-tenant primitives shipped in migration 0016
(plan 10-01 / MT-001 + MT-002 + MT-008):

1. The Default department is seeded with the hardcoded UUID
   ``00000000-0000-0000-0000-000000000001`` and slug ``default``.
2. All pre-existing users are promoted to ``is_superadmin = true`` (the
   "single-tenant operator becomes superadmin" interpretation). Users
   inserted post-migration default to ``is_superadmin = false``.
3. Every pre-existing user gets a ``user_departments`` row with
   ``role = 'dept_lead'`` linking them to the Default department.
4. The ``user_departments.role`` CHECK rejects values outside
   ``{viewer, analyst, dept_lead}``.
5. The ``departments.slug`` CHECK rejects upper-case / whitespace slugs.
6. ``ON DELETE CASCADE`` removes ``user_departments`` rows when either side
   (user or department) is deleted.

Unlike :mod:`test_topic_stats_view` (which builds the schema via
``Base.metadata.create_all`` + raw view SQL), these tests run real
``alembic upgrade head`` against a clean test DB so we exercise the
seed-INSERTs literally as they will run in production.
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


def _run_alembic(action: str, dsn: str) -> None:
    """Invoke ``alembic`` as a subprocess against the test DSN.

    Using a subprocess (rather than alembic.command in-process) keeps the
    test isolated from any global Alembic state and matches how operators
    actually run migrations in production.
    """
    env = {**os.environ, "DATABASE_URL": _sync_dsn(dsn)}
    subprocess.run(
        ["alembic", action] if action == "upgrade" else ["alembic", action],
        cwd=_CORE_PKG_ROOT,
        env=env,
        check=True,
    )


def _alembic_upgrade_head(dsn: str) -> None:
    env = {**os.environ, "DATABASE_URL": _sync_dsn(dsn)}
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=_CORE_PKG_ROOT,
        env=env,
        check=True,
    )


def _alembic_downgrade_base(dsn: str) -> None:
    env = {**os.environ, "DATABASE_URL": _sync_dsn(dsn)}
    subprocess.run(
        ["alembic", "downgrade", "base"],
        cwd=_CORE_PKG_ROOT,
        env=env,
        check=True,
    )


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_engine() -> AsyncIterator[AsyncEngine]:
    """Per-test engine that runs ``alembic upgrade head`` then tears down.

    Each test gets a fresh schema so seed-row assertions are deterministic
    regardless of test ordering. The downgrade-base at teardown leaves the
    DB empty for the next test.
    """
    dsn = _test_database_url()
    assert dsn is not None  # gated by pytestmark
    # Insert a pre-existing user BEFORE migrating so we can assert that
    # the seed UPDATE promotes existing users to superadmin and the seed
    # INSERT links them to Default.
    #
    # Trick: run upgrade to 0015 first, insert the user, then upgrade to
    # 0016 head. That mimics the prod migration moment.
    env = {**os.environ, "DATABASE_URL": _sync_dsn(dsn)}
    subprocess.run(
        ["alembic", "upgrade", "0015"],
        cwd=_CORE_PKG_ROOT,
        env=env,
        check=True,
    )
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (username, password_hash) "
                "VALUES ('preexisting', 'bcrypt$dummy')"
            )
        )
    await eng.dispose()
    # Now run the 0016 migration on top.
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=_CORE_PKG_ROOT,
        env=env,
        check=True,
    )
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    try:
        yield eng
    finally:
        await eng.dispose()
        # Drop everything for the next test.
        _alembic_downgrade_base(dsn)


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_session_factory(
    migrated_engine: AsyncEngine,
) -> async_sessionmaker:
    return async_sessionmaker(migrated_engine, expire_on_commit=False)


async def test_default_department_seeded(migrated_session_factory) -> None:
    """One row in departments with slug='default' and the hardcoded UUID."""
    async with migrated_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, slug FROM departments "
                    "WHERE slug = 'default'"
                )
            )
        ).mappings().all()
    assert len(rows) == 1
    assert rows[0]["id"] == DEFAULT_DEPARTMENT_ID
    assert rows[0]["name"] == "Default"


async def test_seed_user_promoted_to_superadmin(
    migrated_session_factory,
) -> None:
    """Every pre-existing user becomes superadmin; new users default false."""
    async with migrated_session_factory() as session:
        # Pre-existing users (inserted by the fixture before 0016 ran) are
        # all superadmin now.
        existing = (
            await session.execute(
                text(
                    "SELECT username, is_superadmin FROM users "
                    "WHERE username = 'preexisting'"
                )
            )
        ).mappings().one()
        assert existing["is_superadmin"] is True

        # A brand-new user inserted POST-migration defaults to false.
        await session.execute(
            text(
                "INSERT INTO users (username, password_hash) "
                "VALUES ('post_migration_user', 'bcrypt$x')"
            )
        )
        await session.commit()
        fresh = (
            await session.execute(
                text(
                    "SELECT is_superadmin FROM users "
                    "WHERE username = 'post_migration_user'"
                )
            )
        ).mappings().one()
        assert fresh["is_superadmin"] is False


async def test_user_departments_seeded_for_existing_users(
    migrated_session_factory,
) -> None:
    """Each pre-existing user gets a dept_lead row in Default."""
    async with migrated_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT ud.role, ud.department_id "
                    "FROM user_departments ud "
                    "JOIN users u ON u.id = ud.user_id "
                    "WHERE u.username = 'preexisting'"
                )
            )
        ).mappings().one()
        assert row["role"] == "dept_lead"
        assert row["department_id"] == DEFAULT_DEPARTMENT_ID


async def test_role_check_constraint(migrated_session_factory) -> None:
    """Inserting role='admin' violates the CHECK constraint."""
    async with migrated_session_factory() as session:
        user_id = (
            await session.execute(
                text(
                    "SELECT id FROM users WHERE username = 'preexisting'"
                )
            )
        ).scalar_one()
    with pytest.raises(IntegrityError) as exc_info:
        async with migrated_session_factory() as session:
            # Delete the seeded membership first so we're hitting the role
            # CHECK and not the composite PK uniqueness.
            await session.execute(
                text(
                    "DELETE FROM user_departments WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
            await session.execute(
                text(
                    "INSERT INTO user_departments "
                    "(user_id, department_id, role) "
                    "VALUES (:uid, :did, 'admin')"
                ),
                {"uid": user_id, "did": DEFAULT_DEPARTMENT_ID},
            )
            await session.commit()
    assert "ck_user_departments_role" in str(exc_info.value).lower() or \
        "check" in str(exc_info.value).lower()


async def test_slug_format_check(migrated_session_factory) -> None:
    """Inserting slug='Bad Slug' violates the slug-format CHECK."""
    with pytest.raises(IntegrityError) as exc_info:
        async with migrated_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO departments (name, slug) "
                    "VALUES ('Bad', 'Bad Slug')"
                )
            )
            await session.commit()
    assert "ck_departments_slug_format" in str(exc_info.value).lower() or \
        "check" in str(exc_info.value).lower()


async def test_user_cascade_deletes_user_departments(
    migrated_session_factory,
) -> None:
    """Deleting a user removes its user_departments rows."""
    async with migrated_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO users (username, password_hash) "
                "VALUES ('cascade_user', 'x')"
            )
        )
        await session.commit()
        uid = (
            await session.execute(
                text("SELECT id FROM users WHERE username = 'cascade_user'")
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO user_departments (user_id, department_id, role) "
                "VALUES (:uid, :did, 'viewer')"
            ),
            {"uid": uid, "did": DEFAULT_DEPARTMENT_ID},
        )
        await session.commit()
        await session.execute(
            text("DELETE FROM users WHERE id = :uid"), {"uid": uid}
        )
        await session.commit()
        remaining = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM user_departments "
                    "WHERE user_id = :uid"
                ),
                {"uid": uid},
            )
        ).scalar_one()
        assert remaining == 0


async def test_department_cascade_deletes_user_departments(
    migrated_session_factory,
) -> None:
    """Deleting a department removes its user_departments rows."""
    async with migrated_session_factory() as session:
        # Make a throwaway department + membership; don't touch Default
        # (some other tests assume it's there).
        await session.execute(
            text(
                "INSERT INTO departments (name, slug) "
                "VALUES ('Throwaway', 'throwaway')"
            )
        )
        await session.commit()
        did = (
            await session.execute(
                text("SELECT id FROM departments WHERE slug = 'throwaway'")
            )
        ).scalar_one()
        uid = (
            await session.execute(
                text("SELECT id FROM users WHERE username = 'preexisting'")
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO user_departments (user_id, department_id, role) "
                "VALUES (:uid, :did, 'analyst')"
            ),
            {"uid": uid, "did": did},
        )
        await session.commit()
        await session.execute(
            text("DELETE FROM departments WHERE id = :did"), {"did": did}
        )
        await session.commit()
        remaining = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM user_departments "
                    "WHERE department_id = :did"
                ),
                {"did": did},
            )
        ).scalar_one()
        assert remaining == 0
