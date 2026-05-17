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

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Topic, TopicSource

from crawler.adapters.sources.google_news_url import decode_google_news_url
from crawler.domain.raw_item import RawItem
from crawler.ports.topic_repository_port import TopicCandidate


_GOOGLE_NEWS_SOURCE = "google_news"


def _resolve_url_if_google_news(item: RawItem) -> str | None:
    """Return decoded publisher URL for google_news items, else None.

    Plan 04.5-01 / T04 (ING-011): Centralizes the source-name gate so both
    ``insert_new`` and ``update_existing`` use identical logic. The decoder
    itself logs on failure; this helper just chooses whether to invoke it
    at all (the caller in tests can also call the underlying decoder
    directly without source-name semantics).
    """
    if item.source_name != _GOOGLE_NEWS_SOURCE:
        return None
    return decode_google_news_url(item.url)


class SqlAlchemyTopicRepository:
    """Persists topics + per-source observations using SQLAlchemy 2.x async."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_candidates(
        self, dedup_key: str, limit: int = 5000
    ) -> list[TopicCandidate]:
        # Phase 1: recent-window scan. dedup_key is unused here on purpose —
        # the domain layer makes the actual fuzzy match against `title`.
        # Phase 2 hot-fix (Plan 02-04): default window widened from 50 to
        # 5000. The old 50 silently dropped any topic older than the 50
        # most-recent inserts, so on a multi-source crawl a topic ingested
        # by source A would not be found when source B re-observed it.
        # 5000 covers the v1 ~thousands-of-topics scale; Phase 3 replaces
        # this with an indexed lookup on a dedup_key column.
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
                description=item.description,
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
                    resolved_url=_resolve_url_if_google_news(item),
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
        resolved = _resolve_url_if_google_news(item)
        # Try the combined update + source insert. If the unique constraint
        # on (topic_id, source_name, url, observed_at) blows up, retry with
        # the topic update only so observation counters still advance.
        try:
            async with self._session_factory() as session:
                await self._bump_topic(
                    session,
                    topic_pk,
                    item.observed_at,
                    new_description=item.description,
                )
                session.add(
                    TopicSource(
                        topic_id=topic_pk,
                        source_name=item.source_name,
                        url=item.url,
                        resolved_url=resolved,
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
                await self._bump_topic(
                    session,
                    topic_pk,
                    item.observed_at,
                    new_description=item.description,
                )
                await session.commit()

    @staticmethod
    async def _bump_topic(
        session: AsyncSession,
        topic_pk: str,
        observed_at: datetime,
        *,
        new_description: str | None = None,
    ) -> None:
        # First-non-empty merge for description (Plan 04.5-01, D-Q1):
        # COALESCE keeps any existing non-NULL value and only fills NULL
        # with the new observation's description. This protects the first
        # observed framing of a topic from being overwritten by a later
        # source's summary (operator chose stability over freshness).
        await session.execute(
            update(Topic)
            .where(Topic.id == topic_pk)
            .values(
                last_seen_at=observed_at,
                observation_count=Topic.observation_count + 1,
                updated_at=datetime.now(timezone.utc),
                description=func.coalesce(Topic.description, new_description),
            )
        )


__all__ = ["SqlAlchemyTopicRepository"]
