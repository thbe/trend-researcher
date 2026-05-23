"""Add assessment_jobs table for background processing.

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assessment_jobs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("total_topics", sa.Integer(), nullable=False),
        sa.Column("completed_topics", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_topics", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("results", JSONB, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_assessment_jobs_state", "assessment_jobs", ["state"])


def downgrade() -> None:
    op.drop_index("ix_assessment_jobs_state")
    op.drop_table("assessment_jobs")
