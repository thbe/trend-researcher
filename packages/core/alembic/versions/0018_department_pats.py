"""Per-department Personal Access Tokens (PATs)

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-27

Plan 10-02, T09 (Phase 10 — Multi-Tenant Market Intelligence Platform).

Introduces ``department_pats`` so each department's lead can mint its own
bearer tokens for the dept-scoped internal crawl endpoint
(``POST /api/internal/departments/{dept_slug}/crawl``) without sharing the
global ``TREND_INTERNAL_PAT`` env secret used by the legacy
``/api/internal/crawl`` route (which stays).

Schema:

- ``id``           uuid PK (server-side ``gen_random_uuid()``)
- ``department_id`` FK ``departments(id)`` ON DELETE CASCADE, NOT NULL
- ``name``         text, NOT NULL (human label, e.g. "Cloud Scheduler")
- ``token_hash``   text NOT NULL — SHA-256 hex of the plaintext token; the
                   plaintext is shown to the operator exactly once at
                   creation time and never persisted.
- ``created_by``   FK ``users(id)`` NOT NULL — the user who minted it.
- ``created_at``   timestamptz NOT NULL default now()
- ``last_used_at`` timestamptz NULL — updated on every successful auth.
- ``revoked_at``   timestamptz NULL — soft-delete tombstone; auth refuses
                   any token whose row has a non-NULL revoked_at.

Partial unique index ``(token_hash) WHERE revoked_at IS NULL`` enforces that
no two *active* PATs share a hash (collision space is effectively zero
given 256 bits, but the constraint makes the auth lookup unambiguous).
Revoked rows are kept indefinitely for audit and may share a hash with a
later-minted active PAT without breaking the constraint.

Downgrade drops the index then the table.
"""

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP


def upgrade() -> None:
    op.create_table(
        "department_pats",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "department_id",
            UUID(as_uuid=False),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_department_pats_department_id",
        "department_pats",
        ["department_id"],
    )
    op.create_index(
        "ix_department_pats_token_hash_active",
        "department_pats",
        ["token_hash"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_department_pats_token_hash_active", table_name="department_pats"
    )
    op.drop_index(
        "ix_department_pats_department_id", table_name="department_pats"
    )
    op.drop_table("department_pats")
