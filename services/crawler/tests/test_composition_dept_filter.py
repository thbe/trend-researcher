"""Unit tests for the dept-scoped filter branch of
:func:`crawler.app.composition.build_sources_from_db` (Plan 10-02 T09).

Pattern mirrors :mod:`test_orchestrator_dept_sources` — pure fake-session,
no Postgres, no network. Specifically guards the contract that an explicit
``department_id`` kwarg:

* applies the ``department_sources.department_id = :id`` filter,
* returns ``[]`` + emits ``crawl_sources.dept_scope_empty`` when that dept
  has zero enabled subscriptions (no fallback expansion — see G5),
* still intersects with ``crawl_config``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
import structlog

from crawler.app.composition import build_sources_from_db


# --------------------------------------------------------------------------
# Reused fakes (kept local so this file stays independent).
# --------------------------------------------------------------------------


@dataclass
class _CfgRow:
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
    """Returns canned rows for the two execute() calls, in order."""

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
    def make() -> _FakeSession:
        return _FakeSession([cfg_rows, sub_names])

    return make


def _names(sources) -> list[str]:
    return [s.name for s in sources]


# --------------------------------------------------------------------------
# Dept-scoped happy path: dept subscriptions ∩ crawl_config.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dept_scope_returns_only_dept_subscriptions() -> None:
    """``department_id=<uuid>`` builds only sources from that dept's enabled
    subscriptions. The test simulates the SQL filter by handing back the
    pre-filtered subscription list the DB would have returned.
    """
    dept_id = uuid4()
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
        ),
    ]
    # Pretend this dept only subscribed to hackernews.
    with structlog.testing.capture_logs() as captured:
        sources = await build_sources_from_db(
            _factory(cfg, ["hackernews"]),
            department_id=dept_id,
        )

    assert _names(sources) == ["hackernews"]
    # Happy-path log fires (selection, NOT dept_scope_empty, NOT fallback).
    events = {e.get("event") for e in captured}
    assert "crawl_sources.selected_via_department_sources_union" in events
    assert "crawl_sources.dept_scope_empty" not in events
    assert "crawl_sources.no_department_subscriptions_falling_back" not in events


@pytest.mark.asyncio
async def test_dept_scope_accepts_uuid_string() -> None:
    """``department_id`` is documented as ``UUID | None`` but callers in
    practice forward whatever ``Department.id`` is (UUID-as-string per
    ORM). The build function must handle either."""
    dept_uuid = uuid4()
    cfg = [_CfgRow(source_name="hackernews")]
    sources_a = await build_sources_from_db(
        _factory(cfg, ["hackernews"]), department_id=dept_uuid
    )
    sources_b = await build_sources_from_db(
        _factory(cfg, ["hackernews"]), department_id=UUID(str(dept_uuid))
    )
    assert _names(sources_a) == ["hackernews"]
    assert _names(sources_b) == ["hackernews"]


# --------------------------------------------------------------------------
# Dept-scoped empty: NO fallback expansion (intentional, see G5 / T09).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dept_scope_empty_returns_empty_list_no_fallback() -> None:
    """Explicit dept scope + zero subscriptions = empty list. Crucially,
    we do NOT fall back to "crawl every known source" — that would leak
    other depts' sources through an explicit per-dept trigger.
    """
    dept_id = uuid4()
    cfg = [
        _CfgRow(source_name="hackernews"),
        _CfgRow(source_name="nyt_homepage", feed_url="https://example.com/n.rss"),
    ]
    with structlog.testing.capture_logs() as captured:
        sources = await build_sources_from_db(
            _factory(cfg, []), department_id=dept_id
        )

    assert sources == []
    events = [e for e in captured if e.get("event") == "crawl_sources.dept_scope_empty"]
    assert len(events) == 1
    assert events[0]["department_id"] == str(dept_id)
    # The all-depts fallback warning must NOT fire here.
    fb_events = {e.get("event") for e in captured}
    assert "crawl_sources.no_department_subscriptions_falling_back" not in fb_events


# --------------------------------------------------------------------------
# Regression guard: department_id=None preserves pre-T09 behavior.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unscoped_call_still_falls_back_on_empty_subscriptions() -> None:
    """When called without ``department_id`` (global cron path), the
    all-depts fallback must still fire on empty subscriptions — the T09
    no-fallback rule applies *only* to explicit dept-scoped calls.
    """
    cfg = [_CfgRow(source_name="hackernews")]
    with structlog.testing.capture_logs() as captured:
        sources = await build_sources_from_db(_factory(cfg, []))
    assert _names(sources) == ["hackernews"]
    events = {e.get("event") for e in captured}
    assert "crawl_sources.no_department_subscriptions_falling_back" in events
    assert "crawl_sources.dept_scope_empty" not in events
