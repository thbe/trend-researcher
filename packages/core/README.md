# core

Shared domain types, database models, and Alembic migrations for Trend Researcher.

This package owns the v1 Postgres schema for every service in the workspace
(locked architectural decision — see `ARC-003` in `.planning/REQUIREMENTS.md`).

## Running Alembic

`alembic` reads its connection URL from the `DATABASE_URL` environment
variable via `core.config.get_settings`, **not** from `alembic.ini`. Set it
before running any `alembic` command:

```bash
cp .env.example .env                       # at repo root
export $(grep -v '^#' ../../.env | xargs)  # or use direnv / dotenv-cli
cd packages/core
uv run alembic upgrade head
```

Without `DATABASE_URL` set, `alembic current` / `upgrade` will fail with a
pydantic validation error.
