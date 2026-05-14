"""Async SQLAlchemy engine + session factory for the shared topic store."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings


def get_engine(database_url: str | None = None) -> AsyncEngine:
    """Build an async SQLAlchemy engine bound to asyncpg.

    Parameters
    ----------
    database_url:
        Optional explicit URL. When ``None``, falls back to
        :func:`core.config.get_settings`. The URL must use the
        ``postgresql+asyncpg://`` driver.
    """

    url = database_url if database_url is not None else get_settings().database_url
    return create_async_engine(url, future=True)


def get_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an :class:`async_sessionmaker` bound to ``engine``."""

    return async_sessionmaker(engine, expire_on_commit=False)


__all__ = ["get_engine", "get_sessionmaker"]
