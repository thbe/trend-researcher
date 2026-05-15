"""Integration test for SqlAlchemyCrawlRunRepository.

Skipped automatically when TEST_DATABASE_URL is unset or the configured
database is unreachable. Set TEST_DATABASE_URL to enable, e.g.::

    export TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test

Phase 3 / Plan 03-01 / T07 — proves the adapter persists every column of
a CrawlRunRecord round-trip. Pairs with T08 unit test which exercises the
orchestrator-level failure-propagation contract without a real DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from core.models import CrawlRun
from crawler.adapters.persistence.sqlalchemy_crawl_run_repository import (
    SqlAlchemyCrawlRunRepository,
)
from crawler.ports import CrawlRunRecord

from .conftest import db_available


pytestmark = pytest.mark.skipif(
    not db_available(),
    reason="set TEST_DATABASE_URL to a reachable Postgres to run these tests",
)


async def test_insert_persists_crawl_run(session_factory):
    repo = SqlAlchemyCrawlRunRepository(session_factory)

    started = datetime.now(timezone.utc)
    finished = started + timedelta(seconds=42)
    record = CrawlRunRecord(
        started_at=started,
        finished_at=finished,
        duration_ms=42_000,
        top_n=100,
        totals_fetched=200,
        totals_inserted=89,
        totals_updated=10,
        totals_skipped_within_run=1,
        totals_errors=2,
        per_source={
            "hackernews": {
                "fetched": 100,
                "inserted": 30,
                "updated": 5,
                "skipped_within_run": 0,
                "errors": 0,
            },
            "reddit": {
                "fetched": 0,
                "inserted": 0,
                "updated": 0,
                "skipped_within_run": 0,
                "errors": 1,
            },
        },
        failed_sources=["reddit"],
    )

    crawl_run_id = await repo.insert(record)
    assert crawl_run_id is not None

    # Open a fresh session and select the row back to assert on every column.
    async with session_factory() as session:
        row = (
            await session.execute(select(CrawlRun).where(CrawlRun.id == str(crawl_run_id)))
        ).scalar_one()

    assert row.started_at == started
    assert row.finished_at == finished
    assert row.duration_ms == 42_000
    assert row.top_n == 100
    assert row.totals_fetched == 200
    assert row.totals_inserted == 89
    assert row.totals_updated == 10
    assert row.totals_skipped_within_run == 1
    assert row.totals_errors == 2
    assert row.per_source == record.per_source
    assert row.failed_sources == ["reddit"]
    # created_at is server-assigned (default now()); just assert it's set
    # and within a sane window of the insert.
    assert row.created_at is not None
    assert abs((row.created_at - finished).total_seconds()) < 60
