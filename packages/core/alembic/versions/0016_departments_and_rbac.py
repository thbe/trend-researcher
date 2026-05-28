"""Departments + per-(user,dept) RBAC + superadmin + default-dept seed

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-27

Plan 10-01 (Phase 10 — Multi-Tenant Market Intelligence Platform).
Requirements: MT-001 (departments), MT-002 (per-(user,dept) RBAC),
MT-008 (default-dept migration of existing single-tenant data).

Adds the foundational multi-tenant primitives:

1. ``departments`` table — name + slug + description, slug is lower-case
   ASCII/digits/hyphens/underscores only (enforced via CHECK).
2. ``users.is_superadmin`` boolean column — orthogonal to per-dept role;
   superadmins can administer any department.
3. ``user_departments`` join table — composite PK (user_id, department_id),
   ``role`` is one of ``viewer`` | ``analyst`` | ``dept_lead`` (CHECK).

**Default-dept seed (same transaction):**
- Inserts a hardcoded ``Default`` department with a fixed UUID
  (``00000000-0000-0000-0000-000000000001``) so downgrade + tests can
  reference it deterministically.
- Promotes every existing user to ``is_superadmin = true``. In single-tenant
  production there is exactly one user (the seed user); test fixtures may
  have several — all become superadmin at the migration moment, which is the
  correct multi-tenant interpretation of "the people who were running this
  before".
- Inserts a ``user_departments`` row per existing user linking them to the
  Default department with role ``dept_lead``.

Downgrade reverses all three schema changes (seed rows go with the dropped
tables / columns).
"""

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP


# Hardcoded UUID for the Default department — referenced by the seed
# INSERT and by tests that assert "the default dept exists with this id".
DEFAULT_DEPARTMENT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # 1. departments table -----------------------------------------------
    op.create_table(
        "departments",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9_-]+$'",
            name="ck_departments_slug_format",
        ),
    )

    # 2. users.is_superadmin column --------------------------------------
    op.add_column(
        "users",
        sa.Column(
            "is_superadmin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 3. user_departments join table -------------------------------------
    op.create_table(
        "user_departments",
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "department_id",
            UUID(as_uuid=False),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "role IN ('viewer', 'analyst', 'dept_lead')",
            name="ck_user_departments_role",
        ),
    )
    op.create_index(
        "ix_user_departments_department_id",
        "user_departments",
        ["department_id"],
    )

    # 4. Default-dept seed (same transaction) ----------------------------
    # Insert hardcoded-UUID Default department so downgrade + tests can
    # reference it deterministically.
    op.execute(
        sa.text(
            "INSERT INTO departments (id, name, slug, description) "
            "VALUES (CAST(:id AS uuid), 'Default', 'default', "
            "'Auto-created default department from single-tenant migration.')"
        ).bindparams(id=DEFAULT_DEPARTMENT_ID)
    )

    # Promote every existing user to superadmin. In single-tenant prod
    # there is exactly one user; test fixtures may have several — all
    # become superadmin which is the correct multi-tenant interpretation
    # of "the people who were running this before".
    op.execute("UPDATE users SET is_superadmin = true")

    # Every existing user becomes dept_lead of Default.
    op.execute(
        sa.text(
            "INSERT INTO user_departments (user_id, department_id, role) "
            "SELECT id, CAST(:dept_id AS uuid), 'dept_lead' FROM users"
        ).bindparams(dept_id=DEFAULT_DEPARTMENT_ID)
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_departments_department_id", table_name="user_departments"
    )
    op.drop_table("user_departments")
    op.drop_column("users", "is_superadmin")
    op.drop_table("departments")
