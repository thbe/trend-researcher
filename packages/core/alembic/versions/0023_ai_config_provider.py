"""Add explicit ``provider`` column to ai_config

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-30

Replaces the fragile URL-sniffing heuristic in
``services/api/src/api/routes/assessment.py::_build_pipeline`` with an
explicit per-row choice. The heuristic mis-routed bare oMLX endpoints
(e.g. ``http://host.docker.internal:8000`` without a ``/v1`` suffix) to
the Ollama adapter because the matcher only looked for ``/v1`` or
``openai`` substrings.

Backfill strategy for existing rows:

- ``anthropic`` if ``base_url`` contains ``anthropic`` (case-insensitive).
- ``openai`` if ``base_url`` contains ``openai`` OR ``/v1`` OR the host
  matches a well-known OpenAI-compatible local-inference port we use
  internally (8000 = oMLX, 1234 = LM Studio default, 8080 = llama.cpp /
  vLLM common default). Operators on non-standard ports must edit the
  row by hand after migration.
- ``ollama`` as the safe fallback (matches the historical default
  ``http://ollama:11434``).

Downgrade simply drops the column — adapter dispatch then falls back to
the legacy URL heuristic, which still works for properly-suffixed URLs.
"""

from __future__ import annotations

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add nullable so we can backfill.
    op.add_column(
        "ai_config",
        sa.Column("provider", sa.Text(), nullable=True),
    )

    # 2. Backfill from existing base_url.
    bind.execute(
        sa.text(
            """
            UPDATE ai_config SET provider = CASE
              WHEN lower(base_url) LIKE '%anthropic%' THEN 'anthropic'
              WHEN lower(base_url) LIKE '%openai%'    THEN 'openai'
              WHEN lower(base_url) LIKE '%/v1%'       THEN 'openai'
              WHEN base_url ~ ':(8000|1234|8080)(/|$)' THEN 'openai'
              ELSE 'ollama'
            END
            WHERE provider IS NULL
            """
        )
    )

    # 3. Promote to NOT NULL with server-side default for future inserts.
    op.alter_column(
        "ai_config",
        "provider",
        nullable=False,
        server_default="ollama",
    )


def downgrade() -> None:
    op.drop_column("ai_config", "provider")
