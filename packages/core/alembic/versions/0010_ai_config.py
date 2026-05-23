"""Add ai_config table

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-19

Singleton table storing LLM connection settings (URL, model, token).
"""

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "ai_config",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("base_url", sa.Text(), nullable=False, server_default="http://ollama:11434"),
        sa.Column("model", sa.Text(), nullable=False, server_default="qwen3.5:latest"),
        sa.Column("api_token", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Seed the default row
    op.execute(
        "INSERT INTO ai_config (key, base_url, model) VALUES ('default', 'http://ollama:11434', 'qwen3.5:latest')"
    )


def downgrade() -> None:
    op.drop_table("ai_config")
