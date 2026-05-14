"""Alembic environment for ``packages/core``.

Schema is owned exclusively by this package (locked architectural decision).
The async engine and target metadata are sourced from :mod:`core.db` and
:mod:`core.models` respectively, so the migration tree always matches the ORM
models in this workspace.

The connection URL comes from ``DATABASE_URL`` (via :mod:`core.config`), not
from ``alembic.ini``. Set it before running ``alembic`` commands, e.g.
``cp .env.example .env`` then ``export $(grep -v '^#' .env | xargs)``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy.engine import Connection

from alembic import context

from core.config import get_settings
from core.db import get_engine
from core.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate — every Base subclass in core.models is
# registered here.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Uses ``DATABASE_URL`` from the environment (via :func:`get_settings`) so
    the offline path matches the online path.
    """

    url = get_settings().database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Build the async engine from :mod:`core.db` and run migrations."""

    connectable = get_engine(get_settings().database_url)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
