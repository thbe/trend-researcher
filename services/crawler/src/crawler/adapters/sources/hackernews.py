"""HackerNewsSource: ingest the HN front page via the public Firebase API.

Public, unauthenticated endpoints:
    GET  https://hacker-news.firebaseio.com/v0/topstories.json  -> list[int]
    GET  https://hacker-news.firebaseio.com/v0/item/{id}.json   -> dict | null

`null` is returned for deleted/dead stories — those are skipped.
Self-posts (Ask HN, Show HN) have no `url` field — fall back to the HN
permalink so downstream dedup + UI always have a working URL.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import structlog

from crawler.domain.raw_item import RawItem

_DEFAULT_BASE_URL = "https://hacker-news.firebaseio.com/v0"
_HN_PERMALINK = "https://news.ycombinator.com/item?id={id}"
_MAX_CONCURRENCY = 10
_DEFAULT_TIMEOUT = 10.0

_log = structlog.get_logger(__name__)


class HackerNewsSource:
    """SourcePort adapter for the HackerNews front page."""

    name = "hackernews"

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        verify_ssl: bool = True,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._base_url = base_url.rstrip("/")
        self._verify_ssl = verify_ssl

    async def fetch(self, top_n: int) -> list[RawItem]:
        """Fetch up to top_n front-page items in HN-native rank order."""
        if top_n <= 0:
            return []

        client, owns = self._acquire_client()
        try:
            ids = await self._fetch_topstory_ids(client)
            ids = ids[:top_n]
            return await self._fetch_items(client, ids)
        finally:
            if owns:
                await client.aclose()

    def _acquire_client(self) -> tuple[httpx.AsyncClient, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=self._verify_ssl), True

    async def _fetch_topstory_ids(self, client: httpx.AsyncClient) -> list[int]:
        resp = await client.get(f"{self._base_url}/topstories.json")
        resp.raise_for_status()
        return resp.json()

    async def _fetch_items(
        self, client: httpx.AsyncClient, ids: list[int]
    ) -> list[RawItem]:
        sem = asyncio.Semaphore(_MAX_CONCURRENCY)
        observed_at = datetime.now(timezone.utc)

        async def fetch_one(rank: int, item_id: int) -> RawItem | None:
            async with sem:
                resp = await client.get(f"{self._base_url}/item/{item_id}.json")
                resp.raise_for_status()
                payload = resp.json()
            if payload is None or not payload.get("title"):
                _log.warning("hn.missing_item", id=item_id, rank=rank)
                return None
            url = payload.get("url") or _HN_PERMALINK.format(id=payload["id"])
            return RawItem(
                title=payload["title"],
                url=url,
                source_name=self.name,
                native_rank=rank,
                observed_at=observed_at,
                raw_payload=payload,
            )

        results = await asyncio.gather(
            *(fetch_one(rank, item_id) for rank, item_id in enumerate(ids, start=1))
        )
        return [item for item in results if item is not None]
