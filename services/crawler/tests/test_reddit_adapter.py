"""Tests for the Reddit JSON source adapter (mocked httpx)."""

from __future__ import annotations

import json

import httpx

from crawler.adapters.sources.reddit import RedditJsonSource

_UA = "Trend-Researcher/0.1 (internal PoC; +https://github.com/thbe/trend-researcher)"


def _reddit_listing(children: list[dict]) -> dict:
    """Wrap children in Reddit's standard listing envelope."""
    return {
        "kind": "Listing",
        "data": {
            "children": [{"kind": "t3", "data": child} for child in children],
        },
    }


def _make_client(payload: dict, captured: dict | None = None) -> httpx.AsyncClient:
    """Build an AsyncClient backed by MockTransport returning canned JSON.

    `captured` (optional): records the last request's headers + URL.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["headers"] = dict(request.headers)
            captured["url"] = str(request.url)
        return httpx.Response(200, content=json.dumps(payload))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# 4-item fixture: 3 valid + 1 with empty title (must be skipped, rank gap preserved).
_FIXTURE_CHILDREN = [
    {
        "title": "Cast iron pan I bought 30 years ago still going strong",
        "url": "https://i.imgur.com/cast-iron.jpg",
        "permalink": "/r/BuyItForLife/comments/abc1/cast_iron/",
    },
    {
        "title": "Recommendations for buy-it-for-life dishwasher?",
        "url": "https://www.reddit.com/r/BuyItForLife/comments/abc2/dishwasher_rec/",
        "permalink": "/r/BuyItForLife/comments/abc2/dishwasher_rec/",
    },
    {
        # broken: empty title -> should be skipped, next item keeps rank 4
        "title": "",
        "url": "https://example.com/broken",
        "permalink": "/r/BuyItForLife/comments/abc3/broken/",
    },
    {
        "title": "Patagonia jacket review after 15 years",
        "url": "https://blog.example.com/patagonia-15y",
        "permalink": "/r/BuyItForLife/comments/abc4/patagonia/",
    },
]


async def test_fetch_returns_three_items_with_correct_ranks() -> None:
    payload = _reddit_listing(_FIXTURE_CHILDREN)
    async with _make_client(payload) as client:
        source = RedditJsonSource(
            name="reddit_bifl", subreddit="BuyItForLife", http_client=client
        )
        items = await source.fetch(4)

    assert len(items) == 3
    titles = [i.title for i in items]
    ranks = [i.native_rank for i in items]
    assert titles == [
        "Cast iron pan I bought 30 years ago still going strong",
        "Recommendations for buy-it-for-life dishwasher?",
        "Patagonia jacket review after 15 years",
    ]
    # Rank gap preserved: skipped item had rank 3, next item keeps rank 4.
    assert ranks == [1, 2, 4]


async def test_self_post_uses_permalink() -> None:
    # Item 2 in the fixture: data.url points back into reddit.com -> self-post.
    payload = _reddit_listing([_FIXTURE_CHILDREN[1]])
    async with _make_client(payload) as client:
        source = RedditJsonSource(
            name="reddit_bifl", subreddit="BuyItForLife", http_client=client
        )
        items = await source.fetch(1)

    assert len(items) == 1
    assert items[0].url == "https://www.reddit.com/r/BuyItForLife/comments/abc2/dishwasher_rec/"


async def test_link_post_uses_external_url() -> None:
    # Item 1 in the fixture: data.url is an external imgur link.
    payload = _reddit_listing([_FIXTURE_CHILDREN[0]])
    async with _make_client(payload) as client:
        source = RedditJsonSource(
            name="reddit_bifl", subreddit="BuyItForLife", http_client=client
        )
        items = await source.fetch(1)

    assert len(items) == 1
    assert items[0].url == "https://i.imgur.com/cast-iron.jpg"


async def test_source_name_matches_constructor() -> None:
    payload = _reddit_listing([_FIXTURE_CHILDREN[0]])
    async with _make_client(payload) as client:
        source = RedditJsonSource(
            name="reddit_retail", subreddit="retail", http_client=client
        )
        items = await source.fetch(1)

    assert len(items) == 1
    assert items[0].source_name == "reddit_retail"


async def test_user_agent_header_set() -> None:
    captured: dict = {}
    payload = _reddit_listing([_FIXTURE_CHILDREN[0]])
    async with _make_client(payload, captured=captured) as client:
        source = RedditJsonSource(
            name="reddit_bifl", subreddit="BuyItForLife", http_client=client
        )
        await source.fetch(1)

    assert captured["headers"].get("user-agent") == _UA
    # And the URL must hit the right subreddit's hot.json endpoint.
    assert "/r/BuyItForLife/hot.json" in captured["url"]
