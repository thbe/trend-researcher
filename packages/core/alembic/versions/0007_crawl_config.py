"""Add crawl_config table for per-source enable/N control

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-18

Phase 5: crawl_config is the single source of truth for mutable crawl
settings. The crawler reads it at the start of each run. The UI writes it.
Cadence stays env-driven (not in this table).
"""

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "crawl_config",
        sa.Column("source_name", sa.Text(), primary_key=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "top_n",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "capture_summary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "feed_url",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Seed with current hardcoded sources
    op.execute(
        """
        INSERT INTO crawl_config (source_name, enabled, top_n, capture_summary, feed_url) VALUES
            ('hackernews', true, 100, true, NULL),
            ('nyt_homepage', true, 100, true, 'https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml'),
            ('google_news', true, 100, false, 'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en')
        """
    )


def downgrade() -> None:
    op.drop_table("crawl_config")
