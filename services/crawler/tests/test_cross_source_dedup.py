"""Cross-source dedup proof — Plan 02-03 T02.

These tests drive the real ``run_once`` orchestrator + real
``SqlAlchemyTopicRepository`` against a real Postgres to prove the
dedup mechanism is source-agnostic by construction. They are skip-gated
on ``TEST_DATABASE_URL`` (see conftest).

Three scenarios are pinned down:

1. Same headline, two different sources, two SEPARATE runs → one topic,
   two source rows, observation_count == 2. (Across-runs aggregation works.)
2. Same headline, two different sources, ONE run → one topic, one source row,
   observation_count == 1, skipped_within_run == 1. (Documents Phase 1's
   "bump at most once per crawl per topic" invariant so any future change
   is deliberate.)
3. Byte-identical re-observation (same source, url, observed_at) goes through
   the orchestrator → repo's ``IntegrityError`` branch → no duplicate source
   row, but observation_count still bumped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from crawler.adapters.persistence.sqlalchemy_topic_repository import (
    SqlAlchemyTopicRepository,
)
from crawler.app.orchestrator import run_once
from crawler.domain.raw_item import RawItem

from .conftest import db_available


pytestmark = pytest.mark.skipif(
    not db_available(),
    reason="set TEST_DATABASE_URL to a reachable Postgres for cross-source dedup tests",
)


@dataclass
class _FakeSource:
    """Tiny duck-typed SourcePort returning pre-built RawItems."""

    name: str
    items: list[RawItem]

    async def fetch(self, top_n: int) -> list[RawItem]:  # noqa: ARG002
        return list(self.items)


def _item(
    *,
    title: str,
    url: str,
    source_name: str,
    observed_at: datetime | None = None,
    native_rank: int = 1,
) -> RawItem:
    return RawItem(
        title=title,
        url=url,
        source_name=source_name,
        native_rank=native_rank,
        observed_at=observed_at or datetime.now(timezone.utc),
        raw_payload={"title": title},
    )


async def _select_counts(engine: AsyncEngine) -> tuple[int, int, list[str], int]:
    """Return (topics_count, sources_count, source_names_sorted, obs_count_of_only_topic)."""
    async with engine.connect() as conn:
        topics_count = (
            await conn.execute(text("SELECT count(*) FROM topics"))
        ).scalar_one()
        sources_count = (
            await conn.execute(text("SELECT count(*) FROM topic_sources"))
        ).scalar_one()
        source_names = sorted(
            row[0]
            for row in (
                await conn.execute(text("SELECT source_name FROM topic_sources"))
            ).all()
        )
        obs_count = (
            (
                await conn.execute(
                    text("SELECT observation_count FROM topics LIMIT 1")
                )
            ).scalar_one()
            if topics_count
            else 0
        )
    return topics_count, sources_count, source_names, obs_count


async def test_same_headline_two_sources_two_runs_collapses_to_one_topic(
    engine: AsyncEngine, session_factory: async_sessionmaker
) -> None:
    repo = SqlAlchemyTopicRepository(session_factory)
    title = "Major retailer announces price cuts"
    t0 = datetime.now(timezone.utc)
    item_a = _item(title=title, url="https://nyt.com/x", source_name="nyt_homepage", observed_at=t0)
    item_b = _item(
        title=title,
        url="https://news.google.com/y",
        source_name="google_news",
        observed_at=t0 + timedelta(seconds=30),
    )

    stats1 = await run_once([_FakeSource("nyt_homepage", [item_a])], repo, top_n=10)
    assert stats1["totals"] == {
        "fetched": 1, "inserted": 1, "updated": 0, "skipped_within_run": 0, "errors": 0,
    }

    stats2 = await run_once([_FakeSource("google_news", [item_b])], repo, top_n=10)
    assert stats2["totals"] == {
        "fetched": 1, "inserted": 0, "updated": 1, "skipped_within_run": 0, "errors": 0,
    }

    topics, sources, names, obs = await _select_counts(engine)
    assert topics == 1
    assert sources == 2
    assert names == ["google_news", "nyt_homepage"]
    assert obs == 2


async def test_within_single_run_two_sources_same_headline_skips_second_match(
    engine: AsyncEngine, session_factory: async_sessionmaker
) -> None:
    repo = SqlAlchemyTopicRepository(session_factory)
    title = "Holiday shopping surge breaks records"
    t0 = datetime.now(timezone.utc)
    item_a = _item(title=title, url="https://nyt.com/a", source_name="nyt_homepage", observed_at=t0)
    item_b = _item(title=title, url="https://news.google.com/b", source_name="google_news", observed_at=t0)

    stats = await run_once(
        [_FakeSource("nyt_homepage", [item_a]), _FakeSource("google_news", [item_b])],
        repo,
        top_n=10,
    )
    assert stats["totals"] == {
        "fetched": 2, "inserted": 1, "updated": 0, "skipped_within_run": 1, "errors": 0,
    }

    topics, sources, names, obs = await _select_counts(engine)
    assert topics == 1
    assert sources == 1, "Phase 1 invariant: skip-within-run does NOT add a source row"
    assert names == ["nyt_homepage"]
    assert obs == 1


async def test_byte_identical_reobservation_through_orchestrator_handles_unique_violation(
    engine: AsyncEngine, session_factory: async_sessionmaker
) -> None:
    repo = SqlAlchemyTopicRepository(session_factory)
    title = "Single item end-to-end idempotency check"
    t0 = datetime.now(timezone.utc)
    item = _item(title=title, url="https://example.com/z", source_name="hackernews", observed_at=t0)

    await run_once([_FakeSource("hackernews", [item])], repo, top_n=10)
    # Second run with byte-identical item: orchestrator dedup matches the
    # existing topic → update_existing → IntegrityError on the unique
    # (topic_id, source_name, url, observed_at) → repo retries the bump
    # alone in a fresh session. Source row count stays at 1.
    stats2 = await run_once([_FakeSource("hackernews", [item])], repo, top_n=10)
    assert stats2["totals"]["updated"] == 1

    topics, sources, names, obs = await _select_counts(engine)
    assert topics == 1
    assert sources == 1
    assert names == ["hackernews"]
    assert obs == 2
