"""Tests for ``core.seed.seed_frameworks`` — the bootstrap idempotency
guarantee for the assessment_frameworks registry.

Skipped automatically when ``TEST_DATABASE_URL`` is unset or unreachable.

The migration (0019) seeds the three system frameworks with
``prompt_version = 'v1'`` (a placeholder). The framework registry in
``services/assessor/src/assessor/domain/frameworks/`` ships the true
prompt_version strings (``'v4'`` / ``'swot.v1'`` / ``'pestle.v1'``) plus the
final json schemas. So the *first* call to ``seed_frameworks`` after a
migration must UPDATE all three rows; the *second* call must be a no-op
(``unchanged`` covers all three) — the idempotency contract specified by
plan 10-03 T03.

These tests use the registry's real ``all_definitions()`` so any drift
between migration-seed and code-defined metadata is caught here.
"""

from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.seed import seed_frameworks


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


def _alembic(action: str, target: str, dsn: str, *, check: bool = True) -> None:
    env = {**os.environ, "DATABASE_URL": _sync_dsn(dsn)}
    subprocess.run(
        ["alembic", action, target],
        cwd=_CORE_PKG_ROOT,
        env=env,
        check=check,
    )


def _load_registry_definitions() -> list[Any]:
    """Import the assessor framework registry lazily so this test module
    can still be collected when ``services/assessor`` is not installed in
    the active venv (the pytestmark above will skip before this is called
    in the no-DB case)."""
    from assessor.domain.frameworks import registry as framework_registry

    return list(framework_registry.all_definitions())


@dataclass
class _StubDef:
    """Local stub matching ``core.seed._FrameworkDef`` Protocol. Used for
    the mutation test where we need to alter one field without touching the
    real registry definitions."""

    key: str
    name: str
    description: str
    display_component: str
    prompt_version: str
    json_schema: dict


@pytest_asyncio.fixture(loop_scope="function")
async def migrated_engine() -> AsyncIterator[AsyncEngine]:
    dsn = _test_database_url()
    assert dsn is not None  # gated by pytestmark
    _alembic("downgrade", "base", dsn, check=False)
    _alembic("upgrade", "head", dsn)
    eng = create_async_engine(dsn, future=True, poolclass=NullPool)
    try:
        yield eng
    finally:
        await eng.dispose()
        _alembic("downgrade", "base", dsn)


@pytest_asyncio.fixture(loop_scope="function")
async def session_factory(
    migrated_engine: AsyncEngine,
) -> async_sessionmaker:
    return async_sessionmaker(migrated_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_seed_frameworks_idempotent(session_factory) -> None:
    """Migration-seeded rows differ from registry definitions on first run
    (migration uses ``prompt_version='v1'`` placeholder), so the first call
    must UPDATE all three. A second call must report every row unchanged."""
    definitions = _load_registry_definitions()
    assert len(definitions) == 3

    # First call: migration placeholders → registry truth. All 3 updated.
    async with session_factory() as session:
        first = await seed_frameworks(session, definitions)
    assert first.inserted == []
    assert sorted(first.updated) == ["pestle", "swot", "verdict"]
    assert first.unchanged == []

    # Second call: registry == DB. All 3 unchanged.
    async with session_factory() as session:
        second = await seed_frameworks(session, definitions)
    assert second.inserted == []
    assert second.updated == []
    assert sorted(second.unchanged) == ["pestle", "swot", "verdict"]


async def test_seed_frameworks_updates_on_mutation(session_factory) -> None:
    """Mutating one definition's description after reaching steady state
    causes only that key to appear in ``updated`` on the next call."""
    real_defs = _load_registry_definitions()

    # Bring DB to steady state first.
    async with session_factory() as session:
        await seed_frameworks(session, real_defs)
    async with session_factory() as session:
        baseline = await seed_frameworks(session, real_defs)
    assert sorted(baseline.unchanged) == ["pestle", "swot", "verdict"]

    # Build a parallel definition list where ``swot`` has a mutated
    # description; the other two match the registry verbatim.
    def _clone(d: Any, *, description: str | None = None) -> _StubDef:
        return _StubDef(
            key=d.key,
            name=d.name,
            description=description if description is not None else d.description,
            display_component=d.display_component,
            prompt_version=d.prompt_version,
            json_schema=d.json_schema,
        )

    mutated = [
        _clone(d, description="MUTATED description for test")
        if d.key == "swot"
        else _clone(d)
        for d in real_defs
    ]

    async with session_factory() as session:
        result = await seed_frameworks(session, mutated)
    assert result.inserted == []
    assert result.updated == ["swot"]
    assert sorted(result.unchanged) == ["pestle", "verdict"]
