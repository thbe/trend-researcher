"""Add business_context column to ai_config

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-19

Stores the operator's business description used as context for AI assessment.
"""

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("ai_config", sa.Column("business_context", sa.Text(), nullable=True))

    # Seed a sensible default
    op.execute("""
        UPDATE ai_config SET business_context =
        'We are a large retail company (grocery + general merchandise). '
        'Topics are relevant if they represent either:\n'
        '- OPPORTUNITY: viral products, trending categories, or consumer behaviour shifts we should react to in assortment/marketing\n'
        '- RISK: supply chain disruptions, geopolitical events, natural disasters, regulatory changes, or reputational threats that could impact operations\n'
        'Score relevance from the perspective of a retail category manager or risk officer.'
        WHERE key = 'default'
    """)


def downgrade() -> None:
    op.drop_column("ai_config", "business_context")
