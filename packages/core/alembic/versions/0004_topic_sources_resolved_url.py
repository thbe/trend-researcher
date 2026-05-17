"""topic_sources.resolved_url nullable column

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-18

Adds a nullable ``resolved_url`` text column to ``topic_sources``.

Context (Plan 04.5-01, ING-011, locked D-Q4 = B):
    Google News RSS publishes redirect tokens of the form
    ``https://news.google.com/rss/articles/CBMi…`` that are useless as a
    one-click "open the article" target. We need the publisher URL, but we
    must NOT add an outbound HTTP fetch in the ingest path (ARC-001 + the
    "deterministic zero-AI ingest" boundary).

    The chosen path:

    * Keep ``topic_sources.url`` AS-IS holding the original CBM token
      (preserves the raw signal — audits + the decoder rollback path both
      need it).
    * Add this new ``resolved_url`` column to carry the decoded publisher
      URL when the in-process base64 decoder succeeds; ``NULL`` when it
      fails or the source isn't a Google News redirect at all.
    * The SPA (TopicDetail.vue, Plan 04.5-01 / T06) renders
      ``source.resolved_url || source.url`` so the link is always clickable
      — degraded but never broken when the decoder can't keep up with
      Google's protobuf rotations.

    No backfill happens in this migration — the one-shot
    ``scripts/backfill_descriptions.py`` (Plan 04.5-01 / T05) populates
    historical rows with the same guard (``WHERE resolved_url IS NULL``).

Schema impact:
    * Additive column, nullable, no default, no index, no constraint.
    * Existing rows: ``resolved_url IS NULL`` — SPA fallback handles this.
    * Older API images that don't know about this column simply ignore it
      (extra-column reads are silent in SQLAlchemy core selects we use).
      This makes rollback to v0.4.1 safe without an Alembic downgrade.

Downgrade:
    Drops the column unconditionally. Data loss is acceptable on
    downgrade — we can always re-derive resolved_url from
    ``topic_sources.url`` via the decoder.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "topic_sources",
        sa.Column("resolved_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("topic_sources", "resolved_url")
