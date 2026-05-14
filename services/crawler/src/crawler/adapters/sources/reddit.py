"""RedditJsonSource: ingest a subreddit's hot listing via the public JSON API.

Public, unauthenticated endpoint:
    GET https://www.reddit.com/r/{subreddit}/hot.json?limit={top_n}

Reddit may rate-limit (HTTP 429) requests without a meaningful User-Agent;
we set a project-identifying UA per Reddit API guidelines.

URL handling:
    - Link posts: `data.url` is an external URL — use it as-is.
    - Self-posts (text posts): `data.url` points back at reddit.com — use the
      permalink-prefixed canonical URL so downstream dedup + UI always have
      a working link to the discussion thread.

Items with empty/missing titles are skipped (logged); native_rank for
remaining items reflects the original listing position (gaps preserved).
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog

from crawler.domain.raw_item import RawItem

_USER_AGENT = (
    "Trend-Researcher/0.1 (internal PoC; +https://github.com/thbe/trend-researcher)"
)
_DEFAULT_BASE_URL = "https://www.reddit.com"
_DEFAULT_TIMEOUT = 10.0

_log = structlog.get_logger(__name__)


def _is_self_post_url(url: str | None) -> bool:
    """Return True if `url` points back into reddit.com (i.e. a self-post)."""
    if not url:
        return True
    return "reddit.com" in url


class RedditJsonSource:
    """SourcePort adapter for a subreddit's hot listing."""

    def __init__(
        self,
        name: str,
        subreddit: str,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self.name = name
        self.subreddit = subreddit
        self._client = http_client
        self._owns_client = http_client is None
        self._base_url = base_url.rstrip("/")

    async def fetch(self, top_n: int) -> list[RawItem]:
        """Fetch up to top_n hot items in subreddit-native rank order."""
        if top_n <= 0:
            return []

        client, owns = self._acquire_client()
        try:
            url = f"{self._base_url}/r/{self.subreddit}/hot.json"
            resp = await client.get(
                url,
                params={"limit": top_n},
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
            payload = resp.json()
        finally:
            if owns:
                await client.aclose()

        return self._parse_listing(payload)

    def _acquire_client(self) -> tuple[httpx.AsyncClient, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT), True

    def _parse_listing(self, payload: dict) -> list[RawItem]:
        observed_at = datetime.now(timezone.utc)
        children = payload.get("data", {}).get("children", [])
        items: list[RawItem] = []

        for rank, child in enumerate(children, start=1):
            data = child.get("data", {})
            title = data.get("title")
            if not title:
                _log.warning("reddit.missing_title", source=self.name, rank=rank)
                continue

            external_url = data.get("url")
            permalink = data.get("permalink", "")
            if _is_self_post_url(external_url) and permalink:
                url = f"https://www.reddit.com{permalink}"
            else:
                url = external_url

            items.append(
                RawItem(
                    title=title,
                    url=url,
                    source_name=self.name,
                    native_rank=rank,
                    observed_at=observed_at,
                    raw_payload=data,
                )
            )
        return items
