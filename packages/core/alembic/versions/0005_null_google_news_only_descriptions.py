"""NULL Google-News-only topic descriptions (data migration)

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-18

Plan 04.5.1 T02 data cleanup: NULLs topics.description for topics whose
every observed source is 'google_news'. These descriptions contain HTML
link-list fragments (<ol><li><a>...) from Google News RSS, not publisher
prose. Cross-source topics (also observed by NYT/HN) are preserved.

Idempotent: WHERE description IS NOT NULL guard means re-running is a no-op.
"""

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute("""
        UPDATE topics t
        SET description = NULL
        WHERE t.description IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM topic_sources ts
            WHERE ts.topic_id = t.id AND ts.source_name = 'google_news'
          )
          AND NOT EXISTS (
            SELECT 1 FROM topic_sources ts
            WHERE ts.topic_id = t.id AND ts.source_name <> 'google_news'
          )
    """)


def downgrade() -> None:
    # Cannot restore the original HTML descriptions — they were garbage data.
    # The raw values remain in topic_sources.raw_payload['summary'] for
    # forensic recovery if ever needed.
    pass
