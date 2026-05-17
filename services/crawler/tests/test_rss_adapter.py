"""Unit tests for the RSS source adapter (TDD: RED → GREEN)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from crawler.adapters.sources.rss import RssSource

_UA = "Trend-Researcher/0.1 (internal PoC; +https://github.com/thbe/trend-researcher)"

# RSS 2.0 fixture: 3 valid items + 1 broken (missing <title>) at position 3.
# Expected ranks after parsing: 1, 2, 4 (gap preserved when item 3 is dropped).
_FIXTURE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>A test feed</description>
    <item>
      <title>First headline</title>
      <link>https://example.com/article-1</link>
      <pubDate>Mon, 06 Jan 2020 09:00:00 GMT</pubDate>
      <description>Summary one.</description>
    </item>
    <item>
      <title>Second headline</title>
      <link>https://example.com/article-2</link>
      <pubDate>Mon, 06 Jan 2020 10:00:00 GMT</pubDate>
      <description>Summary two.</description>
    </item>
    <item>
      <link>https://example.com/article-broken</link>
      <pubDate>Mon, 06 Jan 2020 11:00:00 GMT</pubDate>
      <description>Missing title item.</description>
    </item>
    <item>
      <title>Fourth headline</title>
      <link>https://example.com/article-4</link>
      <pubDate>Mon, 06 Jan 2020 12:00:00 GMT</pubDate>
      <description>Summary four.</description>
    </item>
  </channel>
</rss>
"""


def _make_client(body: str, captured: dict | None = None) -> httpx.AsyncClient:
    """Build an AsyncClient with a MockTransport that returns `body` and records the request."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["headers"] = dict(request.headers)
            captured["url"] = str(request.url)
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "application/rss+xml; charset=utf-8"},
        )

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=10.0)


async def test_returns_three_items_skipping_broken() -> None:
    client = _make_client(_FIXTURE_RSS)
    src = RssSource(name="test_feed", feed_url="https://example.com/rss", http_client=client)
    items = await src.fetch(top_n=10)
    await client.aclose()

    assert len(items) == 3, f"expected 3 items (broken one dropped), got {len(items)}"
    assert [it.native_rank for it in items] == [1, 2, 4], "rank gap should be preserved"
    assert items[0].title == "First headline"
    assert items[0].url == "https://example.com/article-1"
    assert items[1].title == "Second headline"
    assert items[2].title == "Fourth headline"


async def test_source_name_matches_constructor() -> None:
    client = _make_client(_FIXTURE_RSS)
    src = RssSource(name="nyt_homepage", feed_url="https://example.com/rss", http_client=client)
    items = await src.fetch(top_n=10)
    await client.aclose()

    assert all(it.source_name == "nyt_homepage" for it in items)
    assert src.name == "nyt_homepage"


async def test_raw_payload_is_json_serializable() -> None:
    client = _make_client(_FIXTURE_RSS)
    src = RssSource(name="test_feed", feed_url="https://example.com/rss", http_client=client)
    items = await src.fetch(top_n=10)
    await client.aclose()

    for item in items:
        # Must not raise — feedparser objects are NOT json-serializable, so we must
        # have stripped them down to plain dict primitives.
        payload_json = json.dumps(item.raw_payload)
        assert payload_json  # non-empty
        # Sanity: payload should at least carry the title and link.
        assert "title" in item.raw_payload
        assert "link" in item.raw_payload


async def test_observed_at_is_fetch_time_not_pubdate() -> None:
    client = _make_client(_FIXTURE_RSS)
    src = RssSource(name="test_feed", feed_url="https://example.com/rss", http_client=client)
    before = datetime.now(timezone.utc)
    items = await src.fetch(top_n=10)
    after = datetime.now(timezone.utc)
    await client.aclose()

    # The fixture's pubDate is 2020-01-06; observed_at must be "now", not the pubDate.
    for item in items:
        assert item.observed_at.year >= before.year
        assert before <= item.observed_at <= after, (
            f"observed_at {item.observed_at} outside fetch window [{before}, {after}]"
        )
        # And explicitly NOT the pubDate from the fixture.
        assert item.observed_at.year != 2020


async def test_user_agent_header_set() -> None:
    captured: dict = {}
    client = _make_client(_FIXTURE_RSS, captured=captured)
    src = RssSource(
        name="test_feed", feed_url="https://example.com/rss", http_client=client
    )
    await src.fetch(top_n=10)
    await client.aclose()

    assert captured.get("headers", {}).get("user-agent") == _UA


# --- Plan 04.5-01 / T01 (ING-010): RawItem.description plumbed from <description> ---

_FIXTURE_RSS_EMPTY_SUMMARY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <description>A test feed</description>
    <item>
      <title>Empty-summary headline</title>
      <link>https://example.com/article-empty</link>
      <pubDate>Mon, 06 Jan 2020 09:00:00 GMT</pubDate>
      <description>   </description>
    </item>
    <item>
      <title>No-summary-tag headline</title>
      <link>https://example.com/article-nosumtag</link>
      <pubDate>Mon, 06 Jan 2020 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


async def test_description_populated_from_summary() -> None:
    """When the feed entry has a non-empty <description>, RawItem.description
    carries it verbatim (whitespace trimmed)."""
    client = _make_client(_FIXTURE_RSS)
    src = RssSource(
        name="nyt_homepage",
        feed_url="https://example.com/rss",
        http_client=client,
    )
    items = await src.fetch(top_n=10)
    await client.aclose()

    # The 3 surviving items (1, 2, 4) all carry non-empty <description>.
    assert items[0].description == "Summary one."
    assert items[1].description == "Summary two."
    assert items[2].description == "Summary four."


async def test_description_is_none_when_summary_missing_or_blank() -> None:
    """Whitespace-only and missing-tag summaries collapse to None (so the
    repository's first-non-empty merge doesn't accidentally overwrite a
    real description with whitespace)."""
    client = _make_client(_FIXTURE_RSS_EMPTY_SUMMARY)
    src = RssSource(
        name="nyt_homepage",
        feed_url="https://example.com/rss",
        http_client=client,
    )
    items = await src.fetch(top_n=10)
    await client.aclose()

    assert len(items) == 2
    assert all(it.description is None for it in items)


# ---------------------------------------------------------------------------
# Plan 04.5.1: capture_summary=False drops descriptions at parse time.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_summary_false_drops_description():
    """Sources registered with capture_summary=False yield description=None.

    Used by Google News whose RSS <description> is an HTML link-list, not
    publisher prose. The raw value still lands in raw_payload['summary'] for
    forensic fidelity — only the topic-level RawItem.description is suppressed.
    """
    client = _make_client(_FIXTURE_RSS)
    source = RssSource(
        name="link_list_source",
        feed_url="https://example.com/rss",
        http_client=client,
        capture_summary=False,
    )
    items = await source.fetch(top_n=10)

    assert len(items) == 3  # same 3 valid items as the default fixture run
    for item in items:
        assert item.description is None, (
            f"capture_summary=False must zero out description, got {item.description!r}"
        )
        # forensic fidelity: raw_payload still carries summary
        assert "summary" in item.raw_payload


@pytest.mark.asyncio
async def test_capture_summary_default_true_preserves_description():
    """Default behaviour unchanged: capture_summary defaults to True."""
    client = _make_client(_FIXTURE_RSS)
    source = RssSource(
        name="prose_source",
        feed_url="https://example.com/rss",
        http_client=client,
    )
    items = await source.fetch(top_n=10)

    assert len(items) == 3
    # First item's description from fixture is "Summary one."
    assert items[0].description == "Summary one."
