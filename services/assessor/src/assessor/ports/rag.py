"""RAG port — protocol for topic retrieval from the store."""

from __future__ import annotations

from typing import Protocol

from core import Topic


class TopicContext:
    """Context bundle for a single topic, ready for prompt injection."""

    def __init__(self, topic: Topic, source_summaries: list[str]) -> None:
        self.topic = topic
        self.source_summaries = source_summaries

    def to_prompt_text(self) -> str:
        """Render as text suitable for LLM context window."""
        lines = [
            f"Title: {self.topic.title}",
            f"Description: {self.topic.description or '(none)'}",
            f"First seen: {self.topic.first_seen_at}",
            f"Last seen: {self.topic.last_seen_at}",
            f"Observation count: {self.topic.observation_count}",
            f"Sources ({len(self.source_summaries)}):",
        ]
        for s in self.source_summaries:
            lines.append(f"  - {s}")
        return "\n".join(lines)


class RAGPort(Protocol):
    """Adapter contract for retrieving topic context from Postgres."""

    async def get_topic_context(self, topic_id: str) -> TopicContext | None:
        """Retrieve full context for a single topic by ID."""
        ...

    async def get_unassessed_topic_ids(self, limit: int = 50) -> list[str]:
        """Return topic IDs that have no business_cases row yet."""
        ...
