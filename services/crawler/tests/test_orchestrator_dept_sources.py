"""Unit tests for the Plan 10-02 union-query / subscription-fallback logic in
:func:`crawler.app.composition.build_sources_from_db`.

These tests are pure: no Postgres, no network. They feed
``build_sources_from_db`` a fake ``session_factory`` whose ``execute`` calls
return canned rows for the two queries the function issues:

1. ``SELECT * FROM crawl_config`` — technical per-source config.
2. ``SELECT DISTINCT source_name FROM department_sources WHERE enabled=true``
   — union of department subscriptions.

The contract under test (per 10-02 G5):

* The crawler runs the **intersection** of ``crawl_config`` rows and the
  *union* of every department's enabled subscriptions.
* If **no department** has subscribed to anything, the cron MUST NOT
  brick: fall back to all ``crawl_config`` rows and emit
  ``crawl_sources.no_department_subscriptions_falling_back`` WARNING.
* DB errors and an empty ``crawl_config`` table both fall back to the
  hardcoded :func:`build_sources` list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import structlog

from crawler.app.composition import build_sources_from_db


# --------------------------------------------------------------------------
# Test doubles
# --------------------------------------------------------------------------


@dataclass
class _CfgRow:
    """Stand-in for a ``CrawlConfig`` ORM row.

    Only the attributes ``build_sources_from_db`` actually reads.
    """

    source_name: str
    top_n: int = 50
    capture_summary: bool = True
    feed_url: str | None = None
    verify_ssl: bool = True


class _ScalarsResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _ExecResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarsResult:
        return _ScalarsResult(self._rows)


class _FakeSession:
    """Returns canned results based on call order.

    ``build_sources_from_db`` issues exactly two ``session.execute`` calls
    in a fixed order: (1) crawl_config rows, (2) department_sources
    subscription names. We pop from a queue.
    """

    def __init__(self, results: list[list[Any]]) -> None:
        self._queue = list(results)

    async def execute(self, _stmt: Any) -> _ExecResult:
        if not self._queue:
            raise AssertionError("unexpected extra execute() call")
        return _ExecResult(self._queue.pop(0))

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None


def _factory(cfg_rows: list[_CfgRow], sub_names: list[str]):
    """Build a session_factory callable that yields a fresh _FakeSession."""

    def make() -> _FakeSession:
        return _FakeSession([cfg_rows, sub_names])

    return make


def _raising_factory():
    """session_factory whose context manager raises on entry."""

    class _Broken:
        async def __aenter__(self) -> "_Broken":
            raise RuntimeError("simulated DB outage")

        async def __aexit__(self, *_exc: Any) -> None:  # pragma: no cover
            return None

    def make() -> _Broken:
        return _Broken()

    return make


def _names(sources) -> list[str]:
    return [s.name for s in sources]


# --------------------------------------------------------------------------
# Happy-path: intersection of crawl_config × subscriptions
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_union_intersects_crawl_config_with_subscriptions() -> None:
    """Only sources whose name is in BOTH crawl_config AND the subscription
    union are returned. Per-source ``top_n`` is preserved on the built
    source object.
    """
    cfg = [
        _CfgRow(source_name="hackernews", top_n=42),
        _CfgRow(
            source_name="nyt_homepage",
            top_n=33,
            feed_url="https://example.com/nyt.rss",
        ),
        _CfgRow(
            source_name="google_news",
            top_n=11,
            feed_url="https://example.com/gn.rss",
            capture_summary=False,
        ),
    ]
    # Only hackernews + google_news subscribed (across all depts).
    with structlog.testing.capture_logs() as captured:
        sources = await build_sources_from_db(_factory(cfg, ["hackernews", "google_news"]))

    assert sorted(_names(sources)) == ["google_news", "hackernews"]
    # Per-source top_n carried through.
    by_name = {s.name: s for s in sources}
    assert by_name["hackernews"].configured_top_n == 42
    assert by_name["google_news"].configured_top_n == 11
    # Happy-path log emitted, fallback log NOT emitted.
    events = {e.get("event") for e in captured}
    assert "crawl_sources.selected_via_department_sources_union" in events
    assert "crawl_sources.no_department_subscriptions_falling_back" not in events


@pytest.mark.asyncio
async def test_union_distinct_across_depts_is_deduped() -> None:
    """Distinct-on the DB side means the same source name only appears
    once in the union, even if N depts all subscribed to it.
    """
    cfg = [_CfgRow(source_name="hackernews")]
    # Caller (the SQL) already DISTINCTs, so we hand back one element here
    # to model that. The test guards that the function doesn't accidentally
    # double-build sources when the union has duplicate-looking strings —
    # we feed it an artificially repeated list to be safe.
    sources = await build_sources_from_db(
        _factory(cfg, ["hackernews", "hackernews", "hackernews"])
    )
    assert _names(sources) == ["hackernews"]


# --------------------------------------------------------------------------
# Fallback A: zero subscriptions → crawl every crawl_config row
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_subscriptions_falls_back_to_all_crawl_configs() -> None:
    """If no department has enabled any source, the cron must not brick.
    Crawl every known source from ``crawl_config`` and emit a WARNING so
    operators notice the subscription state is empty.
    """
    cfg = [
        _CfgRow(source_name="hackernews"),
        _CfgRow(source_name="nyt_homepage", feed_url="https://example.com/n.rss"),
    ]
    with structlog.testing.capture_logs() as captured:
        sources = await build_sources_from_db(_factory(cfg, []))

    assert sorted(_names(sources)) == ["hackernews", "nyt_homepage"]
    warnings = [
        e
        for e in captured
        if e.get("log_level") == "warning"
        and e.get("event") == "crawl_sources.no_department_subscriptions_falling_back"
    ]
    assert len(warnings) == 1
    assert warnings[0]["fallback_count"] == 2
    assert set(warnings[0]["fallback_names"]) == {"hackernews", "nyt_homepage"}
    # The happy-path INFO must NOT fire when fallback is used.
    events = {e.get("event") for e in captured}
    assert "crawl_sources.selected_via_department_sources_union" not in events
    assert "crawl_sources.built_from_fallback" in events


# --------------------------------------------------------------------------
# Fallback B: DB read error → hardcoded build_sources()
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_error_falls_back_to_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any exception reading the DB falls back to the hardcoded source
    list (preserves fresh-install / pre-migration behavior).
    """
    monkeypatch.delenv("CRAWLER_DISABLED_SOURCES", raising=False)
    with structlog.testing.capture_logs() as captured:
        sources = await build_sources_from_db(_raising_factory())
    # build_sources() returns 3 hardcoded sources.
    assert sorted(_names(sources)) == ["google_news", "hackernews", "nyt_homepage"]
    warnings = [
        e
        for e in captured
        if e.get("event") == "crawl_config.read_failed_fallback_hardcoded"
    ]
    assert len(warnings) == 1
    assert "simulated DB outage" in warnings[0]["error"]


# --------------------------------------------------------------------------
# Fallback C: empty crawl_config → hardcoded build_sources()
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_crawl_config_falls_back_to_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty ``crawl_config`` table is treated as "DB not yet seeded"
    and falls back to the hardcoded list — same as the pre-10-02
    behavior so fresh installs keep working.
    """
    monkeypatch.delenv("CRAWLER_DISABLED_SOURCES", raising=False)
    with structlog.testing.capture_logs() as captured:
        sources = await build_sources_from_db(_factory([], ["hackernews"]))
    assert sorted(_names(sources)) == ["google_news", "hackernews", "nyt_homepage"]
    events = {e.get("event") for e in captured}
    assert "crawl_config.empty_fallback_hardcoded" in events


# --------------------------------------------------------------------------
# Edge: RSS row without a feed_url is skipped with a warning
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_row_without_feed_url_is_skipped() -> None:
    """If a non-hackernews ``crawl_config`` row has no ``feed_url`` we
    can't build an :class:`RssSource` for it — skip + log warning,
    don't crash the whole crawl.
    """
    cfg = [
        _CfgRow(source_name="hackernews"),
        _CfgRow(source_name="mystery_rss", feed_url=None),
    ]
    with structlog.testing.capture_logs() as captured:
        sources = await build_sources_from_db(
            _factory(cfg, ["hackernews", "mystery_rss"])
        )
    assert _names(sources) == ["hackernews"]
    warnings = [
        e for e in captured if e.get("event") == "crawl_config.skip_no_feed_url"
    ]
    assert len(warnings) == 1
    assert warnings[0]["source_name"] == "mystery_rss"
