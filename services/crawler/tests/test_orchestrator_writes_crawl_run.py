"""Unit tests for orchestrator → crawl_run_repo persistence (Plan 03-01 T08).

These tests pin the OPS-002 contract that ``run_once`` must persist exactly
one ``crawl_runs`` row per crawl, built from the same stats it returns and
logs, and that a failure in that persist step propagates (does NOT get
swallowed). Pure unit tests: in-memory ``FakeCrawlRunRepo`` + the same
``_FakeSource`` / ``_FakeRepository`` doubles used in test_orchestrator.py.
No Postgres, no skip-gate.

Sibling integration test ``test_sqlalchemy_crawl_run_repository.py`` covers
the real adapter against a live DB.
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
# Test doubles (mirror test_orchestrator.py shape)
# ---------------------------------------------------------------------------


class _FakeSource:
    def __init__(self, name: str, items_or_exc: list[RawItem] | BaseException) -> None:
        self.name = name
        self._items_or_exc = items_or_exc

    async def fetch(self, top_n: int) -> list[RawItem]:
        if isinstance(self._items_or_exc, BaseException):
            raise self._items_or_exc
        return list(self._items_or_exc)


class _StoredTopic:
    __slots__ = ("id", "title", "dedup_key")

    def __init__(self, topic_id: UUID, title: str, key: str) -> None:
        self.id = topic_id
        self.title = title
        self.dedup_key = key


class _FakeTopicRepo:
    def __init__(self) -> None:
        self._topics: dict[UUID, _StoredTopic] = {}

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
        return topic_id

    async def update_existing(self, topic_id: UUID, item: RawItem) -> None:  # noqa: ARG002
        return None


class _FakeCrawlRunRepo:
    """Collects every persisted CrawlRunRecord; returns a fresh UUID each call."""

    def __init__(self) -> None:
        self.inserts: list[CrawlRunRecord] = []

    async def insert(self, record: CrawlRunRecord) -> UUID:
        self.inserts.append(record)
        return uuid4()


class _RaisingCrawlRunRepo:
    """Raises on insert to exercise the persist-failure-propagates branch."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls = 0

    async def insert(self, record: CrawlRunRecord) -> UUID:  # noqa: ARG002
        self.calls += 1
        raise self._exc


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


async def test_run_once_writes_one_crawl_run() -> None:
    """One crawl → exactly one inserted CrawlRunRecord whose fields mirror
    the returned stats (totals, per_source, failed_sources)."""

    item_a = _item("Alpha headline", "good_a")
    item_b = _item("Beta headline", "good_b")

    sources: list[Any] = [
        _FakeSource("good_a", [item_a]),
        _FakeSource("bad", RuntimeError("boom")),
        _FakeSource("good_b", [item_b]),
    ]
    topic_repo = _FakeTopicRepo()
    crawl_run_repo = _FakeCrawlRunRepo()

    stats = await run_once(sources, topic_repo, crawl_run_repo, top_n=10)

    assert len(crawl_run_repo.inserts) == 1, "exactly one crawl_runs row per crawl"
    record = crawl_run_repo.inserts[0]

    # Totals mirror returned stats.
    assert record.top_n == 10
    assert record.totals_fetched == stats["totals"]["fetched"] == 2
    assert record.totals_inserted == stats["totals"]["inserted"] == 2
    assert record.totals_updated == stats["totals"]["updated"] == 0
    assert (
        record.totals_skipped_within_run
        == stats["totals"]["skipped_within_run"]
        == 0
    )
    assert record.totals_errors == stats["totals"]["errors"] == 1

    # Per-source dict + failed_sources list mirror stats.
    assert record.per_source == stats["sources"]
    assert record.failed_sources == stats["failed_sources"] == ["bad"]

    # Timing sanity: started_at <= finished_at and duration_ms >= 0.
    assert record.started_at <= record.finished_at
    assert record.duration_ms >= 0

    # crawl_run_id surfaced into stats.
    assert "crawl_run_id" in stats


async def test_run_once_persist_failure_propagates() -> None:
    """If the crawl_run insert raises, run_once must re-raise (not swallow).
    Telemetry-loss is louder than a failed crawl per OPS-002 decision."""

    item = _item("Gamma headline", "good")
    sources: list[Any] = [_FakeSource("good", [item])]
    topic_repo = _FakeTopicRepo()
    crawl_run_repo = _RaisingCrawlRunRepo(RuntimeError("DB unreachable"))

    with pytest.raises(RuntimeError, match="DB unreachable"):
        await run_once(sources, topic_repo, crawl_run_repo, top_n=5)

    # Insert was actually attempted (regression guard against silent skip).
    assert crawl_run_repo.calls == 1


__all__: list[str] = []
