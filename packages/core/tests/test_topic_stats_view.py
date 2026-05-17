"""Integration tests for the v_topic_stats Postgres VIEW (migration 0003).

Skipped automatically when ``TEST_DATABASE_URL`` is unset or the configured
database is unreachable. Set ``TEST_DATABASE_URL`` to enable, e.g.::

    export TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test

These tests pin the four SQL semantics the view promises (per plan 04-01
T02):

1. ``breadth`` counts *distinct* ``source_name`` values per topic — repeats
   in ``topic_sources`` do not inflate the count.
2. A topic with zero ``topic_sources`` rows still appears in the view
   (``LEFT JOIN``) with ``breadth = 0`` and ``longevity_seconds = 0``
   (``first_seen_at == last_seen_at`` immediately after insert).
3. ``longevity_seconds`` is ``EXTRACT(EPOCH FROM (last_seen_at -
   first_seen_at))`` in whole seconds — pinned with a 90-second window.
4. ``longevity_seconds`` is returned as Python ``int`` (i.e. Postgres
   ``bigint``), not ``float`` — guards against accidental removal of the
   ``::bigint`` cast in the SQL.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from .conftest import db_available


pytestmark = pytest.mark.skipif(
    not db_available(),
    reason="set TEST_DATABASE_URL to a reachable Postgres to run these tests",
)


# Shared SQL for reading a single row out of the view.
_SELECT_STATS = text(
    "SELECT topic_id, breadth, longevity_seconds "
    "FROM v_topic_stats WHERE topic_id = :tid"
)


async def _insert_topic(
    session_factory,
    *,
    title: str = "Test topic",
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
) -> str:
    """Insert a topic with explicit timestamps and return its UUID."""
    if first_seen_at is None:
        first_seen_at = datetime.now(timezone.utc)
    if last_seen_at is None:
        last_seen_at = first_seen_at
    async with session_factory() as session:
        row = await session.execute(
            text(
                "INSERT INTO topics (title, first_seen_at, last_seen_at) "
                "VALUES (:title, :fs, :ls) RETURNING id"
            ),
            {"title": title, "fs": first_seen_at, "ls": last_seen_at},
        )
        topic_id = row.scalar_one()
        await session.commit()
        return topic_id


async def _insert_topic_source(
    session_factory,
    *,
    topic_id: str,
    source_name: str,
    url: str,
    observed_at: datetime | None = None,
) -> None:
    if observed_at is None:
        observed_at = datetime.now(timezone.utc)
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO topic_sources "
                "(topic_id, source_name, url, observed_at) "
                "VALUES (:tid, :src, :url, :obs)"
            ),
            {
                "tid": topic_id,
                "src": source_name,
                "url": url,
                "obs": observed_at,
            },
        )
        await session.commit()


async def test_breadth_counts_distinct_source_names(session_factory):
    """3 topic_sources with source_names [hackernews, hackernews, nyt_homepage]
    → breadth = 2 (distinct count, not row count)."""
    topic_id = await _insert_topic(session_factory, title="Distinct breadth")
    base = datetime.now(timezone.utc)
    await _insert_topic_source(
        session_factory,
        topic_id=topic_id,
        source_name="hackernews",
        url="https://news.ycombinator.com/item?id=1",
        observed_at=base,
    )
    await _insert_topic_source(
        session_factory,
        topic_id=topic_id,
        source_name="hackernews",
        url="https://news.ycombinator.com/item?id=2",
        observed_at=base + timedelta(seconds=1),
    )
    await _insert_topic_source(
        session_factory,
        topic_id=topic_id,
        source_name="nyt_homepage",
        url="https://nytimes.com/article/x",
        observed_at=base + timedelta(seconds=2),
    )
    async with session_factory() as session:
        row = (
            await session.execute(_SELECT_STATS, {"tid": topic_id})
        ).mappings().one()
    assert row["topic_id"] == topic_id
    assert row["breadth"] == 2


async def test_breadth_is_zero_for_orphan_topic(session_factory):
    """Topic with zero topic_sources rows → row in view with breadth=0
    and longevity_seconds=0 (first_seen_at == last_seen_at on insert)."""
    now = datetime.now(timezone.utc)
    topic_id = await _insert_topic(
        session_factory,
        title="Orphan topic",
        first_seen_at=now,
        last_seen_at=now,
    )
    async with session_factory() as session:
        row = (
            await session.execute(_SELECT_STATS, {"tid": topic_id})
        ).mappings().one()
    assert row["topic_id"] == topic_id
    assert row["breadth"] == 0
    assert row["longevity_seconds"] == 0


async def test_longevity_seconds_matches_timestamp_delta(session_factory):
    """first_seen_at = 2026-01-01T00:00:00Z, last_seen_at = +90s →
    longevity_seconds == 90 (whole seconds)."""
    first = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    last = first + timedelta(seconds=90)
    topic_id = await _insert_topic(
        session_factory,
        title="90 second window",
        first_seen_at=first,
        last_seen_at=last,
    )
    async with session_factory() as session:
        row = (
            await session.execute(_SELECT_STATS, {"tid": topic_id})
        ).mappings().one()
    assert row["longevity_seconds"] == 90


async def test_longevity_seconds_is_bigint_not_float(session_factory):
    """`::bigint` cast in the view SQL must return Python int, not float.

    Regression guard: if a future edit drops the cast, EXTRACT(EPOCH ...)
    returns ``double precision`` which asyncpg maps to ``float``. This test
    would catch that drift immediately.
    """
    first = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    # > 1 day so we're well past any sub-second noise concern.
    last = first + timedelta(days=2, hours=3)
    topic_id = await _insert_topic(
        session_factory,
        title="Bigint typing guard",
        first_seen_at=first,
        last_seen_at=last,
    )
    async with session_factory() as session:
        row = (
            await session.execute(_SELECT_STATS, {"tid": topic_id})
        ).mappings().one()
    longevity = row["longevity_seconds"]
    assert isinstance(longevity, int), (
        f"longevity_seconds returned {type(longevity).__name__} — the "
        "::bigint cast in the v_topic_stats view SQL may have been dropped"
    )
    assert not isinstance(longevity, bool)  # bool is a subclass of int
    # Sanity: 2 days 3 hours = 183600 seconds.
    assert longevity == 2 * 24 * 3600 + 3 * 3600
