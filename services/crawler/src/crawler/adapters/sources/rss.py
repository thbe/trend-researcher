"""RSS source adapter.

Fetches an RSS 2.0 / Atom feed via httpx, parses with feedparser (sync, run in
a thread), and returns a list of ``RawItem`` ordered by feed position.

Design notes (locked in CONTEXT.md / 02-02-PLAN.md):

* ``observed_at`` is the wall-clock time at fetch start, NOT the feed entry's
  published date. The pubDate is preserved inside ``raw_payload``.
* ``raw_payload`` is reduced to a plain JSON-serializable dict
  (``title``, ``link``, ``published``, ``summary``). feedparser returns
  ``FeedParserDict`` objects that are not directly JSON-encodable, so we strip
  them down before storing.
* Items missing ``title`` or ``link`` are skipped with a warning; the rank
  ``enumerate`` is NOT renumbered, matching the HN/Reddit adapters'
  rank-gap-preservation rule.
* Same User-Agent string as the Reddit adapter to keep us identifiable and
  polite to publishers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx
import structlog

from crawler.domain.raw_item import RawItem

_log = structlog.get_logger(__name__)

_USER_AGENT = (
    "Trend-Researcher/0.1 (internal PoC; +https://github.com/thbe/trend-researcher)"
)
_DEFAULT_TIMEOUT = 10.0
_ACCEPT = "application/rss+xml, application/xml;q=0.9, */*;q=0.8"


class RssSource:
    """Adapter conforming to ``SourcePort`` for any RSS 2.0 / Atom feed."""

    def __init__(
        self,
        name: str,
        feed_url: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._feed_url = feed_url
        self._http_client = http_client

    async def fetch(self, top_n: int) -> list[RawItem]:
        """Return up to ``top_n`` items from the feed, in feed order."""
        observed_at = datetime.now(timezone.utc)
        client, owns = self._acquire_client()
        try:
            response = await client.get(
                self._feed_url,
                headers={"User-Agent": _USER_AGENT, "Accept": _ACCEPT},
            )
            response.raise_for_status()
            body = response.text
        finally:
            if owns:
                await client.aclose()

        # feedparser is synchronous and CPU-ish on large feeds — push to a thread.
        parsed = await asyncio.to_thread(feedparser.parse, body)
        return self._build_items(parsed, top_n=top_n, observed_at=observed_at)

    # ------------------------------------------------------------------ helpers

    def _acquire_client(self) -> tuple[httpx.AsyncClient, bool]:
        """Return (client, owns). If we own it, caller must aclose() it."""
        if self._http_client is not None:
            return self._http_client, False
        return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT), True

    def _build_items(
        self,
        parsed: Any,
        *,
        top_n: int,
        observed_at: datetime,
    ) -> list[RawItem]:
        items: list[RawItem] = []
        entries = list(parsed.entries[:top_n])
        for rank, entry in enumerate(entries, start=1):
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                _log.warning(
                    "rss.missing_field",
                    source=self.name,
                    rank=rank,
                    has_title=bool(title),
                    has_link=bool(link),
                )
                continue

            payload: dict[str, Any] = {
                "title": title,
                "link": link,
                "published": entry.get("published"),
                "summary": entry.get("summary"),
            }

            items.append(
                RawItem(
                    title=title,
                    url=link,
                    source_name=self.name,
                    native_rank=rank,
                    observed_at=observed_at,
                    raw_payload=payload,
                )
            )
        return items
