"""CrawlRunRepositoryPort: protocol the orchestrator uses to persist one crawl_runs row.

Written at the end of run_once() — one row per CLI invocation. Ops telemetry only;
no PII, no source credentials. Read by the api `/runs` endpoint and by smoke_phase3.

Boundary: zero I/O imports here (no sqlalchemy, no httpx, no core.models).
The port is pure data + protocol.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CrawlRunRecord:
    """Immutable projection of one crawl run, ready for persistence.

    Mirrors the crawl_runs table columns minus id/created_at (server-assigned).
    Fields with defaults come last per dataclass rules; per_source/failed_sources
    default to empty so a degenerate run still produces a valid record.
    """

    started_at: datetime
    finished_at: datetime
    duration_ms: int
    top_n: int
    totals_fetched: int
    totals_inserted: int
    totals_updated: int
    totals_skipped_within_run: int
    totals_errors: int
    per_source: dict[str, Any] = field(default_factory=dict)
    failed_sources: list[str] = field(default_factory=list)


class CrawlRunRepositoryPort(Protocol):
    async def insert(self, record: CrawlRunRecord) -> UUID:
        """Insert one crawl_runs row. Return the server-assigned id.

        Persist failures must propagate — the orchestrator does NOT swallow them.
        """
        ...
