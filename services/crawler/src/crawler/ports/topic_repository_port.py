"""TopicRepositoryPort: protocol the dedup-and-upsert flow uses to persist topics."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from crawler.domain.raw_item import RawItem


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    """Lightweight projection of an existing Topic for dedup matching.

    We don't expose the full SQLAlchemy Topic model across the port boundary —
    the domain only needs id and title to decide 'same topic?'.
    """

    id: UUID
    title: str
    last_seen_at: datetime
    observation_count: int


class TopicRepositoryPort(Protocol):
    async def find_candidates(
        self, dedup_key: str, limit: int = 50
    ) -> list[TopicCandidate]:
        """Return existing topics that may match the given dedup_key.

        Implementation may use trigram, ILIKE, or simply return recent
        topics — the dedup decision is made in the domain layer.
        """
        ...

    async def insert_new(self, item: RawItem) -> UUID:
        """Insert a new Topic and the first TopicSource row, return new topic id."""
        ...

    async def update_existing(self, topic_id: UUID, item: RawItem) -> None:
        """Append a new TopicSource row, bump last_seen_at, increment observation_count.

        If a TopicSource row with the same (source_name, url, observed_at)
        already exists, this is a no-op for that row (the unique constraint
        handles it).
        """
        ...
