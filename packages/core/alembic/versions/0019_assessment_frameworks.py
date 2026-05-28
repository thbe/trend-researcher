"""Assessment frameworks (verdict/swot/pestle) + per-dept enablement + business_cases.structured_output

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-28

Plan 10-03, T01 (Phase 10 — Multi-Tenant Market Intelligence Platform).
Requirements: MT-005 (pluggable frameworks), MT-007 (structured per-framework
output + composite UNIQUE on business_cases).

Schema changes (single transaction):

1. **Create ``assessment_frameworks``** — system-level registry of the three
   seeded frameworks (verdict, swot, pestle). ``key`` is the stable string
   identifier the assessor dispatches on; ``json_schema`` is the JSONB schema
   used to validate LLM output post-parse. The *source-of-truth* for the
   schema lives in ``services/assessor/src/assessor/domain/frameworks/<key>.py``
   as ``JSON_SCHEMA``; T07 enforces byte-for-byte parity via a golden test.
   Hardcoded UUIDs let ``seed.py`` (T03) upsert by ``id`` idempotently and
   let downstream migrations reference them by constant.

2. **Create ``department_frameworks``** join table — each department enables
   ≥1 framework and marks exactly one as default. Partial unique index
   ``(department_id) WHERE is_default = true`` enforces "one default per
   dept" at the DB layer.

3. **Backfill ``department_frameworks``** — every existing department (only
   Default exists post-10-01) gets all three frameworks enabled, with
   ``verdict`` marked as the default (preserves current single-tenant
   behaviour: every existing assessment used the verdict framework).

4. **Extend ``business_cases``** with ``framework_id`` FK + ``structured_output``
   JSONB. Backfill ``framework_id = verdict_uuid`` and
   ``structured_output = COALESCE(raw_response, jsonb_build_object('verdict',
   relevance_verdict, 'reason', relevance_reason))`` — every existing row
   originated from the verdict prompt, and ``raw_response`` already holds the
   parsed LLM JSON. Then add the composite UNIQUE
   ``(topic_id, department_id, framework_id, prompt_version, model_used)``
   deferred from 10-02 (the pre-check at 0017 step 1 already proved the data
   satisfies the strictly-weaker version of this constraint, and adding
   ``framework_id`` — uniform = verdict_uuid for all backfilled rows — does
   not introduce new collisions). Index on ``framework_id``.

5. **Extend ``assessment_jobs``** with ``framework_id`` FK + backfill to
   verdict + NOT NULL + index. Mirrors business_cases pattern.

Downgrade reverses every step. Step 4 dropping ``structured_output`` is
data-loss-safe for verdict rows (their content is reconstructible from
``raw_response`` / ``relevance_verdict`` / ``relevance_reason``) but
**destructive for SWOT and PESTLE rows** (their framework-specific cells
live only in ``structured_output``). Documented loudly in the downgrade
docstring; operator's responsibility if they downgrade after writing any
non-verdict assessment.
"""

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID


# Hardcoded UUIDs for the three seeded frameworks. seed.py (T03) upserts by
# id using these constants so the (migration, seed) pair is idempotent and
# downstream code/tests can reference them as well-known IDs.
VERDICT_FRAMEWORK_ID = "00000000-0000-0000-0000-000000000010"
SWOT_FRAMEWORK_ID = "00000000-0000-0000-0000-000000000011"
PESTLE_FRAMEWORK_ID = "00000000-0000-0000-0000-000000000012"


# ---------------------------------------------------------------------------
# Framework JSON schemas
#
# These are the *initial* schemas seeded into ``assessment_frameworks``. The
# canonical, evolving definitions live in
# ``services/assessor/src/assessor/domain/frameworks/<key>.py``; T07 enforces
# parity via a golden test. Until then, the assessor reads schemas from the
# DB at job-start, so any drift between this file and the framework package
# would surface as a validation failure on the next assessment.
# ---------------------------------------------------------------------------

# Verdict schema mirrors the existing RESPONSE_SCHEMA in
# services/assessor/src/assessor/domain/prompts.py exactly. Backfilled
# raw_response payloads conform to this shape (proven empirically — every
# production row went through that same prompt + parse path).
_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "category": {
            "type": "string",
            "enum": ["opportunity", "risk", "neutral"],
        },
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}


# SWOT: per CONTEXT.md G3 — strengths/weaknesses/opportunities/threats cells
# plus top-level verdict/importance/confidence for cross-framework sorting.
_SWOT_CELL = {
    "type": "object",
    "properties": {
        "point": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["point", "rationale"],
}
_SWOT_SCHEMA = {
    "type": "object",
    "properties": {
        "strengths": {"type": "array", "items": _SWOT_CELL},
        "weaknesses": {"type": "array", "items": _SWOT_CELL},
        "opportunities": {"type": "array", "items": _SWOT_CELL},
        "threats": {"type": "array", "items": _SWOT_CELL},
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "reason": {"type": "string"},
        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": [
        "strengths",
        "weaknesses",
        "opportunities",
        "threats",
        "verdict",
        "reason",
    ],
}


# PESTLE: political/economic/social/technological/legal/environmental cells
# plus top-level verdict/importance/confidence.
_PESTLE_CELL = {
    "type": "object",
    "properties": {
        "relevance": {"type": "string", "enum": ["low", "med", "high"]},
        "notes": {"type": "string"},
    },
    "required": ["relevance", "notes"],
}
_PESTLE_SCHEMA = {
    "type": "object",
    "properties": {
        "political": _PESTLE_CELL,
        "economic": _PESTLE_CELL,
        "social": _PESTLE_CELL,
        "technological": _PESTLE_CELL,
        "legal": _PESTLE_CELL,
        "environmental": _PESTLE_CELL,
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "reason": {"type": "string"},
        "importance": {"type": "integer", "minimum": 0, "maximum": 100},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": [
        "political",
        "economic",
        "social",
        "technological",
        "legal",
        "environmental",
        "verdict",
        "reason",
    ],
}


# Helper for op.execute INSERT below — alembic operations don't accept dicts
# directly as JSONB; we cast via ``::jsonb`` from a json-encoded string.
import json as _json


def _seed_frameworks(conn) -> None:
    """Insert the three system frameworks. Idempotent within a single migration
    run (the table is freshly created so no conflicts possible). seed.py (T03)
    handles ongoing idempotency on subsequent app starts."""
    rows = [
        {
            "id": VERDICT_FRAMEWORK_ID,
            "key": "verdict",
            "name": "Relevance Verdict",
            "description": (
                "Binary relevance + 1-2 sentence reason. The original "
                "single-tenant assessment shape, preserved 1:1 as a "
                "framework so all pre-Phase-10 business_cases migrate "
                "cleanly."
            ),
            "display_component": "VerdictCard",
            "json_schema": _json.dumps(_VERDICT_SCHEMA),
            "prompt_version": "v1",
        },
        {
            "id": SWOT_FRAMEWORK_ID,
            "key": "swot",
            "name": "SWOT",
            "description": (
                "Strengths, Weaknesses, Opportunities, Threats — classic "
                "four-quadrant strategic assessment."
            ),
            "display_component": "SwotCard",
            "json_schema": _json.dumps(_SWOT_SCHEMA),
            "prompt_version": "v1",
        },
        {
            "id": PESTLE_FRAMEWORK_ID,
            "key": "pestle",
            "name": "PESTLE",
            "description": (
                "Political, Economic, Social, Technological, Legal, "
                "Environmental — macro-environment scan."
            ),
            "display_component": "PestleCard",
            "json_schema": _json.dumps(_PESTLE_SCHEMA),
            "prompt_version": "v1",
        },
    ]
    conn.execute(
        sa.text(
            """
            INSERT INTO assessment_frameworks
              (id, key, name, description, display_component,
               json_schema, prompt_version)
            VALUES
              (CAST(:id AS uuid), :key, :name, :description, :display_component,
               (:json_schema)::jsonb, :prompt_version)
            """
        ),
        rows,
    )


def upgrade() -> None:
    conn = op.get_bind()

    # 1. assessment_frameworks ------------------------------------------
    op.create_table(
        "assessment_frameworks",
        sa.Column(
            "id",
            UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_component", sa.Text(), nullable=False),
        sa.Column("json_schema", JSONB, nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
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
    )

    # 2. Seed the three frameworks --------------------------------------
    _seed_frameworks(conn)

    # 3. department_frameworks join table -------------------------------
    op.create_table(
        "department_frameworks",
        sa.Column(
            "department_id",
            UUID(as_uuid=False),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "framework_id",
            UUID(as_uuid=False),
            sa.ForeignKey("assessment_frameworks.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_department_frameworks_framework_id",
        "department_frameworks",
        ["framework_id"],
    )
    # One default per dept (partial unique).
    op.create_index(
        "uq_department_frameworks_one_default_per_dept",
        "department_frameworks",
        ["department_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )

    # 4. Backfill department_frameworks ---------------------------------
    # Every existing department (Default + any future ones already at 0018)
    # gets all three frameworks enabled, with verdict as the default. This
    # preserves single-tenant behaviour: every legacy assessment used the
    # verdict prompt and stays addressable under the verdict framework.
    op.execute(
        sa.text(
            """
            INSERT INTO department_frameworks
              (department_id, framework_id, is_default)
            SELECT d.id, f.id,
                   (f.key = 'verdict') AS is_default
            FROM departments d
            CROSS JOIN assessment_frameworks f
            """
        )
    )

    # 5. Extend business_cases ------------------------------------------
    # 5a. Add nullable columns so we can backfill before tightening.
    op.add_column(
        "business_cases",
        sa.Column(
            "framework_id",
            UUID(as_uuid=False),
            sa.ForeignKey(
                "assessment_frameworks.id", ondelete="RESTRICT"
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "business_cases",
        sa.Column("structured_output", JSONB, nullable=True),
    )

    # 5b. Backfill: every existing row is a verdict-framework assessment.
    # structured_output prefers raw_response (the full parsed LLM JSON);
    # falls back to a minimal {verdict, reason} object if raw_response is
    # NULL. relevance_verdict + relevance_reason are NOT NULL in the
    # current schema (0008), so the fallback always yields a valid object
    # conforming to _VERDICT_SCHEMA's required fields.
    op.execute(
        sa.text(
            """
            UPDATE business_cases
            SET framework_id = CAST(:fw_id AS uuid),
                structured_output = COALESCE(
                    raw_response,
                    jsonb_build_object(
                        'verdict', relevance_verdict,
                        'reason',  relevance_reason
                    )
                )
            WHERE framework_id IS NULL
            """
        ).bindparams(fw_id=VERDICT_FRAMEWORK_ID)
    )

    # 5c. Tighten constraints + add server default so future INSERTs that
    # forget structured_output don't break (worst case = empty object).
    op.alter_column("business_cases", "framework_id", nullable=False)
    op.alter_column(
        "business_cases",
        "structured_output",
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    op.create_index(
        "ix_business_cases_framework_id",
        "business_cases",
        ["framework_id"],
    )

    # 5d. Post-backfill safety check: composite UNIQUE must not collide.
    # 0017 step 1 already proved (topic_id, prompt_version, model_used) was
    # unique. Adding constant framework_id = verdict_uuid + uniform
    # department_id = default does not introduce collisions, but verify
    # anyway in case multiple departments now exist and somehow share rows.
    result = conn.execute(
        sa.text(
            """
            SELECT topic_id, department_id, framework_id,
                   prompt_version, model_used, COUNT(*) AS c
            FROM business_cases
            GROUP BY topic_id, department_id, framework_id,
                     prompt_version, model_used
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).fetchone()
    if result is not None:
        raise RuntimeError(
            "Found duplicate business_cases rows on "
            "(topic_id, department_id, framework_id, prompt_version, "
            "model_used) — composite UNIQUE cannot be added. Inspect with: "
            "SELECT topic_id, department_id, framework_id, prompt_version, "
            "model_used, COUNT(*) FROM business_cases "
            "GROUP BY 1,2,3,4,5 HAVING COUNT(*) > 1;"
        )

    op.create_unique_constraint(
        "uq_business_cases_topic_dept_fw_prompt_model",
        "business_cases",
        [
            "topic_id",
            "department_id",
            "framework_id",
            "prompt_version",
            "model_used",
        ],
    )

    # 6. Extend assessment_jobs -----------------------------------------
    op.add_column(
        "assessment_jobs",
        sa.Column(
            "framework_id",
            UUID(as_uuid=False),
            sa.ForeignKey(
                "assessment_frameworks.id", ondelete="RESTRICT"
            ),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE assessment_jobs
            SET framework_id = CAST(:fw_id AS uuid)
            WHERE framework_id IS NULL
            """
        ).bindparams(fw_id=VERDICT_FRAMEWORK_ID)
    )
    op.alter_column("assessment_jobs", "framework_id", nullable=False)
    op.create_index(
        "ix_assessment_jobs_framework_id",
        "assessment_jobs",
        ["framework_id"],
    )


def downgrade() -> None:
    """Reverse 0019. DATA LOSS WARNING: dropping ``business_cases.structured_output``
    permanently destroys all framework-specific cells of any SWOT and PESTLE
    rows written between 0019 and the downgrade. Verdict-framework rows are
    safely reconstructible from ``raw_response`` / ``relevance_verdict`` /
    ``relevance_reason`` (those columns survive)."""
    # 6. assessment_jobs -------------------------------------------------
    op.drop_index(
        "ix_assessment_jobs_framework_id", table_name="assessment_jobs"
    )
    op.drop_column("assessment_jobs", "framework_id")

    # 5. business_cases --------------------------------------------------
    op.drop_constraint(
        "uq_business_cases_topic_dept_fw_prompt_model",
        "business_cases",
        type_="unique",
    )
    op.drop_index(
        "ix_business_cases_framework_id", table_name="business_cases"
    )
    op.drop_column("business_cases", "structured_output")
    op.drop_column("business_cases", "framework_id")

    # 3. department_frameworks ------------------------------------------
    op.drop_index(
        "uq_department_frameworks_one_default_per_dept",
        table_name="department_frameworks",
    )
    op.drop_index(
        "ix_department_frameworks_framework_id",
        table_name="department_frameworks",
    )
    op.drop_table("department_frameworks")

    # 1. assessment_frameworks ------------------------------------------
    op.drop_table("assessment_frameworks")
