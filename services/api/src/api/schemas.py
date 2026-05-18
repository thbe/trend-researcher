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

from pydantic import BaseModel, ConfigDict, Field


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


class TopicsListResponse(BaseModel):
    """Wrapper for ``GET /api/topics`` so the JSON shape is an object, not a bare array.

    ``limit`` echoes back the (validated) page size; ``sort`` echoes back the
    (validated) sort key including any leading ``-`` for desc. Operators can
    sanity-check both against what they sent.
    """

    topics: list[TopicResponse]
    limit: int
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
    """One row from ``crawl_config``."""

    model_config = ConfigDict(from_attributes=True)

    source_name: str
    enabled: bool
    top_n: int
    capture_summary: bool
    feed_url: str | None
    updated_at: datetime


class CrawlConfigUpdateRequest(BaseModel):
    """Mutable fields the operator can change via the UI."""

    enabled: bool | None = None
    top_n: int | None = Field(None, ge=1, le=500)


__all__ = [
    "CrawlConfigResponse",
    "CrawlConfigUpdateRequest",
    "HealthzResponse",
    "RunResponse",
    "RunsListResponse",
    "TopicResponse",
    "TopicsListResponse",
    "TopicSourceResponse",
    "TopicDetailResponse",
]
