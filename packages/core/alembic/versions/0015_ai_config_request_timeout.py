"""Add request_timeout_seconds to ai_config

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-22

Lets the operator tune per-request LLM timeout from the UI without redeploys.
Useful when running small local models on slow hardware (CPU-only inference)
where the previous hard-coded 120s ceiling caused 500s on long prompts.
"""

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "ai_config",
        sa.Column(
            "request_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_config", "request_timeout_seconds")
