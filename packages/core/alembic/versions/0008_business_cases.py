"""Add business_cases table for AI assessment results

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-18

Phase 6: AI Assessment Foundation. This table stores the output of the
Stage 2 assessment pipeline — one row per (topic, assessment run). The v1
schema covers binary retail-relevance verdict + reason; full business-case
fields (importance, investment band, etc.) land in Phase 7.
"""

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP, JSONB


def upgrade() -> None:
    op.create_table(
        "business_cases",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("topic_id", UUID(as_uuid=False), sa.ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("relevance_verdict", sa.Text, nullable=False),  # 'relevant' | 'not-relevant'
        sa.Column("relevance_reason", sa.Text, nullable=False),
        sa.Column("model_used", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("raw_response", JSONB, nullable=True),  # full LLM response for debugging
        sa.Column("generated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("business_cases")
