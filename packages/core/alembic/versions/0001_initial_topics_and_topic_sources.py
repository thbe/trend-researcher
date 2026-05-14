"""initial topics and topic_sources

Revision ID: 0001
Revises:
Create Date: 2026-05-14

Creates the v1 topic store schema:

- ``topics`` — one row per distinct (deduplicated) topic
- ``topic_sources`` — many-to-one observations per topic, with a unique
  constraint on ``(topic_id, source_name, url, observed_at)``

The ``pgcrypto`` extension is enabled at the top of ``upgrade()`` so
``gen_random_uuid()`` is available for UUID primary key defaults on standard
Postgres images.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "topics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "observation_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_topics_title", "topics", ["title"])
    op.create_index("ix_topics_last_seen_at", "topics", ["last_seen_at"])

    op.create_table(
        "topic_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "topic_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("native_rank", sa.Integer(), nullable=True),
        sa.Column(
            "observed_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint(
            "topic_id",
            "source_name",
            "url",
            "observed_at",
            name="uq_topic_sources_topic_source_url_observed",
        ),
    )
    op.create_index("ix_topic_sources_topic_id", "topic_sources", ["topic_id"])
    op.create_index(
        "ix_topic_sources_source_name", "topic_sources", ["source_name"]
    )
    op.create_index(
        "ix_topic_sources_observed_at", "topic_sources", ["observed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_topic_sources_observed_at", table_name="topic_sources")
    op.drop_index("ix_topic_sources_source_name", table_name="topic_sources")
    op.drop_index("ix_topic_sources_topic_id", table_name="topic_sources")
    op.drop_table("topic_sources")

    op.drop_index("ix_topics_last_seen_at", table_name="topics")
    op.drop_index("ix_topics_title", table_name="topics")
    op.drop_table("topics")
