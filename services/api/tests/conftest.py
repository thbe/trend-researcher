"""Shared fixtures for the api test suite.

DB-touching tests (eg. ``/healthz`` happy path, ``/runs`` ordering) skip-gate
on ``TEST_DATABASE_URL`` + a 0.5s TCP probe to its host:port — same idiom as
the crawler suite (see ``services/crawler/tests/conftest.py``) so a developer
without local Postgres still gets a green run from the pure-FastAPI tests.

The ``client`` fixture wraps the in-process ASGI app via ``ASGITransport`` so
no actual port is bound; tests can hit routes via plain ``await client.get``
without spinning up uvicorn.

Phase 10 additions (MT-001 / MT-002):
- :func:`seeded_db` provisions two departments (``Default`` + ``Other``) and
  three users with controlled roles, returning a small dataclass for assertions.
- :func:`make_authed_client` returns an ``AsyncClient`` whose session cookie is
  signed for the requested username so tests can switch identities without
  reseeding.
"""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import core
from api import dependencies as deps
from api.auth.middleware import COOKIE_NAME, create_session_cookie
from api.main import app
from core.models import Base, Department, User, UserDepartment


_TEST_SECRET = "dev-secret-change-in-production"


def _test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


def _can_reach(dsn: str) -> bool:
    """0.5s TCP probe so the suite skips cleanly when Postgres isn't up."""

    parsed = urlparse(dsn.replace("postgresql+asyncpg", "postgresql"))
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def db_available() -> bool:
    """True when ``TEST_DATABASE_URL`` is set AND its host:port is reachable."""

    dsn = _test_database_url()
    return dsn is not None and _can_reach(dsn)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """In-process ASGI client — no uvicorn, no real port.

    Injects a valid session cookie for the legacy ``test-user`` so protected
    routes are accessible to suites that predate the Phase 10 dept fixtures.
    """

    transport = ASGITransport(app=app)
    cookie = create_session_cookie("test-user", _TEST_SECRET, 24)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={COOKIE_NAME: cookie},
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Phase 10 fixtures: seeded departments + per-identity client factory
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeededDb:
    """Handles returned by :func:`seeded_db` for assertions in dept tests.

    Attributes
    ----------
    default_dept_id, other_dept_id:
        UUID strings for the two seeded departments. ``default`` matches the
        slug guarded by the API (cannot be deleted, etc.).
    superadmin, lead_a, analyst_a, viewer_b:
        Username strings; their User rows are seeded with
        ``password_hash='unused'``. ``superadmin`` is the only superadmin.
        ``lead_a`` is dept_lead of Default. ``analyst_a`` is analyst of Default
        AND viewer of Other (multi-dept membership). ``viewer_b`` is viewer of
        Other only.
    user_ids:
        ``{username: user_id}`` mapping — needed for member-management
        endpoints that take UUID path params.
    """

    default_dept_id: str
    other_dept_id: str
    superadmin: str
    lead_a: str
    analyst_a: str
    viewer_b: str
    user_ids: dict[str, str]


def _reset_dep_singletons() -> None:
    deps._engine = None
    deps._sessionmaker = None


@pytest_asyncio.fixture
async def seeded_db(monkeypatch) -> AsyncIterator[SeededDb]:
    """Seed 2 depts + 4 users with controlled roles; tear down on exit.

    Uses ``Base.metadata.create_all`` (not Alembic) for speed — the schema
    shape is identical because models.py is the single source of truth that
    migration 0016 conforms to. The seed inserts are done with ORM rows so
    composite-PK + CHECK constraints are exercised end-to-end.
    """

    if not db_available():
        pytest.skip("set TEST_DATABASE_URL to a reachable Postgres")

    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("AUTH_SECRET_KEY", _TEST_SECRET)
    _reset_dep_singletons()

    engine = core.get_engine(os.environ["TEST_DATABASE_URL"])
    sessionmaker = core.get_sessionmaker(engine)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        # Defensive: drop anything left from a prior partial run, then create.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    default_id = "00000000-0000-0000-0000-000000000001"
    other_id = str(uuid.uuid4())
    users = {
        "phase10-super": str(uuid.uuid4()),
        "phase10-lead-a": str(uuid.uuid4()),
        "phase10-analyst-a": str(uuid.uuid4()),
        "phase10-viewer-b": str(uuid.uuid4()),
    }

    async with sessionmaker() as session:
        session.add_all(
            [
                Department(id=default_id, name="Default", slug="default"),
                Department(id=other_id, name="Other", slug="other"),
                User(
                    id=users["phase10-super"],
                    username="phase10-super",
                    password_hash="unused",
                    is_active=True,
                    is_superadmin=True,
                ),
                User(
                    id=users["phase10-lead-a"],
                    username="phase10-lead-a",
                    password_hash="unused",
                    is_active=True,
                    is_superadmin=False,
                ),
                User(
                    id=users["phase10-analyst-a"],
                    username="phase10-analyst-a",
                    password_hash="unused",
                    is_active=True,
                    is_superadmin=False,
                ),
                User(
                    id=users["phase10-viewer-b"],
                    username="phase10-viewer-b",
                    password_hash="unused",
                    is_active=True,
                    is_superadmin=False,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                UserDepartment(
                    user_id=users["phase10-lead-a"],
                    department_id=default_id,
                    role="dept_lead",
                ),
                UserDepartment(
                    user_id=users["phase10-analyst-a"],
                    department_id=default_id,
                    role="analyst",
                ),
                UserDepartment(
                    user_id=users["phase10-analyst-a"],
                    department_id=other_id,
                    role="viewer",
                ),
                UserDepartment(
                    user_id=users["phase10-viewer-b"],
                    department_id=other_id,
                    role="viewer",
                ),
            ]
        )
        await session.commit()

    try:
        yield SeededDb(
            default_dept_id=default_id,
            other_dept_id=other_id,
            superadmin="phase10-super",
            lead_a="phase10-lead-a",
            analyst_a="phase10-analyst-a",
            viewer_b="phase10-viewer-b",
            user_ids=users,
        )
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
        _reset_dep_singletons()


ClientFactory = Callable[..., Awaitable[AsyncClient]]


@pytest_asyncio.fixture
async def make_authed_client() -> AsyncIterator[ClientFactory]:
    """Factory: return an ``AsyncClient`` cookied as the requested user.

    Usage::

        client = await make_authed_client("phase10-lead-a", active_dept=dept_id)

    Pass ``active_dept`` to inject the ``X-Active-Department`` header on every
    request (the active-department dependency reads it). Created clients are
    auto-closed on fixture teardown.
    """

    opened: list[AsyncClient] = []

    async def _make(
        username: str, *, active_dept: str | None = None
    ) -> AsyncClient:
        transport = ASGITransport(app=app)
        cookie = create_session_cookie(username, _TEST_SECRET, 24)
        headers: dict[str, str] = {}
        if active_dept is not None:
            headers["X-Active-Department"] = active_dept
        c = AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={COOKIE_NAME: cookie},
            headers=headers,
        )
        opened.append(c)
        return c

    try:
        yield _make
    finally:
        for c in opened:
            await c.aclose()


__all__ = ["SeededDb", "client", "db_available", "make_authed_client", "seeded_db"]
