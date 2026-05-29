"""Lowercase existing usernames for case-insensitive identity

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-29

Application-layer change: ``api.auth.normalize_username`` now lowercases +
strips every username at the login/create/seed boundary. Pre-existing rows
may still carry mixed-case values, which would silently lock those users
out (their input gets lowercased on login, but their stored username does
not match).

This migration normalises existing data so the unique index on
``users.username`` enforces case-insensitive uniqueness from now on.

Collision handling: if two rows differ only by case (e.g. ``Alice`` and
``alice``), the UPDATE would violate the unique constraint and fail the
migration. We surface that explicitly with a pre-check that raises a
descriptive error — an operator must resolve the conflict manually before
re-running. In practice the only seeded user is ``admin@app.local``
(already lowercase), so this is defensive.

Downgrade is a no-op: lowercasing is lossy and reversing it would require
guesswork we don't have.
"""

from __future__ import annotations

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    bind = op.get_bind()

    # Pre-check: find any case-collisions that would block the UPDATE.
    collisions = bind.execute(
        sa.text(
            """
            SELECT LOWER(username) AS lname, COUNT(*) AS n
            FROM users
            GROUP BY LOWER(username)
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    if collisions:
        names = ", ".join(f"{row.lname!r} (×{row.n})" for row in collisions)
        raise RuntimeError(
            "Migration 0021 cannot proceed: users table has case-insensitive "
            f"duplicates: {names}. Resolve manually (deactivate or rename one "
            "of each colliding pair) and re-run."
        )

    op.execute(
        sa.text("UPDATE users SET username = LOWER(TRIM(username)) "
                "WHERE username <> LOWER(TRIM(username))")
    )


def downgrade() -> None:
    # Lowercasing is lossy; no reliable downgrade.
    pass
