"""Unit tests for the ``CRAWLER_DISABLED_SOURCES`` env-driven source filter
in :func:`crawler.app.composition.build_sources` (Plan 03-03).

These tests are intentionally pure: no Postgres, no network. They flip the
env var with ``monkeypatch`` and assert on the source list returned by
:func:`build_sources`. The warning-vs-raise contract for unknown source
names is verified via :func:`structlog.testing.capture_logs`.
"""

from __future__ import annotations

import pytest
import structlog

from crawler.app.composition import build_sources

_ENV = "CRAWLER_DISABLED_SOURCES"
_ALL_NAMES = {"hackernews", "nyt_homepage", "google_news"}


def _names(sources) -> set[str]:
    return {s.name for s in sources}


def test_no_env_returns_all_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    sources = build_sources()
    assert len(sources) == 3
    assert _names(sources) == _ALL_NAMES


def test_disable_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "hackernews")
    sources = build_sources()
    assert _names(sources) == {"nyt_homepage", "google_news"}


def test_disable_multiple_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "hackernews, nyt_homepage")
    sources = build_sources()
    assert _names(sources) == {"google_news"}


def test_disable_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "HackerNews")
    sources = build_sources()
    assert "hackernews" not in _names(sources)
    assert _names(sources) == {"nyt_homepage", "google_news"}


def test_disable_whitespace_tolerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV, "  hackernews  ,  nyt_homepage  ")
    sources = build_sources()
    assert _names(sources) == {"google_news"}


def test_unknown_source_warns_but_doesnt_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV, "reddit,nonexistent")
    with structlog.testing.capture_logs() as captured:
        sources = build_sources()
    # All 3 real sources still returned — unknowns don't match anything.
    assert _names(sources) == _ALL_NAMES
    warnings = [
        e
        for e in captured
        if e.get("log_level") == "warning"
        and e.get("event") == "crawler.disabled_sources.unknown"
    ]
    assert len(warnings) == 1
    assert set(warnings[0]["unknown"]) == {"reddit", "nonexistent"}


def test_disable_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "hackernews,nyt_homepage,google_news")
    sources = build_sources()
    assert sources == []


def test_empty_string_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV, "")
    sources = build_sources()
    assert len(sources) == 3
    assert _names(sources) == _ALL_NAMES
