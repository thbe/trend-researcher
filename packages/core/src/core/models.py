"""SQLAlchemy 2.x ORM models for the Trend Researcher topic store.

The schema lives here in ``packages/core`` and is the single source of truth
for every service in the workspace (locked architectural decision — see
ARC-003 / b3 in .planning/REQUIREMENTS.md).

Notes
-----
- The Python attribute on :class:`Topic` is ``topic_metadata`` but it maps to
  the SQL column literally named ``metadata``. ``metadata`` is reserved on
  :class:`sqlalchemy.orm.DeclarativeBase` and cannot be used as an attribute
  name.
- ``observation_count`` and ``last_seen_at`` are denormalised counters on
  ``topics`` so the assessor service can sort cheaply, but breadth and
  longevity are NOT stored — they are computed from ``topic_sources`` via SQL
  at query time (STO-005).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# Phase 10 (MT-002): per-(user, department) role. The string set is enforced
# at the DB layer via a CHECK constraint on ``user_departments.role`` — see
# migration 0016. This Literal is the API contract surface used by Pydantic
# schemas + FastAPI dependencies (``require_role``).
RoleLiteral = Literal["viewer", "analyst", "dept_lead"]


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in :mod:`core.models`."""


class Topic(Base):
    """One row per distinct (deduplicated) topic observed across all sources."""

    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )
    observation_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    # Python attribute is ``topic_metadata`` to avoid the reserved
    # DeclarativeBase ``metadata`` attribute. SQL column is ``metadata``.
    topic_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    sources: Mapped[list["TopicSource"]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Phase 10 (MT-012): optional cross-department Net View annotation.
    harmonization: Mapped["TopicHarmonization | None"] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class TopicSource(Base):
    """One row per (topic, source, url, observed_at) observation.

    Many-to-one against :class:`Topic`. Re-crawls accumulate rows here while
    the parent ``topics`` row is updated in place (last_seen bumped,
    observation_count incremented).
    """

    __tablename__ = "topic_sources"
    __table_args__ = (
        UniqueConstraint(
            "topic_id",
            "source_name",
            "url",
            "observed_at",
            name="uq_topic_sources_topic_source_url_observed",
        ),
        Index("ix_topic_sources_topic_id", "topic_id"),
        Index("ix_topic_sources_source_name", "source_name"),
        Index("ix_topic_sources_observed_at", "observed_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    topic_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Plan 04.5-01 (ING-011, migration 0004): decoded publisher URL for
    # Google News CBM redirect tokens. NULL when the source isn't a
    # google_news redirect or when the in-process base64 decoder couldn't
    # extract a usable URL. SPA prefers this over `url` for clickability;
    # `url` is preserved AS-IS so we can re-derive on demand.
    resolved_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    native_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    topic: Mapped["Topic"] = relationship(back_populates="sources")


class CrawlRun(Base):
    """One row per ``crawler run-once`` invocation — operational telemetry.

    Written at the end of :func:`crawler.app.orchestrator.run_once` from the
    stats dict the orchestrator already computes. Read by the api service via
    ``GET /runs`` and by ``scripts/smoke_phase3.sh`` to assert that scheduled
    crawls actually fire (Phase 3, OPS-002).

    No PII / credentials / user content — just counts, timestamps, and the
    list of sources that failed during the run.
    """

    __tablename__ = "crawl_runs"
    __table_args__ = (
        Index("ix_crawl_runs_started_at", "started_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    started_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    finished_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    top_n: Mapped[int] = mapped_column(Integer, nullable=False)
    totals_fetched: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    totals_inserted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    totals_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    totals_skipped_within_run: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    totals_errors: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    per_source: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    failed_sources: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class User(Base):
    """Application user for login-page authentication (v0.5.2).

    Passwords are stored as bcrypt hashes. The seed user is upserted on app
    startup from AUTH_SEED_USERNAME / AUTH_SEED_PASSWORD env vars.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_superadmin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # Phase 10 (MT-002): per-(user, department) memberships. Each row carries
    # the role this user has *within* that department.
    departments: Mapped[list["UserDepartment"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Department(Base):
    """A market-intelligence tenant (Phase 10, MT-001).

    Departments are the per-tenant scope for assessment configuration,
    sources subscription, frameworks, and business cases. Topics remain
    GLOBAL (ARC-001 preserved) — only the *lens* applied to them is
    per-department.

    The ``slug`` column is constrained to lower-case ASCII letters, digits,
    hyphens and underscores via a DB CHECK (see migration 0016). The
    seeded Default department uses the hardcoded UUID
    ``00000000-0000-0000-0000-000000000001`` so downgrade + tests can
    reference it deterministically.
    """

    __tablename__ = "departments"
    __table_args__ = (
        CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9_-]+$'",
            name="ck_departments_slug_format",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    members: Mapped[list["UserDepartment"]] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Phase 10 (MT-006): per-(dept, source) subscription. Crawler unions
    # the enabled set across all departments to build its effective source
    # list (see services/crawler/src/crawler/app/orchestrator.py).
    sources: Mapped[list["DepartmentSource"]] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Phase 10 (MT-004): per-dept AI config. One row per department after
    # migration 0017 reshape (PK is department_id).
    ai_config: Mapped["AIConfig | None"] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    # Phase 10 (MT-009): per-dept assessment artefacts.
    business_cases: Mapped[list["BusinessCase"]] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    assessment_jobs: Mapped[list["AssessmentJob"]] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Phase 10 (plan 10-03, MT-010): per-dept framework enablement. Each
    # row records that this department has opted-in to a given assessment
    # framework (verdict / swot / pestle / future). Exactly one row per
    # department carries ``is_default = true`` (enforced by partial unique
    # index in migration 0019).
    framework_links: Mapped[list["DepartmentFramework"]] = relationship(
        back_populates="department",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class UserDepartment(Base):
    """Join row between :class:`User` and :class:`Department` (Phase 10, MT-002).

    Composite primary key ``(user_id, department_id)``. The ``role`` column
    is one of :data:`RoleLiteral` — enforced by a DB CHECK constraint (see
    migration 0016). A user can belong to N departments with a different
    role in each; system-wide admin is the orthogonal ``users.is_superadmin``
    boolean.
    """

    __tablename__ = "user_departments"
    __table_args__ = (
        CheckConstraint(
            "role IN ('viewer', 'analyst', 'dept_lead')",
            name="ck_user_departments_role",
        ),
        Index("ix_user_departments_department_id", "department_id"),
    )

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    department_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[RoleLiteral] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    user: Mapped["User"] = relationship(back_populates="departments")
    department: Mapped["Department"] = relationship(back_populates="members")


class CrawlConfig(Base):
    """Per-source technical crawl configuration (Phase 5).

    Holds tuning knobs (``top_n``, ``capture_summary``, ``verify_ssl``,
    ``feed_url``) that are global per source — *not* per department. The
    crawler fetches each source once globally (``source_name`` is the
    primary key); ``department_id`` records which department *owns* the
    source (added in migration 0022). Owner dept members get full CRUD on
    their sources; other depts may opt in via :class:`DepartmentSource`.
    """

    __tablename__ = "crawl_config"
    __table_args__ = (
        Index("ix_crawl_config_department_id", "department_id"),
    )

    source_name: Mapped[str] = mapped_column(Text, primary_key=True)
    department_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    top_n: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    capture_summary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    verify_ssl: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    feed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class DepartmentSource(Base):
    """Per-(department, source) subscription (Phase 10, MT-006).

    Composite PK ``(department_id, source_name)``. The ``enabled`` flag
    drives the crawler's effective source list: the orchestrator queries
    ``SELECT DISTINCT source_name FROM department_sources WHERE
    enabled = true`` to get the union across all departments. If every
    row is disabled (or the table is empty), the orchestrator falls back
    to all known sources from :class:`CrawlConfig` to avoid bricking the
    cron — see migration 0017 docstring.
    """

    __tablename__ = "department_sources"
    __table_args__ = (
        Index("ix_department_sources_source_name", "source_name"),
    )

    department_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_name: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    department: Mapped["Department"] = relationship(back_populates="sources")


class DepartmentPAT(Base):
    """Per-department Personal Access Token (Phase 10, plan 10-02 T09).

    Each row is a bearer credential scoped to a single department.
    Dept_leads (and superadmins) mint these to drive the dept-scoped
    internal crawl endpoint without sharing the global
    ``TREND_INTERNAL_PAT`` env secret.

    Storage shape:

    - ``token_hash`` holds the SHA-256 hex of the plaintext bearer; the
      plaintext is returned to the caller exactly once at creation time
      and is never persisted.
    - ``revoked_at`` is a soft-delete tombstone — the auth middleware
      rejects any token whose row has a non-NULL ``revoked_at``.
    - Partial unique index on ``token_hash WHERE revoked_at IS NULL``
      (migration 0018) keeps active-token lookup unambiguous while
      allowing revoked rows to be retained for audit.
    """

    __tablename__ = "department_pats"
    __table_args__ = (
        Index("ix_department_pats_department_id", "department_id"),
        Index(
            "ix_department_pats_token_hash_active",
            "token_hash",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    department_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id"),
        nullable=False,
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_used_at: Mapped[str | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    revoked_at: Mapped[str | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    department: Mapped["Department"] = relationship()


class BusinessCase(Base):
    """One row per AI assessment of a topic (Phase 6).

    Phase 10 (MT-009) added ``department_id`` so each (topic, dept) pair
    can carry its own assessment. The composite UNIQUE
    ``(topic_id, department_id, framework_id, prompt_version, model_used)``
    is added in 10-03 once ``framework_id`` exists.
    """

    __tablename__ = "business_cases"
    __table_args__ = (
        Index("ix_business_cases_department_id", "department_id"),
        Index("ix_business_cases_framework_id", "framework_id"),
        UniqueConstraint(
            "topic_id",
            "department_id",
            "framework_id",
            "prompt_version",
            "model_used",
            name="uq_business_cases_topic_dept_fw_prompt_model",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    topic_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    department_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Phase 10 (plan 10-03, MT-010): which assessment framework produced
    # this row. Backfilled to the verdict framework UUID in 0019.
    framework_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("assessment_frameworks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    relevance_verdict: Mapped[str] = mapped_column(Text, nullable=False)
    relevance_reason: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Phase 10 (plan 10-03): canonical framework-shaped output, validated
    # against the framework's ``json_schema``. For verdict rows backfilled
    # in 0019 this mirrors ``raw_response`` (or a synthesised
    # ``{verdict, reason}`` object when raw_response was NULL).
    structured_output: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    generated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    department: Mapped["Department"] = relationship(
        back_populates="business_cases"
    )
    framework: Mapped["AssessmentFramework"] = relationship(
        back_populates="business_cases"
    )


class AIConfig(Base):
    """Per-department AI/LLM connection settings (Phase 10, MT-004).

    Migration 0017 reshaped this table: PK is now ``department_id`` (UUID FK
    to ``departments``) instead of the legacy ``key='default'`` singleton.
    Each department owns one row. The crawler does NOT read this table —
    AI runs only in Stage 2 (ARC-001).
    """

    __tablename__ = "ai_config"

    department_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # ``provider`` chooses the adapter explicitly (see migration 0023). One
    # of: ``ollama`` | ``openai`` | ``anthropic``. ``openai`` covers any
    # OpenAI-compatible endpoint: hosted OpenAI, oMLX, LM Studio, vLLM,
    # llama.cpp server, etc. — ``base_url`` must point at the ``/v1`` root.
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="ollama")
    base_url: Mapped[str] = mapped_column(Text, nullable=False, default="http://ollama:11434")
    model: Mapped[str] = mapped_column(Text, nullable=False, default="qwen3.5:latest")
    api_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    opportunity_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking_effort: Mapped[str] = mapped_column(Text, nullable=False, server_default="low")
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="120")
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    department: Mapped["Department"] = relationship(back_populates="ai_config")


class AssessmentJob(Base):
    """Background assessment job tracking (Phase 7).

    Phase 10 (MT-009) added ``department_id`` so per-dept assessment
    batches can be tracked independently.
    """

    __tablename__ = "assessment_jobs"
    __table_args__ = (
        Index("ix_assessment_jobs_department_id", "department_id"),
        Index("ix_assessment_jobs_framework_id", "framework_id"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    department_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Phase 10 (plan 10-03, MT-010): which framework this job runs against.
    # Backfilled to verdict UUID in 0019.
    framework_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("assessment_frameworks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
    )  # pending, running, completed, failed
    total_topics: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_topics: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    failed_topics: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    started_at: Mapped[str | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    finished_at: Mapped[str | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    department: Mapped["Department"] = relationship(
        back_populates="assessment_jobs"
    )
    framework: Mapped["AssessmentFramework"] = relationship(
        back_populates="assessment_jobs"
    )


class AssessmentFramework(Base):
    """Registry of pluggable assessment frameworks (Phase 10, plan 10-03).

    Each row is a system-level framework definition (e.g. ``verdict``,
    ``swot``, ``pestle``) that departments can opt-in to via
    :class:`DepartmentFramework`. The seeded rows use hardcoded UUIDs
    declared in migration 0019 so the seed bootstrap (T03) can upsert
    idempotently from the registry module.

    - ``key`` is the stable string identifier the assessor dispatches on
      (matches the registry key in
      ``services/assessor/src/assessor/domain/frameworks/registry.py``).
    - ``json_schema`` is the JSONB schema the framework's structured
      output must validate against (mirrors the schema in the framework
      module — single source of truth lives in the registry module; this
      column is the cached DB copy used for validation in the API).
    - ``display_component`` is the Vuetify component name the SPA picks
      to render rows produced by this framework.
    """

    __tablename__ = "assessment_frameworks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_component: Mapped[str] = mapped_column(Text, nullable=False)
    json_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    department_links: Mapped[list["DepartmentFramework"]] = relationship(
        back_populates="framework",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    business_cases: Mapped[list["BusinessCase"]] = relationship(
        back_populates="framework"
    )
    assessment_jobs: Mapped[list["AssessmentJob"]] = relationship(
        back_populates="framework"
    )


class DepartmentFramework(Base):
    """Per-(department, framework) opt-in row (Phase 10, plan 10-03).

    Composite PK ``(department_id, framework_id)``. Exactly one row per
    department carries ``is_default = true`` — enforced at the DB layer
    via the partial unique index
    ``uq_department_frameworks_one_default_per_dept`` (created in
    migration 0019). The API picks the default framework whenever an
    assessment request omits ``framework_id``.

    Backfill in 0019 enables all three seeded frameworks for every
    existing department, with ``verdict`` flagged as the default so
    legacy single-tenant behaviour is preserved.
    """

    __tablename__ = "department_frameworks"
    __table_args__ = (
        Index(
            "ix_department_frameworks_framework_id", "framework_id"
        ),
        Index(
            "uq_department_frameworks_one_default_per_dept",
            "department_id",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
    )

    department_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("departments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    framework_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("assessment_frameworks.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    department: Mapped["Department"] = relationship(
        back_populates="framework_links"
    )
    framework: Mapped["AssessmentFramework"] = relationship(
        back_populates="department_links"
    )


class TopicHarmonization(Base):
    """Cross-department Net View annotation for a topic (Phase 10, MT-012).

    One optional row per topic. A dept_lead (of any department) or superadmin
    can author/update the free-text ``net_view`` — a meta-assessment that
    synthesises the individual department business cases into a single
    organisational perspective.

    Read access: any logged-in user (cross-department visibility by design).
    Write access: ``dept_lead`` of any department, or ``is_superadmin``.
    Concurrency: last-write-wins (acceptable for v1 single-operator usage).
    """

    __tablename__ = "topic_harmonizations"

    topic_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    net_view: Mapped[str] = mapped_column(Text, nullable=False)
    authored_by: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    authored_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    topic: Mapped["Topic"] = relationship(back_populates="harmonization")
    author: Mapped["User | None"] = relationship()


__all__ = ["AIConfig", "AssessmentFramework", "AssessmentJob", "Base", "BusinessCase", "CrawlConfig", "CrawlRun", "Department", "DepartmentFramework", "DepartmentPAT", "DepartmentSource", "RoleLiteral", "Topic", "TopicHarmonization", "TopicSource", "User", "UserDepartment"]
