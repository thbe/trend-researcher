"""Topic harmonizations (cross-department Net View annotation)

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-28

Plan 10-05, T01 (Phase 10 — Multi-Tenant Market Intelligence Platform).
Requirements: MT-011 (cross-department side-by-side view), MT-012 (Net View
annotation).

Schema:

- ``topic_id``    uuid PK, FK ``topics(id)`` ON DELETE CASCADE — one optional
                  harmonization row per topic.
- ``net_view``    text NOT NULL — free-text meta-assessment authored by a
                  dept_lead or superadmin.
- ``authored_by`` FK ``users(id)`` ON DELETE SET NULL — the user who last
                  wrote the Net View. NULL if that user is deleted.
- ``authored_at`` timestamptz NOT NULL default now()
- ``updated_at``  timestamptz NOT NULL default now()

Additive-only migration (new table, no existing data touched).
Downgrade drops the table.
"""

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP


def upgrade() -> None:
    op.create_table(
        "topic_harmonizations",
        sa.Column(
            "topic_id",
            UUID(as_uuid=False),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("net_view", sa.Text(), nullable=False),
        sa.Column(
            "authored_by",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "authored_at",
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


def downgrade() -> None:
    op.drop_table("topic_harmonizations")
