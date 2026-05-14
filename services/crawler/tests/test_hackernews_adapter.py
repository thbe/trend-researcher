"""Tests for the HackerNews source adapter (mocked httpx)."""

from __future__ import annotations

import json
from collections import Counter

import httpx

from crawler.adapters.sources.hackernews import HackerNewsSource


def _make_client(responses: dict[str, object], counter: Counter | None = None) -> httpx.AsyncClient:
    """Build an AsyncClient backed by MockTransport returning canned JSON.

    `responses` maps URL path suffix -> JSON-serializable payload.
    `counter` (optional) tallies hits per path suffix.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if counter is not None:
            counter[path] += 1
        for suffix, payload in responses.items():
            if path.endswith(suffix):
                return httpx.Response(200, content=json.dumps(payload))
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_returns_raw_items_in_rank_order() -> None:
    responses = {
        "/topstories.json": [100, 200, 300],
        "/item/100.json": {"id": 100, "title": "First", "url": "https://example.com/1"},
        "/item/200.json": {"id": 200, "title": "Second", "url": "https://example.com/2"},
        "/item/300.json": {"id": 300, "title": "Third", "url": "https://example.com/3"},
    }
    async with _make_client(responses) as client:
        source = HackerNewsSource(http_client=client)
        items = await source.fetch(3)

    assert len(items) == 3
    assert [i.title for i in items] == ["First", "Second", "Third"]
    assert [i.native_rank for i in items] == [1, 2, 3]
    assert all(i.source_name == "hackernews" for i in items)


async def test_fetch_skips_null_items() -> None:
    responses = {
        "/topstories.json": [100, 200, 300],
        "/item/100.json": {"id": 100, "title": "First", "url": "https://example.com/1"},
        "/item/200.json": None,
        "/item/300.json": {"id": 300, "title": "Third", "url": "https://example.com/3"},
    }
    async with _make_client(responses) as client:
        source = HackerNewsSource(http_client=client)
        items = await source.fetch(3)

    assert len(items) == 2
    titles = [i.title for i in items]
    ranks = [i.native_rank for i in items]
    assert titles == ["First", "Third"]
    # Rank for the third id stays 3 even though id #2 was dropped.
    assert ranks == [1, 3]


async def test_fetch_self_post_falls_back_to_hn_permalink() -> None:
    # No "url" field in payload -> Ask HN / Show HN style self-post.
    responses = {
        "/topstories.json": [42],
        "/item/42.json": {"id": 42, "title": "Ask HN: anything?"},
    }
    async with _make_client(responses) as client:
        source = HackerNewsSource(http_client=client)
        items = await source.fetch(1)

    assert len(items) == 1
    assert items[0].url == "https://news.ycombinator.com/item?id=42"


async def test_fetch_respects_top_n_slice() -> None:
    ids = list(range(1, 11))  # 1..10
    responses: dict[str, object] = {"/topstories.json": ids}
    for i in ids:
        responses[f"/item/{i}.json"] = {"id": i, "title": f"t{i}", "url": f"https://x/{i}"}

    counter: Counter[str] = Counter()
    async with _make_client(responses, counter=counter) as client:
        source = HackerNewsSource(http_client=client)
        items = await source.fetch(3)

    assert len(items) == 3
    item_hits = sum(1 for path in counter if path.startswith("/v0/item/"))
    assert item_hits == 3
