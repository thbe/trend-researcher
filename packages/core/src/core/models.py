"""SQLAlchemy 2.x ORM models for the Trend Researcher topic store.

The schema lives here in ``packages/core`` and is the single source of truth
for every service in the workspace (locked architectural decision — see
ARC-003 / b3 in .planning/REQUIREMENTS.md).

Notes
-----
- The Python attribute on :class:`Topic` is ``topic_metadata`` but it maps to
  the SQL column literally named ``metadata``. ``metadata`` is reserved on
  :class:`sqlalchemy.orm.DeclarativeBase` and cannot be used as an attribute
  name.
- ``observation_count`` and ``last_seen_at`` are denormalised counters on
  ``topics`` so the assessor service can sort cheaply, but breadth and
  longevity are NOT stored — they are computed from ``topic_sources`` via SQL
  at query time (STO-005).
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in :mod:`core.models`."""


class Topic(Base):
    """One row per distinct (deduplicated) topic observed across all sources."""

    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_seen_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )
    observation_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    # Python attribute is ``topic_metadata`` to avoid the reserved
    # DeclarativeBase ``metadata`` attribute. SQL column is ``metadata``.
    topic_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    sources: Mapped[list["TopicSource"]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TopicSource(Base):
    """One row per (topic, source, url, observed_at) observation.

    Many-to-one against :class:`Topic`. Re-crawls accumulate rows here while
    the parent ``topics`` row is updated in place (last_seen bumped,
    observation_count incremented).
    """

    __tablename__ = "topic_sources"
    __table_args__ = (
        UniqueConstraint(
            "topic_id",
            "source_name",
            "url",
            "observed_at",
            name="uq_topic_sources_topic_source_url_observed",
        ),
        Index("ix_topic_sources_topic_id", "topic_id"),
        Index("ix_topic_sources_source_name", "source_name"),
        Index("ix_topic_sources_observed_at", "observed_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    topic_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    native_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    topic: Mapped["Topic"] = relationship(back_populates="sources")


__all__ = ["Base", "Topic", "TopicSource"]
