"""Add owner department to crawl_config

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-29

Phase 10 follow-up: each crawl source now has an *owning* department.
``source_name`` stays globally unique (the crawler still fetches once per
source) but the row records which department is responsible for the
source. Owner dept members get full CRUD on their sources; other depts
may opt in to consume them via ``department_sources``.

Backfill strategy for existing rows:

1. Try ``slug='it'`` (matches the production IT dept).
2. Fall back to ``slug='default'`` (the seed dept that every fresh install
   provisions at UUID ``00000000-0000-0000-0000-000000000001``).
3. Fall back to the oldest department by ``created_at``.
4. If ``crawl_config`` has rows but no department exists at all, abort
   with a descriptive error — the operator must seed a department before
   re-running.

Downgrade drops the column and FK; existing ``department_sources`` rows
are unaffected.
"""

from __future__ import annotations

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add column NULL-able first so we can backfill cleanly.
    op.add_column(
        "crawl_config",
        sa.Column("department_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
    )

    # 2. Backfill existing rows.
    row_count = bind.execute(sa.text("SELECT COUNT(*) FROM crawl_config")).scalar() or 0
    if row_count > 0:
        owner_id = bind.execute(
            sa.text("SELECT id FROM departments WHERE slug = 'it' LIMIT 1")
        ).scalar()
        if owner_id is None:
            owner_id = bind.execute(
                sa.text("SELECT id FROM departments WHERE slug = 'default' LIMIT 1")
            ).scalar()
        if owner_id is None:
            owner_id = bind.execute(
                sa.text("SELECT id FROM departments ORDER BY created_at ASC LIMIT 1")
            ).scalar()
        if owner_id is None:
            raise RuntimeError(
                "Migration 0022 cannot proceed: crawl_config has rows but the "
                "departments table is empty. Seed a department (IT or default) "
                "and re-run."
            )

        bind.execute(
            sa.text("UPDATE crawl_config SET department_id = :owner WHERE department_id IS NULL"),
            {"owner": str(owner_id)},
        )

    # 3. Promote to NOT NULL + FK + index.
    op.alter_column("crawl_config", "department_id", nullable=False)
    op.create_foreign_key(
        "crawl_config_department_id_fkey",
        "crawl_config",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_crawl_config_department_id",
        "crawl_config",
        ["department_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_config_department_id", table_name="crawl_config")
    op.drop_constraint("crawl_config_department_id_fkey", "crawl_config", type_="foreignkey")
    op.drop_column("crawl_config", "department_id")
