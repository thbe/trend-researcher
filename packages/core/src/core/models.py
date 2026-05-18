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

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
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
    # Plan 04.5-01 (ING-011, migration 0004): decoded publisher URL for
    # Google News CBM redirect tokens. NULL when the source isn't a
    # google_news redirect or when the in-process base64 decoder couldn't
    # extract a usable URL. SPA prefers this over `url` for clickability;
    # `url` is preserved AS-IS so we can re-derive on demand.
    resolved_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    native_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    topic: Mapped["Topic"] = relationship(back_populates="sources")


class CrawlRun(Base):
    """One row per ``crawler run-once`` invocation — operational telemetry.

    Written at the end of :func:`crawler.app.orchestrator.run_once` from the
    stats dict the orchestrator already computes. Read by the api service via
    ``GET /runs`` and by ``scripts/smoke_phase3.sh`` to assert that scheduled
    crawls actually fire (Phase 3, OPS-002).

    No PII / credentials / user content — just counts, timestamps, and the
    list of sources that failed during the run.
    """

    __tablename__ = "crawl_runs"
    __table_args__ = (
        Index("ix_crawl_runs_started_at", "started_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    started_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    finished_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    top_n: Mapped[int] = mapped_column(Integer, nullable=False)
    totals_fetched: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    totals_inserted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    totals_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    totals_skipped_within_run: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    totals_errors: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    per_source: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    failed_sources: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class User(Base):
    """Application user for login-page authentication (v0.5.2).

    Passwords are stored as bcrypt hashes. The seed user is upserted on app
    startup from AUTH_SEED_USERNAME / AUTH_SEED_PASSWORD env vars.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class CrawlConfig(Base):
    """Per-source crawl configuration (Phase 5).

    Single source of truth for mutable crawl settings. The crawler reads this
    table at the start of each run. The UI writes it. Cadence stays env-driven.
    """

    __tablename__ = "crawl_config"

    source_name: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    top_n: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    capture_summary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    feed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


__all__ = ["Base", "CrawlConfig", "CrawlRun", "Topic", "TopicSource", "User"]
