"""v_topic_stats read-only VIEW (breadth + longevity_seconds)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-16

Adds the ``v_topic_stats`` read-only Postgres VIEW exposing two derived
columns per topic:

- ``breadth`` — ``COUNT(DISTINCT topic_sources.source_name)`` per topic
- ``longevity_seconds`` — ``EXTRACT(EPOCH FROM (last_seen_at - first_seen_at))``
  cast to ``bigint``

These two numbers satisfy **STO-006** (derived, not stored): the ``topics``
table gains no new columns and no denormalisation. After this migration,
``SELECT breadth, longevity_seconds FROM v_topic_stats WHERE topic_id = ?``
is the single SQL source of truth for both numbers — Phase 4 list + detail
endpoints (04-02 / 04-03) and any future Phase 5 / Phase 8 caller JOIN this
view rather than re-deriving the formula inline.

``LEFT JOIN topic_sources`` keeps a row in the view for orphan topics (zero
sources observed yet — possible if a future code path inserts a ``Topic``
before its first ``TopicSource``); breadth on that row is ``0``.

The ``COALESCE`` guard around ``EXTRACT(EPOCH ...)`` is defensive: today
both ``first_seen_at`` and ``last_seen_at`` are ``NOT NULL`` in the schema,
but the guard keeps the view honest if either column ever becomes nullable
downstream.

If this view becomes a hot path, the swap to ``MATERIALIZED VIEW`` is a
follow-up migration with **no callsite changes** — the contract
``(topic_id, breadth, longevity_seconds)`` stays identical.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


_CREATE_VIEW_SQL = """
CREATE VIEW v_topic_stats AS
SELECT
    t.id AS topic_id,
    COUNT(DISTINCT ts.source_name) AS breadth,
    COALESCE(EXTRACT(EPOCH FROM (t.last_seen_at - t.first_seen_at))::bigint, 0) AS longevity_seconds
FROM topics t
LEFT JOIN topic_sources ts ON ts.topic_id = t.id
GROUP BY t.id;
"""

_DROP_VIEW_SQL = "DROP VIEW IF EXISTS v_topic_stats;"


def upgrade() -> None:
    op.execute(_CREATE_VIEW_SQL)


def downgrade() -> None:
    op.execute(_DROP_VIEW_SQL)
