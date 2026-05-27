"""Scope existing tables per-department + department_sources + drop crawl_config.enabled

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-27

Plan 10-02 (Phase 10 — Multi-Tenant Market Intelligence Platform).
Requirements: MT-003 (topics stay global), MT-004 (per-dept ai_config),
MT-006 (per-dept source subscription), MT-008 (single-tenant data migrates
cleanly to Default), MT-009 (per-dept business_cases + assessment_jobs).

Schema reshapes (single transaction):

1. **Pre-check** ``business_cases`` for duplicate (topic_id, prompt_version,
   model_used) rows. Raise RuntimeError with operator-actionable message if
   any exist — otherwise the future UNIQUE constraint in 10-03 would silently
   break this migration.

2. **Create ``department_sources``** — per-(department, source_name)
   subscription with ``enabled`` flag. PK ``(department_id, source_name)``.
   Index on ``source_name`` for the crawler's union query.

3. **Backfill ``department_sources``** by copying every existing
   ``crawl_config`` row into a Default-dept subscription with the same
   ``enabled`` value (preserves single-tenant behaviour post-upgrade).

4. **Drop ``crawl_config.enabled``** — single source of truth is now
   ``department_sources``. Other crawl_config columns (top_n, capture_summary,
   verify_ssl, feed_url) stay — they are technical per-source config, not
   tenant preference.

5. **Reshape ``ai_config``** PK from ``key`` → ``department_id`` via
   create_new / copy / drop / rename. Preserves every existing column
   (base_url, model, api_token, business_context, opportunity_criteria,
   risk_criteria, thinking_effort, request_timeout_seconds, updated_at).
   The pre-existing ``key='default'`` row is copied to Default dept's id.

6. **Extend ``business_cases``** with ``department_id`` FK + backfill all
   existing rows to Default + add ``NOT NULL`` + index. The composite
   UNIQUE ``(topic_id, department_id, framework_id, prompt_version,
   model_used)`` is DEFERRED to 10-03 (needs framework_id to exist).

7. **Extend ``assessment_jobs``** with ``department_id`` FK + backfill +
   ``NOT NULL`` + index. Same pattern.

Downgrade reverses every step. For step 5 (ai_config reshape), per-department
configs collapse into Default's single row — operator's manual problem if
they actually had >1 dept configured (this is a single-tenant downgrade).
"""

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP


# Hardcoded UUID for the Default department, matching migration 0016.
DEFAULT_DEPARTMENT_ID = "00000000-0000-0000-0000-000000000001"


_DUPLICATE_BC_MSG = (
    "Found duplicate business_cases rows on (topic_id, prompt_version, "
    "model_used). The 10-03 UNIQUE constraint cannot be added until these "
    "are deduplicated. Inspect with: "
    "SELECT topic_id, prompt_version, model_used, COUNT(*) "
    "FROM business_cases "
    "GROUP BY topic_id, prompt_version, model_used HAVING COUNT(*) > 1;"
)


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Pre-check business_cases for duplicates ------------------------
    result = conn.execute(
        sa.text(
            """
            SELECT topic_id, prompt_version, model_used, COUNT(*) AS c
            FROM business_cases
            GROUP BY topic_id, prompt_version, model_used
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).fetchone()
    if result is not None:
        raise RuntimeError(_DUPLICATE_BC_MSG)

    # 2. department_sources table ---------------------------------------
    op.create_table(
        "department_sources",
        sa.Column(
            "department_id",
            UUID(as_uuid=False),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("source_name", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_department_sources_source_name",
        "department_sources",
        ["source_name"],
    )

    # 3. Backfill department_sources from crawl_config -------------------
    op.execute(
        sa.text(
            """
            INSERT INTO department_sources (department_id, source_name, enabled)
            SELECT :dept_id, source_name, enabled FROM crawl_config
            """
        ).bindparams(dept_id=DEFAULT_DEPARTMENT_ID)
    )

    # 4. Drop crawl_config.enabled --------------------------------------
    op.drop_column("crawl_config", "enabled")

    # 5. Reshape ai_config: PK key -> department_id ---------------------
    op.create_table(
        "ai_config_new",
        sa.Column(
            "department_id",
            UUID(as_uuid=False),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "base_url",
            sa.Text(),
            nullable=False,
            server_default="http://ollama:11434",
        ),
        sa.Column(
            "model",
            sa.Text(),
            nullable=False,
            server_default="qwen3.5:latest",
        ),
        sa.Column("api_token", sa.Text(), nullable=True),
        sa.Column("business_context", sa.Text(), nullable=True),
        sa.Column("opportunity_criteria", sa.Text(), nullable=True),
        sa.Column("risk_criteria", sa.Text(), nullable=True),
        sa.Column(
            "thinking_effort", sa.Text(), nullable=False, server_default="low"
        ),
        sa.Column(
            "request_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO ai_config_new (
                department_id, base_url, model, api_token, business_context,
                opportunity_criteria, risk_criteria, thinking_effort,
                request_timeout_seconds, updated_at
            )
            SELECT
                :dept_id, base_url, model, api_token, business_context,
                opportunity_criteria, risk_criteria, thinking_effort,
                request_timeout_seconds, updated_at
            FROM ai_config WHERE key = 'default'
            """
        ).bindparams(dept_id=DEFAULT_DEPARTMENT_ID)
    )
    op.drop_table("ai_config")
    op.rename_table("ai_config_new", "ai_config")

    # 6. business_cases.department_id -----------------------------------
    op.add_column(
        "business_cases",
        sa.Column(
            "department_id",
            UUID(as_uuid=False),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE business_cases SET department_id = :dept_id"
        ).bindparams(dept_id=DEFAULT_DEPARTMENT_ID)
    )
    op.alter_column("business_cases", "department_id", nullable=False)
    op.create_index(
        "ix_business_cases_department_id",
        "business_cases",
        ["department_id"],
    )

    # 7. assessment_jobs.department_id ----------------------------------
    op.add_column(
        "assessment_jobs",
        sa.Column(
            "department_id",
            UUID(as_uuid=False),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE assessment_jobs SET department_id = :dept_id"
        ).bindparams(dept_id=DEFAULT_DEPARTMENT_ID)
    )
    op.alter_column("assessment_jobs", "department_id", nullable=False)
    op.create_index(
        "ix_assessment_jobs_department_id",
        "assessment_jobs",
        ["department_id"],
    )


def downgrade() -> None:
    # 7. assessment_jobs.department_id ----------------------------------
    op.drop_index(
        "ix_assessment_jobs_department_id", table_name="assessment_jobs"
    )
    op.drop_column("assessment_jobs", "department_id")

    # 6. business_cases.department_id -----------------------------------
    op.drop_index(
        "ix_business_cases_department_id", table_name="business_cases"
    )
    op.drop_column("business_cases", "department_id")

    # 5. Reverse ai_config reshape: department_id -> key ----------------
    op.create_table(
        "ai_config_old",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column(
            "base_url",
            sa.Text(),
            nullable=False,
            server_default="http://ollama:11434",
        ),
        sa.Column(
            "model",
            sa.Text(),
            nullable=False,
            server_default="qwen3.5:latest",
        ),
        sa.Column("api_token", sa.Text(), nullable=True),
        sa.Column("business_context", sa.Text(), nullable=True),
        sa.Column("opportunity_criteria", sa.Text(), nullable=True),
        sa.Column("risk_criteria", sa.Text(), nullable=True),
        sa.Column(
            "thinking_effort", sa.Text(), nullable=False, server_default="low"
        ),
        sa.Column(
            "request_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Pick the Default dept's row if present, else first row, else default
    # values. Per-dept configs (other than Default) are lost on downgrade —
    # documented in the module docstring.
    op.execute(
        sa.text(
            """
            INSERT INTO ai_config_old (
                key, base_url, model, api_token, business_context,
                opportunity_criteria, risk_criteria, thinking_effort,
                request_timeout_seconds, updated_at
            )
            SELECT
                'default', base_url, model, api_token, business_context,
                opportunity_criteria, risk_criteria, thinking_effort,
                request_timeout_seconds, updated_at
            FROM ai_config
            ORDER BY (department_id = :dept_id) DESC
            LIMIT 1
            """
        ).bindparams(dept_id=DEFAULT_DEPARTMENT_ID)
    )
    op.drop_table("ai_config")
    op.rename_table("ai_config_old", "ai_config")

    # 4. Restore crawl_config.enabled -----------------------------------
    op.add_column(
        "crawl_config",
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    # Restore enabled state from Default dept's subscriptions where present.
    op.execute(
        sa.text(
            """
            UPDATE crawl_config cc
            SET enabled = ds.enabled
            FROM department_sources ds
            WHERE ds.source_name = cc.source_name
              AND ds.department_id = :dept_id
            """
        ).bindparams(dept_id=DEFAULT_DEPARTMENT_ID)
    )

    # 3 / 2. Drop department_sources ------------------------------------
    op.drop_index(
        "ix_department_sources_source_name", table_name="department_sources"
    )
    op.drop_table("department_sources")
