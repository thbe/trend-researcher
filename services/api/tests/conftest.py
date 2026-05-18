"""Shared fixtures for the api test suite.

DB-touching tests (eg. ``/healthz`` happy path, ``/runs`` ordering) skip-gate
on ``TEST_DATABASE_URL`` + a 0.5s TCP probe to its host:port — same idiom as
the crawler suite (see ``services/crawler/tests/conftest.py``) so a developer
without local Postgres still gets a green run from the pure-FastAPI tests.

The ``client`` fixture wraps the in-process ASGI app via ``ASGITransport`` so
no actual port is bound; tests can hit routes via plain ``await client.get``
without spinning up uvicorn.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.auth.middleware import COOKIE_NAME, create_session_cookie
from api.main import app


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

    Injects a valid session cookie so protected routes are accessible.
    """

    transport = ASGITransport(app=app)
    cookie = create_session_cookie("test-user", "dev-secret-change-in-production", 24)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={COOKIE_NAME: cookie},
    ) as c:
        yield c


__all__ = ["client", "db_available"]
