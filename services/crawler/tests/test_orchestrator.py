"""Unit tests for the crawler orchestrator.

These tests use in-memory ``FakeSource`` and ``FakeRepository`` doubles so
they touch zero I/O — neither network nor DB. They exercise the failure-
isolation contract: a single source raising mid-fetch must NOT abort the
whole crawl, and the failure must surface in the result stats and log
output via a ``failed_sources`` list.

Plan 02-03 T01 (TDD): these tests are written BEFORE the orchestrator is
extended with the ``failed_sources`` field. The first run is expected to
fail (RED). After the orchestrator is updated, they go GREEN.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from crawler.app.orchestrator import run_once
from crawler.domain.raw_item import RawItem
from crawler.ports.crawl_run_repository_port import CrawlRunRecord


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeSource:
    """Source double that returns a fixed list or raises a fixed exception.

    Conforms structurally to :class:`crawler.ports.source_port.SourcePort`
    (duck-typed: has ``name`` attribute and async ``fetch(top_n)``).
    """

    def __init__(self, name: str, items_or_exc: list[RawItem] | BaseException) -> None:
        self.name = name
        self._items_or_exc = items_or_exc
        self.fetch_calls = 0

    async def fetch(self, top_n: int) -> list[RawItem]:
        self.fetch_calls += 1
        if isinstance(self._items_or_exc, BaseException):
            raise self._items_or_exc
        return list(self._items_or_exc)


class _StoredTopic:
    __slots__ = ("id", "title", "dedup_key")

    def __init__(self, topic_id: UUID, title: str, key: str) -> None:
        self.id = topic_id
        self.title = title
        self.dedup_key = key


class _FakeRepository:
    """In-memory repository double matching ``TopicRepositoryPort`` shape.

    Stores topics in a dict keyed by UUID. ``find_candidates`` returns every
    topic whose stored key starts with the same first 4 chars as the query
    — good enough to exercise the orchestrator's match/insert branching
    without dragging in rapidfuzz semantics (those have their own tests).
    """

    def __init__(self) -> None:
        self._topics: dict[UUID, _StoredTopic] = {}
        self.inserts: list[RawItem] = []
        self.updates: list[tuple[UUID, RawItem]] = []

    async def find_candidates(self, key: str, limit: int = 50) -> list[_StoredTopic]:
        if not key:
            return []
        prefix = key[:4]
        return [t for t in self._topics.values() if t.dedup_key.startswith(prefix)][
            :limit
        ]

    async def insert_new(self, item: RawItem) -> UUID:
        from crawler.domain.dedup import dedup_key

        topic_id = uuid4()
        self._topics[topic_id] = _StoredTopic(
            topic_id, item.title, dedup_key(item.title)
        )
        self.inserts.append(item)
        return topic_id

    async def update_existing(self, topic_id: UUID, item: RawItem) -> None:
        self.updates.append((topic_id, item))


class _NoopCrawlRunRepo:
    """No-op crawl_run repo for tests that focus on source-failure isolation,
    not on the crawl_runs persistence contract (which has its own dedicated
    test module: test_orchestrator_writes_crawl_run.py)."""

    async def insert(self, record: CrawlRunRecord) -> UUID:  # noqa: ARG002
        return uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(title: str, source_name: str, rank: int = 1) -> RawItem:
    return RawItem(
        title=title,
        url=f"https://example.test/{title.replace(' ', '-').lower()}",
        source_name=source_name,
        native_rank=rank,
        observed_at=datetime.now(timezone.utc),
        raw_payload={"title": title},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_one_source_failure_does_not_abort_run() -> None:
    """A failing source must be isolated: other sources still execute and
    the run completes. The failed source's name must appear in
    ``failed_sources``.
    """

    item_a = _item("Alpha headline from A", "good_a")
    item_b = _item("Beta headline from B", "good_b")

    sources: list[Any] = [
        _FakeSource("good_a", [item_a]),
        _FakeSource("bad", RuntimeError("boom")),
        _FakeSource("good_b", [item_b]),
    ]
    repo = _FakeRepository()

    stats = await run_once(sources, repo, _NoopCrawlRunRepo(), top_n=10)

    # Both healthy sources executed and their items were inserted.
    assert sources[0].fetch_calls == 1
    assert sources[2].fetch_calls == 1
    assert {i.title for i in repo.inserts} == {item_a.title, item_b.title}

    # The bad source's failure surfaced as a named failure, not just a counter.
    assert "failed_sources" in stats, (
        "orchestrator must expose failed_sources in result stats"
    )
    assert stats["failed_sources"] == ["bad"]

    # Existing fields still populated and consistent.
    assert stats["totals"]["fetched"] == 2
    assert stats["totals"]["inserted"] == 2
    assert stats["totals"]["errors"] == 1


async def test_all_sources_succeed_no_failed_sources() -> None:
    """When every source succeeds, ``failed_sources`` must exist and be empty."""

    item_a = _item("Gamma headline", "good_a")
    item_b = _item("Delta headline", "good_b")

    sources: list[Any] = [
        _FakeSource("good_a", [item_a]),
        _FakeSource("good_b", [item_b]),
    ]
    repo = _FakeRepository()

    stats = await run_once(sources, repo, _NoopCrawlRunRepo(), top_n=10)

    assert "failed_sources" in stats
    assert stats["failed_sources"] == []
    assert stats["totals"]["errors"] == 0
    assert stats["totals"]["inserted"] == 2


async def test_failed_sources_preserves_order_and_lists_only_failures() -> None:
    """Multiple failures across positions list in the order encountered;
    healthy sources are not listed.
    """

    item_ok = _item("Epsilon healthy", "good_mid")
    sources: list[Any] = [
        _FakeSource("bad_one", RuntimeError("first failure")),
        _FakeSource("good_mid", [item_ok]),
        _FakeSource("bad_two", ValueError("second failure")),
    ]
    repo = _FakeRepository()

    stats = await run_once(sources, repo, _NoopCrawlRunRepo(), top_n=10)

    assert stats["failed_sources"] == ["bad_one", "bad_two"]
    assert stats["totals"]["errors"] == 2
    assert stats["totals"]["inserted"] == 1
    assert sources[1].fetch_calls == 1


__all__: list[str] = []
