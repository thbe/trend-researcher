"""Postgres RAG adapter — retrieves topic context from the topic store."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import Topic, TopicSource
from assessor.ports.rag import TopicContext


class PostgresRAGAdapter:
    """RAG adapter that reads directly from Postgres (no vector store in v1)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_topic_context(self, topic_id: str) -> TopicContext | None:
        """Retrieve full context for a single topic by ID."""
        async with self._session_factory() as session:
            topic = await session.get(Topic, topic_id)
            if topic is None:
                return None

            result = await session.execute(
                select(TopicSource)
                .where(TopicSource.topic_id == topic_id)
                .order_by(TopicSource.observed_at.desc())
            )
            sources = result.scalars().all()

            source_summaries = []
            for s in sources:
                summary = f"{s.source_name} (rank {s.native_rank}, {s.observed_at})"
                if s.url:
                    summary += f" — {s.url}"
                source_summaries.append(summary)

            return TopicContext(topic=topic, source_summaries=source_summaries)

    async def get_unassessed_topic_ids(self, limit: int = 50) -> list[str]:
        """Return topic IDs that have no business_cases row yet."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT t.id FROM topics t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM business_cases bc WHERE bc.topic_id = t.id
                    )
                    ORDER BY t.last_seen_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )
            return [row[0] for row in result.all()]
