"""crawl_runs operational telemetry table

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-16

Adds the ``crawl_runs`` table — one row per ``crawler run-once`` invocation,
written at the end of :func:`crawler.app.orchestrator.run_once` and read by
the api ``GET /runs`` endpoint and ``scripts/smoke_phase3.sh``.

This is operational telemetry only (no PII / credentials / user content).
``failed_sources`` is a Postgres ``text[]`` (not JSONB) so SQL filters like
``cardinality(failed_sources) > 0`` work directly. ``per_source`` is JSONB
because its shape is per-source-keyed and not queried structurally in v1.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "finished_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("top_n", sa.Integer(), nullable=False),
        sa.Column(
            "totals_fetched",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "totals_inserted",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "totals_updated",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "totals_skipped_within_run",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "totals_errors",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "per_source",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "failed_sources",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_crawl_runs_started_at", "crawl_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_crawl_runs_started_at", table_name="crawl_runs")
    op.drop_table("crawl_runs")
