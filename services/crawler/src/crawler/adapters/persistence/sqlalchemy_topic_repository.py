"""SqlAlchemy implementation of :class:`TopicRepositoryPort`.

Phase 1 simplification: ``find_candidates`` is a recent-window scan ordered
by ``last_seen_at DESC``. Most active topics are recent, and the actual dedup
decision is made in the domain layer (``crawler.domain.dedup.is_duplicate``)
on a small candidate set. A trigram-indexed search can replace this later
without touching the port contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Topic, TopicSource

from crawler.domain.raw_item import RawItem
from crawler.ports.topic_repository_port import TopicCandidate


class SqlAlchemyTopicRepository:
    """Persists topics + per-source observations using SQLAlchemy 2.x async."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_candidates(
        self, dedup_key: str, limit: int = 50
    ) -> list[TopicCandidate]:
        # Phase 1: recent-window scan. dedup_key is unused here on purpose —
        # the domain layer makes the actual fuzzy match against `title`.
        del dedup_key
        async with self._session_factory() as session:
            stmt = (
                select(
                    Topic.id,
                    Topic.title,
                    Topic.last_seen_at,
                    Topic.observation_count,
                )
                .order_by(Topic.last_seen_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()
        return [
            TopicCandidate(
                id=UUID(row.id) if isinstance(row.id, str) else row.id,
                title=row.title,
                last_seen_at=row.last_seen_at,
                observation_count=row.observation_count,
            )
            for row in rows
        ]

    async def insert_new(self, item: RawItem) -> UUID:
        async with self._session_factory() as session:
            topic = Topic(
                title=item.title,
                description=None,
                topic_metadata={"first_source": item.source_name},
                observation_count=1,
            )
            session.add(topic)
            await session.flush()  # populate topic.id

            session.add(
                TopicSource(
                    topic_id=topic.id,
                    source_name=item.source_name,
                    url=item.url,
                    native_rank=item.native_rank,
                    observed_at=item.observed_at,
                    raw_payload=item.raw_payload,
                )
            )
            await session.commit()
            topic_id = topic.id
        return UUID(topic_id) if isinstance(topic_id, str) else topic_id

    async def update_existing(self, topic_id: UUID, item: RawItem) -> None:
        topic_pk = str(topic_id)
        # Try the combined update + source insert. If the unique constraint
        # on (topic_id, source_name, url, observed_at) blows up, retry with
        # the topic update only so observation counters still advance.
        try:
            async with self._session_factory() as session:
                await self._bump_topic(session, topic_pk, item.observed_at)
                session.add(
                    TopicSource(
                        topic_id=topic_pk,
                        source_name=item.source_name,
                        url=item.url,
                        native_rank=item.native_rank,
                        observed_at=item.observed_at,
                        raw_payload=item.raw_payload,
                    )
                )
                await session.commit()
        except IntegrityError:
            # Duplicate (topic_id, source_name, url, observed_at) — the source
            # row insert is a no-op, but we still want the topic counters to
            # reflect this re-observation.
            async with self._session_factory() as session:
                await self._bump_topic(session, topic_pk, item.observed_at)
                await session.commit()

    @staticmethod
    async def _bump_topic(
        session: AsyncSession, topic_pk: str, observed_at: datetime
    ) -> None:
        await session.execute(
            update(Topic)
            .where(Topic.id == topic_pk)
            .values(
                last_seen_at=observed_at,
                observation_count=Topic.observation_count + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )


__all__ = ["SqlAlchemyTopicRepository"]
