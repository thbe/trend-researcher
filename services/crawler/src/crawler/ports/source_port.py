"""SourcePort: protocol every ingest source adapter must satisfy."""

from typing import Protocol, runtime_checkable

from crawler.domain.raw_item import RawItem


@runtime_checkable
class SourcePort(Protocol):
    """A source of trending items (HN, Reddit, RSS feed, etc.).

    Each adapter implements this protocol. Sources are discovered and
    registered by the app composition root.
    """

    name: str
    """Stable identifier persisted in topic_sources.source_name."""

    async def fetch(self, top_n: int) -> list[RawItem]:
        """Return up to top_n items in source-native ranking order.

        native_rank on each RawItem MUST reflect the source's own
        ranking (1 = top). Sources MUST NOT normalize across sources.
        """
        ...
