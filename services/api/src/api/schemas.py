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

from pydantic import BaseModel, ConfigDict


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


__all__ = [
    "HealthzResponse",
    "RunResponse",
    "RunsListResponse",
    "TopicResponse",
    "TopicsListResponse",
]
