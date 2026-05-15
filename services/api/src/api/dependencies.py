"""DI wiring for the api service.

Lazy module-level engine + sessionmaker, built on first use, so importing
``api.main`` does NOT touch the database (tests can patch ``core.get_settings``
before the first request). FastAPI ``Depends(get_session)`` yields an
``AsyncSession`` per request and closes it on completion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import core

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    """Return the lazily-built process-wide engine."""

    global _engine
    if _engine is None:
        _engine = core.get_engine(core.get_settings().database_url)
    return _engine


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the lazily-built process-wide sessionmaker."""

    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = core.get_sessionmaker(_get_engine())
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield one ``AsyncSession`` per request."""

    sessionmaker = _get_sessionmaker()
    async with sessionmaker() as session:
        yield session


async def dispose_engine() -> None:
    """Tear down the process-wide engine (FastAPI lifespan shutdown).

    Idempotent: safe to call when no engine was ever built (e.g. import-only
    test runs). Resets the module-level singletons so a subsequent request
    rebuilds cleanly — useful when tests patch settings between cases.
    """

    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


__all__ = ["dispose_engine", "get_session"]
