"""Integration tests for SqlAlchemyTopicRepository.

Skipped automatically when TEST_DATABASE_URL is unset or the configured
database is unreachable. Set TEST_DATABASE_URL to enable, e.g.::

    export TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from core.models import Topic, TopicSource

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
    description: str | None = None,
) -> RawItem:
    return RawItem(
        title=title,
        url=url,
        source_name=source_name,
        native_rank=native_rank,
        observed_at=observed_at or datetime.now(timezone.utc),
        raw_payload={"id": 1},
        description=description,
    )


def _make_decodable_cbm(publisher_url: bytes) -> str:
    """Build a synthetic CBMi token whose payload embeds publisher_url —
    same shape as the T03 test fixture helper. Used here so the
    google_news write-path test doesn't depend on any live Google token."""
    length = len(publisher_url)
    length_bytes = bytes([length]) if length < 128 else bytes([(length & 0x7F) | 0x80, length >> 7])
    payload = (
        b"\x08\x13\x22"
        + length_bytes
        + publisher_url
        + b"\xd2\x01\x20trailing-junk-bytes-here-pad"
    )
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"https://news.google.com/rss/articles/CBMi{encoded}?oc=5"


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


# ---------------------------------------------------------------------------
# Plan 04.5-01 / T04 — description plumb-through + resolved_url write path.
# ---------------------------------------------------------------------------


async def test_insert_new_persists_description(session_factory):
    """RawItem.description lands on Topic.description on first insert
    (ING-010 / D-Q1)."""
    repo = SqlAlchemyTopicRepository(session_factory)
    topic_id = await repo.insert_new(
        _item(
            title="Item with description",
            url="https://example.com/desc",
            description="A short standfirst from the source feed.",
        )
    )

    async with session_factory() as session:
        row = (await session.execute(select(Topic).where(Topic.id == str(topic_id)))).scalar_one()
    assert row.description == "A short standfirst from the source feed."


async def test_update_existing_keeps_first_description(session_factory):
    """Re-observation must NOT overwrite a non-NULL Topic.description
    (D-Q1 first-non-empty merge). Operator chose stability over freshness."""
    repo = SqlAlchemyTopicRepository(session_factory)
    base = datetime.now(timezone.utc)

    topic_id = await repo.insert_new(
        _item(
            title="Stable framing test",
            url="https://example.com/s1",
            description="First framing wins.",
            observed_at=base,
        )
    )

    await repo.update_existing(
        topic_id,
        _item(
            title="Stable framing test",
            url="https://example.com/s2",
            description="A totally different second framing that must NOT win.",
            observed_at=base + timedelta(seconds=10),
        ),
    )

    async with session_factory() as session:
        row = (await session.execute(select(Topic).where(Topic.id == str(topic_id)))).scalar_one()
    assert row.description == "First framing wins."


async def test_update_existing_fills_null_description(session_factory):
    """Symmetric proof of D-Q1: if the first observation had no description
    (e.g. HN), a later observation that DOES carry one should fill the NULL.
    This is the 'first-non-empty' part — NULL is treated as 'not yet set'."""
    repo = SqlAlchemyTopicRepository(session_factory)
    base = datetime.now(timezone.utc)

    topic_id = await repo.insert_new(
        _item(
            title="Cross-source merge test",
            url="https://example.com/hn-first",
            source_name="hackernews",
            description=None,
            observed_at=base,
        )
    )

    await repo.update_existing(
        topic_id,
        _item(
            title="Cross-source merge test",
            url="https://example.com/rss-second",
            source_name="nyt_homepage",
            description="Now we have a summary from RSS.",
            observed_at=base + timedelta(seconds=10),
        ),
    )

    async with session_factory() as session:
        row = (await session.execute(select(Topic).where(Topic.id == str(topic_id)))).scalar_one()
    assert row.description == "Now we have a summary from RSS."


async def test_google_news_source_writes_resolved_url(session_factory):
    """For source_name='google_news', topic_sources.resolved_url is the
    decoded publisher URL; topic_sources.url stays AS-IS (the CBM token)."""
    repo = SqlAlchemyTopicRepository(session_factory)
    publisher = b"https://www.bbc.co.uk/news/world-europe-99999"
    cbm_url = _make_decodable_cbm(publisher)

    topic_id = await repo.insert_new(
        _item(
            title="Decodable google news item",
            url=cbm_url,
            source_name="google_news",
            description="GN summary.",
        )
    )

    async with session_factory() as session:
        src = (
            await session.execute(
                select(TopicSource).where(TopicSource.topic_id == str(topic_id))
            )
        ).scalar_one()
    assert src.url == cbm_url, "original CBM token must be preserved verbatim"
    assert src.resolved_url == publisher.decode("ascii"), (
        f"resolved_url should be the decoded publisher URL, got {src.resolved_url!r}"
    )


async def test_non_google_source_leaves_resolved_url_null(session_factory):
    """Non-google_news sources never invoke the decoder; resolved_url stays
    NULL even when url happens to be a CBM-shaped token (defensive)."""
    repo = SqlAlchemyTopicRepository(session_factory)
    topic_id = await repo.insert_new(
        _item(
            title="NYT item",
            url="https://www.nytimes.com/2026/05/18/foo.html",
            source_name="nyt_homepage",
            description="NYT standfirst.",
        )
    )

    async with session_factory() as session:
        src = (
            await session.execute(
                select(TopicSource).where(TopicSource.topic_id == str(topic_id))
            )
        ).scalar_one()
    assert src.resolved_url is None
