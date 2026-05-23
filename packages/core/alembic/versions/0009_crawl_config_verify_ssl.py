"""Add verify_ssl column to crawl_config

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-19

Per-source SSL verification toggle. Defaults to true (verify).
Set to false for environments with SSL interception proxies.
"""

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "crawl_config",
        sa.Column(
            "verify_ssl",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("crawl_config", "verify_ssl")
