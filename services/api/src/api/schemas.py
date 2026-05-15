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


__all__ = ["HealthzResponse", "RunResponse", "RunsListResponse"]
