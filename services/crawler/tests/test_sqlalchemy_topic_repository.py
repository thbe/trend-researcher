"""Integration tests for SqlAlchemyTopicRepository.

Skipped automatically when TEST_DATABASE_URL is unset or the configured
database is unreachable. Set TEST_DATABASE_URL to enable, e.g.::

    export TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crawler.adapters.persistence.sqlalchemy_topic_repository import (
    SqlAlchemyTopicRepository,
)
from crawler.domain.raw_item import RawItem

from .conftest import db_available


pytestmark = pytest.mark.skipif(
    not db_available(),
    reason="set TEST_DATABASE_URL to a reachable Postgres to run these tests",
)


def _item(
    *,
    title: str = "Test topic",
    url: str = "https://example.com/a",
    source_name: str = "hackernews",
    native_rank: int | None = 1,
    observed_at: datetime | None = None,
) -> RawItem:
    return RawItem(
        title=title,
        url=url,
        source_name=source_name,
        native_rank=native_rank,
        observed_at=observed_at or datetime.now(timezone.utc),
        raw_payload={"id": 1},
    )


async def test_insert_new_round_trip(session_factory):
    repo = SqlAlchemyTopicRepository(session_factory)
    topic_id = await repo.insert_new(_item(title="Brand new topic"))

    candidates = await repo.find_candidates("brand new topic")
    assert any(c.id == topic_id and c.observation_count == 1 for c in candidates)


async def test_update_existing_bumps_counter_and_appends_source(session_factory):
    repo = SqlAlchemyTopicRepository(session_factory)
    first = _item(title="Reuters: market moves", url="https://r.com/1")
    topic_id = await repo.insert_new(first)

    second = _item(
        title="Reuters: market moves",
        url="https://r.com/2",
        observed_at=datetime.now(timezone.utc) + timedelta(seconds=10),
    )
    await repo.update_existing(topic_id, second)

    candidates = await repo.find_candidates("reuters market moves")
    match = next(c for c in candidates if c.id == topic_id)
    assert match.observation_count == 2


async def test_update_existing_idempotent_on_unique_violation(session_factory):
    repo = SqlAlchemyTopicRepository(session_factory)
    item = _item(title="Same source, same url, same time")
    topic_id = await repo.insert_new(item)

    # Same (source_name, url, observed_at) → unique violation on TopicSource;
    # observation_count must still advance.
    duplicate = _item(
        title=item.title,
        url=item.url,
        source_name=item.source_name,
        observed_at=item.observed_at,
    )
    await repo.update_existing(topic_id, duplicate)

    candidates = await repo.find_candidates("same source same url same time")
    match = next(c for c in candidates if c.id == topic_id)
    assert match.observation_count == 2


async def test_find_candidates_window_exceeds_old_phase1_limit(session_factory):
    """Regression: dedup must still find a topic when the candidate window
    contains more than the old hard-coded 50 most-recent rows.

    Phase 1 used limit=50 which silently broke the moment the DB grew past
    50 topics — older topics fell outside the window and were re-inserted
    on the next crawl. Plan 02-04 hot-fix widens the default to 5000; this
    test pins the new behaviour so it can't regress.
    """
    repo = SqlAlchemyTopicRepository(session_factory)
    base = datetime.now(timezone.utc)

    # Insert the target topic FIRST so it has the oldest last_seen_at.
    target_id = await repo.insert_new(
        _item(
            title="Cast iron skillet care guide",
            url="https://example.com/target",
            observed_at=base,
        )
    )

    # Push the target outside the old 50-row window with 60 newer topics.
    for i in range(60):
        await repo.insert_new(
            _item(
                title=f"Filler headline number {i}",
                url=f"https://example.com/filler/{i}",
                observed_at=base + timedelta(seconds=i + 1),
            )
        )

    # With the default limit, the target MUST still appear. Old code with
    # limit=50 would have dropped it (60 fillers are all more recent).
    candidates = await repo.find_candidates("cast iron skillet care guide")
    assert any(c.id == target_id for c in candidates), (
        "find_candidates default window dropped a topic older than the "
        "50 most-recent inserts — dedup will silently re-insert duplicates"
    )


async def test_find_candidates_orders_by_last_seen_desc(session_factory):
    repo = SqlAlchemyTopicRepository(session_factory)
    base = datetime.now(timezone.utc)
    ids = []
    for i, offset in enumerate([0, 30, 60]):
        ids.append(
            await repo.insert_new(
                _item(
                    title=f"Topic {i}",
                    url=f"https://example.com/{i}",
                    observed_at=base + timedelta(seconds=offset),
                )
            )
        )

    candidates = await repo.find_candidates("topic", limit=3)
    assert len(candidates) == 3
    # Most-recent first → reverse insert order.
    assert [c.id for c in candidates] == list(reversed(ids))
