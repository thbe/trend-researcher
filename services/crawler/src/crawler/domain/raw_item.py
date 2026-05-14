"""Source-agnostic input contract for the ingest pipeline.

RawItem is the source-agnostic shape every SourcePort.fetch() returns.
Domain logic operates only on RawItem and its derivatives — adapters are
responsible for parsing source-specific payloads (HN JSON, Reddit JSON,
RSS XML, etc.) into RawItem.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RawItem:
    """A single trending/ranked item as returned by a SourcePort.

    Fields:
        title: Human-readable title of the item (used for dedup matching).
        url: Canonical URL for the item (used as part of the topic_sources
            uniqueness key).
        source_name: Stable identifier of the producing source
            (matches SourcePort.name).
        native_rank: Source-native ranking position (1 = top). May be None
            for sources that don't expose a numeric rank.
        observed_at: Timezone-aware UTC timestamp at which this item was
            observed by the crawler.
        raw_payload: Source-specific JSON-able dict, persisted as JSONB
            for later inspection. Never read by domain logic.
    """

    title: str
    url: str
    source_name: str
    native_rank: int | None
    observed_at: datetime
    raw_payload: dict[str, Any] = field(default_factory=dict)
