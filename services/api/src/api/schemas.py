"""Pydantic v2 response models for the api service.

``RunResponse`` mirrors the ``crawl_runs`` table 1:1 (no field projection,
no rename) so the operator sees exactly what the orchestrator persisted.
``model_config = ConfigDict(from_attributes=True)`` lets the route do
``RunResponse.model_validate(orm_row)`` directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Phase 10 (MT-002): RBAC role literal — mirrors ``core.models.RoleLiteral``
# but redeclared here so this module has zero import-time dependency on the
# ORM layer. Keep in sync with migration 0016's CHECK constraint.
RoleLiteralT = Literal["viewer", "analyst", "dept_lead"]


class HealthzResponse(BaseModel):
    """Liveness + DB-reachability probe response."""

    status: Literal["ok", "degraded"]
    db: Literal["reachable", "unreachable"]


class RunResponse(BaseModel):
    """One ``crawl_runs`` row as JSON.

    Field set + names mirror ``core.models.CrawlRun``. ``per_source`` is
    typed as ``dict[str, dict[str, int]]`` because each source contributes
    a 5-int stats dict (fetched/inserted/updated/skipped_within_run/errors).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    top_n: int
    totals_fetched: int
    totals_inserted: int
    totals_updated: int
    totals_skipped_within_run: int
    totals_errors: int
    per_source: dict[str, dict[str, int]]
    failed_sources: list[str]


class RunsListResponse(BaseModel):
    """Wrapper for ``GET /runs`` so the JSON shape is an object, not a bare array.

    ``limit`` echoes back the (clamped) page size used so operators can sanity-
    check what they actually got.
    """

    runs: list[RunResponse]
    limit: int


class TopicResponse(BaseModel):
    """One ``topics`` row as JSON, enriched with derived ``v_topic_stats`` columns.

    Field set mirrors ``core.models.Topic`` (excluding ``topic_metadata`` and
    ``created_at``/``updated_at``, which are list-view noise per G5) plus the
    two derived columns from the ``v_topic_stats`` view. ``observation_count``
    comes from ``topics`` (already maintained by the crawler); ``breadth`` and
    ``longevity_seconds`` come from the view (single source of truth, STO-006).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    """``topics.id`` UUID (pgcrypto-generated)."""
    title: str
    """``topics.title`` canonical headline."""
    description: str | None
    """``topics.description`` optional summary."""
    first_seen_at: datetime
    """``topics.first_seen_at`` earliest source observation timestamp."""
    last_seen_at: datetime
    """``topics.last_seen_at`` most-recent source observation timestamp."""
    observation_count: int
    """``topics.observation_count`` total source observations recorded (not distinct)."""
    breadth: int
    """``v_topic_stats.breadth`` = COUNT DISTINCT ``topic_sources.source_name`` for this topic."""
    longevity_seconds: int
    """``v_topic_stats.longevity_seconds`` = EXTRACT(EPOCH FROM (last_seen_at - first_seen_at))::bigint."""
    relevance_verdict: str | None = None
    """Latest business_cases.relevance_verdict for this topic (NULL if unassessed)."""
    source_names: str | None = None
    """Comma-separated distinct source names that observed this topic."""


class TopicsListResponse(BaseModel):
    """Wrapper for ``GET /api/topics`` so the JSON shape is an object, not a bare array.

    ``limit`` echoes back the (validated) page size; ``sort`` echoes back the
    (validated) sort key including any leading ``-`` for desc. Operators can
    sanity-check both against what they sent.
    """

    topics: list[TopicResponse]
    total: int
    limit: int
    offset: int
    sort: str


class TopicSourceResponse(BaseModel):
    """One ``topic_sources`` row as JSON, lean projection for the detail endpoint.

    Deliberately **excludes** ``raw_payload`` per CONTEXT G7 — kept lean; can
    be re-added in Phase 5 behind a query flag if the detail UI ever needs it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    """``topic_sources.id`` UUID (pgcrypto-generated)."""
    source_name: str
    """``topic_sources.source_name`` slug (e.g. ``hackernews``, ``nyt_homepage``)."""
    url: str
    """``topic_sources.url`` canonical URL for this observation."""
    resolved_url: str | None = None
    """``topic_sources.resolved_url`` decoded publisher URL for google_news CBM redirect tokens, ``None`` otherwise (Plan 04.5-01 / ING-011)."""
    native_rank: int
    """``topic_sources.native_rank`` 1-based position in the source's native ranking when observed."""
    observed_at: datetime
    """``topic_sources.observed_at`` timestamp of this specific observation."""


class TopicDetailResponse(BaseModel):
    """``GET /api/topics/{id}`` payload — full topic detail with nested sources.

    Field set = ``TopicResponse`` (re-declared explicitly so the OpenAPI schema
    is flat and self-describing) PLUS ``topic_metadata`` (JSONB blob captured
    per source-adapter) PLUS ``sources`` (ordered ``observed_at DESC``).

    Additive-friendly: Phase 5 may add ``crawl_config_context: {...}`` and
    Phase 6+ may add ``business_cases: []`` without renaming any field here.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    """``topics.id`` UUID (pgcrypto-generated)."""
    title: str
    """``topics.title`` canonical headline."""
    description: str | None
    """``topics.description`` optional summary."""
    first_seen_at: datetime
    """``topics.first_seen_at`` earliest source observation timestamp."""
    last_seen_at: datetime
    """``topics.last_seen_at`` most-recent source observation timestamp."""
    observation_count: int
    """``topics.observation_count`` total source observations recorded (not distinct)."""
    breadth: int
    """``v_topic_stats.breadth`` = COUNT DISTINCT ``topic_sources.source_name`` for this topic."""
    longevity_seconds: int
    """``v_topic_stats.longevity_seconds`` = EXTRACT(EPOCH FROM (last_seen_at - first_seen_at))::bigint."""
    topic_metadata: dict[str, object] = Field(default_factory=dict)
    """``topics.metadata`` JSONB blob (mapped to ``topic_metadata`` in Python — ``metadata`` is reserved by DeclarativeBase)."""
    sources: list[TopicSourceResponse] = Field(default_factory=list)
    """``topic_sources`` rows for this topic, ordered ``observed_at DESC`` (most recent first)."""


class CrawlConfigResponse(BaseModel):
    """One row from ``crawl_config`` (tech config only — global per source).

    Phase 10 (MT-006): the ``enabled`` flag moved to ``department_sources``;
    crawl_config carries only tech tuning knobs that apply uniformly to a
    source regardless of which dept subscribes to it.
    """

    model_config = ConfigDict(from_attributes=True)

    source_name: str
    top_n: int
    capture_summary: bool
    verify_ssl: bool
    feed_url: str | None
    updated_at: datetime


class CrawlConfigUpdateRequest(BaseModel):
    """Mutable tech fields the (super)admin can change via the UI."""

    top_n: int | None = Field(None, ge=1, le=500)
    capture_summary: bool | None = None
    verify_ssl: bool | None = None
    feed_url: str | None = None


class CrawlConfigCreateRequest(BaseModel):
    """Create a new crawl source (tech config only)."""

    source_name: str = Field(..., min_length=1, max_length=100)
    top_n: int = Field(100, ge=1, le=500)
    capture_summary: bool = True
    verify_ssl: bool = True
    feed_url: str | None = None


class TopicCleanupRequest(BaseModel):
    """Manual topic cleanup request.

    Filters are AND-combined. At least one of ``source_name`` or
    ``older_than_days`` must be provided (server rejects empty bodies to
    prevent accidental "delete everything" calls).

    - ``source_name``: only purge observations from this source. If omitted,
      filter spans all sources.
    - ``older_than_days``: only purge items whose ``last_seen_at`` (topics) /
      ``observed_at`` (topic_sources) is older than this many days. If omitted,
      no age filter (when source_name is set, deletes ALL from that source).
    """

    source_name: str | None = Field(None, min_length=1, max_length=100)
    older_than_days: int | None = Field(None, ge=0, le=3650)


class TopicCleanupResponse(BaseModel):
    """Counts of rows removed by the cleanup operation."""

    topic_sources_deleted: int
    topics_deleted: int
    source_name: str | None
    older_than_days: int | None


class AIConfigResponse(BaseModel):
    """AI/LLM connection settings."""

    model_config = ConfigDict(from_attributes=True)

    base_url: str
    model: str
    api_token: str | None
    business_context: str | None
    opportunity_criteria: str | None
    risk_criteria: str | None
    thinking_effort: str
    request_timeout_seconds: int
    updated_at: datetime


class AIConfigUpdateRequest(BaseModel):
    """Update AI config fields."""

    base_url: str | None = None
    model: str | None = None
    api_token: str | None = None
    business_context: str | None = None
    opportunity_criteria: str | None = None
    risk_criteria: str | None = None
    thinking_effort: str | None = None
    request_timeout_seconds: int | None = Field(None, ge=10, le=3600)


# ---------------------------------------------------------------------------
# Phase 10 (MT-001/MT-002): Departments + memberships + login extension
# ---------------------------------------------------------------------------


class DepartmentCreate(BaseModel):
    """Create a new department (superadmin-only)."""

    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(
        ..., min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$"
    )
    description: str | None = Field(None, max_length=2000)


class DepartmentUpdate(BaseModel):
    """Update mutable department fields. ``slug`` is immutable in v1."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)


class DepartmentResponse(BaseModel):
    """One ``departments`` row as JSON."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class DepartmentsListResponse(BaseModel):
    """Wrapper for ``GET /api/departments``."""

    departments: list[DepartmentResponse]
    total: int


class MemberResponse(BaseModel):
    """One ``user_departments`` row joined with ``users``."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    username: str
    role: RoleLiteralT
    created_at: datetime
    updated_at: datetime


class MembersListResponse(BaseModel):
    """Wrapper for ``GET /api/departments/{id}/members``."""

    members: list[MemberResponse]
    total: int


class MemberCreate(BaseModel):
    """Add a user to a department with a role."""

    user_id: UUID
    role: RoleLiteralT


class MemberUpdate(BaseModel):
    """Change a member's role within a department."""

    role: RoleLiteralT


class LoginDepartment(BaseModel):
    """Department summary embedded in the login response."""

    id: UUID
    name: str
    slug: str
    role: RoleLiteralT


class LoginResponse(BaseModel):
    """``POST /api/login`` response payload.

    Backwards-compatible: ``ok`` + ``username`` are preserved verbatim; the
    Phase 10 fields ``is_superadmin`` + ``departments`` are added so the SPA
    can populate its dept switcher without a follow-up roundtrip. For
    superadmin users, ``departments`` contains the FULL list of departments
    in the system with a synthesised role of ``dept_lead``.
    """

    ok: bool
    username: str
    is_superadmin: bool
    departments: list[LoginDepartment]


# ---------------------------------------------------------------------------
# Phase 10 (MT-006): Department-source subscriptions
# ---------------------------------------------------------------------------


class DepartmentSourceResponse(BaseModel):
    """One known crawl source joined with the active dept's subscription flag.

    ``enabled`` reflects this department's subscription (``false`` if there
    is no row in ``department_sources`` for the active dept). The other
    fields mirror ``crawl_config`` so the UI can render a single list.
    """

    model_config = ConfigDict(from_attributes=True)

    source_name: str
    enabled: bool
    top_n: int
    capture_summary: bool
    verify_ssl: bool
    feed_url: str | None


class DepartmentSourcesListResponse(BaseModel):
    """Wrapper for ``GET /api/department-sources``."""

    sources: list[DepartmentSourceResponse]
    total: int


class DepartmentSourceUpdateRequest(BaseModel):
    """Toggle the active dept's subscription to one source."""

    enabled: bool


class DepartmentPATCreate(BaseModel):
    """Body for ``POST /api/departments/{dept_id}/pats``."""

    name: str = Field(..., min_length=1, max_length=200)


class DepartmentPATCreateResponse(BaseModel):
    """Returned ONCE at creation time — contains the plaintext token.

    The plaintext is NEVER persisted (only its SHA-256 hash is stored). If
    the caller loses it, the only recourse is to revoke and mint a new PAT.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    token: str
    created_at: datetime


class DepartmentPATResponse(BaseModel):
    """Metadata for a single PAT. Never includes plaintext or hash."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_by: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class DepartmentPATsListResponse(BaseModel):
    """Wrapper for ``GET /api/departments/{dept_id}/pats``."""

    pats: list[DepartmentPATResponse]
    total: int


# ---------------------------------------------------------------------------
# Phase 10 (plan 10-03, MT-010): Assessment frameworks
# ---------------------------------------------------------------------------


class FrameworkResponse(BaseModel):
    """One ``assessment_frameworks`` row as JSON (lean — no ``json_schema``).

    The full JSON Schema is intentionally omitted (large + verbose); a
    follow-up ``GET /api/frameworks/{id}/schema`` endpoint can expose it
    when the UI needs validation hints client-side.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    description: str | None
    display_component: str
    prompt_version: str


class FrameworksListResponse(BaseModel):
    """Wrapper for ``GET /api/frameworks``."""

    frameworks: list[FrameworkResponse]
    total: int


class DepartmentFrameworkResponse(BaseModel):
    """Framework enabled for the active department, with ``is_default`` flag."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    description: str | None
    display_component: str
    prompt_version: str
    is_default: bool


class DepartmentFrameworksListResponse(BaseModel):
    """Wrapper for ``GET /api/frameworks/mine``."""

    frameworks: list[DepartmentFrameworkResponse]
    total: int


class DepartmentFrameworksUpdate(BaseModel):
    """Body for ``PUT /api/frameworks/mine``.

    Replaces the active dept's ``department_frameworks`` rows in one
    transaction. The server validates ``default ∈ enabled`` and that every
    ``enabled`` id exists in ``assessment_frameworks``.
    """

    enabled: list[UUID] = Field(..., min_length=1)
    default: UUID

    @model_validator(mode="after")
    def _default_must_be_enabled(self) -> "DepartmentFrameworksUpdate":
        if self.default not in self.enabled:
            raise ValueError("default framework must be in the enabled list")
        return self


class AssessBatchRequest(BaseModel):
    """Optional body for ``POST /api/assess``.

    ``framework_id`` omitted ⇒ use the active dept's default framework.
    Supplied ⇒ must be in the dept's enabled set (else 422).
    """

    framework_id: UUID | None = None
    limit: int = Field(20, ge=1, le=500)


class AssessSingleRequest(BaseModel):
    """Optional body for ``POST /api/assess/{topic_id}``.

    ``framework_id`` omitted ⇒ use the active dept's default framework.
    Supplied ⇒ must be in the dept's enabled set (else 422).
    """

    framework_id: UUID | None = None


# ---------------------------------------------------------------------------
# Phase 10 (plan 10-05, MT-012): Harmonization
# ---------------------------------------------------------------------------


class HarmonizationPutRequest(BaseModel):
    """Body for ``PUT /api/topics/{topic_id}/harmonization``."""

    net_view: str = Field(..., min_length=1, max_length=10_000)


class HarmonizationNetView(BaseModel):
    """The optional Net View annotation on a topic."""

    text: str
    authored_by: dict | None = None  # {"id": ..., "username": ...} or null
    authored_at: datetime
    updated_at: datetime


class HarmonizationBusinessCaseEntry(BaseModel):
    """One business case in the harmonization response (cross-department)."""

    id: UUID
    department: dict  # {"id": ..., "name": ...}
    framework: dict  # {"id": ..., "key": ..., "name": ..., "display_component": ...}
    structured_output: dict
    relevance_verdict: str | None = None
    importance_score: float | None = None
    confidence: float | None = None
    created_at: datetime
    model_used: str | None = None


class HarmonizationResponse(BaseModel):
    """``GET /api/topics/{topic_id}/harmonization`` response."""

    topic: dict  # {"id": ..., "title": ..., ...}
    business_cases: list[HarmonizationBusinessCaseEntry]
    net_view: HarmonizationNetView | None = None


__all__ = [
    "AIConfigResponse",
    "AIConfigUpdateRequest",
    "AssessBatchRequest",
    "AssessSingleRequest",
    "CrawlConfigCreateRequest",
    "CrawlConfigResponse",
    "CrawlConfigUpdateRequest",
    "DepartmentCreate",
    "DepartmentFrameworkResponse",
    "DepartmentFrameworksListResponse",
    "DepartmentFrameworksUpdate",
    "DepartmentPATCreate",
    "DepartmentPATCreateResponse",
    "DepartmentPATResponse",
    "DepartmentPATsListResponse",
    "DepartmentResponse",
    "DepartmentSourceResponse",
    "DepartmentSourceUpdateRequest",
    "DepartmentSourcesListResponse",
    "DepartmentUpdate",
    "DepartmentsListResponse",
    "FrameworkResponse",
    "FrameworksListResponse",
    "HarmonizationBusinessCaseEntry",
    "HarmonizationNetView",
    "HarmonizationPutRequest",
    "HarmonizationResponse",
    "HealthzResponse",
    "LoginDepartment",
    "LoginResponse",
    "MemberCreate",
    "MemberResponse",
    "MemberUpdate",
    "MembersListResponse",
    "RoleLiteralT",
    "RunResponse",
    "RunsListResponse",
    "TopicCleanupRequest",
    "TopicCleanupResponse",
    "TopicDetailResponse",
    "TopicResponse",
    "TopicSourceResponse",
    "TopicsListResponse",
]
