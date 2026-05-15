"""SqlAlchemy implementation of :class:`CrawlRunRepositoryPort`.

Persists one row per ``orchestrator.run_once()`` invocation into the
``crawl_runs`` table created by alembic migration 0002. Ops telemetry only
— no PII, no credentials. Read by the api ``/runs`` endpoint and by the
Phase 3 smoke script.

Persist failures propagate; the orchestrator does NOT swallow them
(see Plan 03-01 task T06).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import CrawlRun

from crawler.ports.crawl_run_repository_port import CrawlRunRecord


class SqlAlchemyCrawlRunRepository:
    """Persists per-run ops telemetry using SQLAlchemy 2.x async."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def insert(self, record: CrawlRunRecord) -> UUID:
        async with self._session_factory() as session:
            crawl_run = CrawlRun(
                started_at=record.started_at,
                finished_at=record.finished_at,
                duration_ms=record.duration_ms,
                top_n=record.top_n,
                totals_fetched=record.totals_fetched,
                totals_inserted=record.totals_inserted,
                totals_updated=record.totals_updated,
                totals_skipped_within_run=record.totals_skipped_within_run,
                totals_errors=record.totals_errors,
                per_source=record.per_source,
                failed_sources=record.failed_sources,
            )
            session.add(crawl_run)
            await session.flush()  # populate crawl_run.id
            crawl_run_id = crawl_run.id
            await session.commit()
        return UUID(crawl_run_id) if isinstance(crawl_run_id, str) else crawl_run_id


__all__ = ["SqlAlchemyCrawlRunRepository"]
