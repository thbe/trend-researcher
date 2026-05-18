"""``GET /topics`` and ``GET /topics/{id}`` — paginated list + per-topic detail.

LEFT JOIN of ``topics`` (ORM) × ``v_topic_stats`` (Postgres view created in
Alembic 0003) so both routes report ``breadth`` and ``longevity_seconds``
from a single source of truth (STO-006 — derived columns live in the view,
not duplicated on the table or recomputed in Python).

Per CONTEXT G4 the view is consumed via lightweight ``Table(..., autoload=False)``
declaration (no ``Base.metadata`` entry, no ORM read-entity) — fewer files,
keeps the view out of ``Base.metadata.create_all`` / ``drop_all``.

Per CONTEXT G5 (list) the contract is:
- ``sort`` whitelist ``{breadth, longevity, last_seen_at}`` with optional
  leading ``-`` for desc, default ``-last_seen_at``, non-matches → 400.
- ``limit`` ``Query(20, ge=1, le=100)``.
- Response wrapper ``{topics:[...], limit, sort}`` echoing the validated
  sort key (including the ``-`` prefix if any).
- No nested ``sources``, no ``topic_metadata`` on list rows (detail endpoint
  in 04-03 handles those).

Per CONTEXT G7 (detail) the contract is:
- ``topic_id`` is UUID (FastAPI auto-validates → 422 on malformed).
- 404 if not found; 200 returns ``TopicDetailResponse``.
- ``sources`` array ordered ``observed_at DESC``; ``topic_metadata`` included;
  no ``raw_payload`` on the source projection (kept lean).

Mounted at ``/api/topics`` (prefix applied in ``main.py``, per G2).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas import (
    TopicDetailResponse,
    TopicResponse,
    TopicSourceResponse,
    TopicsListResponse,
)
from core.models import Topic, TopicSource, BusinessCase

router = APIRouter()

# Lightweight handle to v_topic_stats — declared, not autoloaded, so this
# module stays sync-import-safe and the view never ends up on Base.metadata.
# Columns mirror Alembic 0003: topic_id (FK to topics.id), breadth, longevity_seconds.
_v_topic_stats = Table(
    "v_topic_stats",
    MetaData(),
    Column("topic_id"),
    Column("breadth"),
    Column("longevity_seconds"),
)

# Whitelisted sort keys → orderable column expression.
# Per G5 these are the only legal values for the ``sort`` query param (with
# or without a leading ``-``). Anything else → 400.
_SORT_COLUMNS = {
    "breadth": _v_topic_stats.c.breadth,
    "longevity": _v_topic_stats.c.longevity_seconds,
    "last_seen_at": Topic.last_seen_at,
}

_DEFAULT_SORT = "-last_seen_at"


def _parse_sort(sort: str) -> tuple[str, bool]:
    """Return ``(key, desc)``; raise 400 if ``key`` not in the whitelist.

    A leading ``-`` selects descending order; absence selects ascending.
    The bare key (without ``-``) must be in ``_SORT_COLUMNS`` — any other
    value is rejected with HTTP 400 so consumers find typos fast.
    """

    desc = sort.startswith("-")
    key = sort[1:] if desc else sort
    if key not in _SORT_COLUMNS:
        allowed = ", ".join(sorted(_SORT_COLUMNS))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort key {sort!r}. Allowed: {allowed} (each may be prefixed with '-' for desc).",
        )
    return key, desc


@router.get("/topics", response_model=TopicsListResponse)
async def list_topics(
    sort: str = Query(_DEFAULT_SORT),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> TopicsListResponse:
    """Return up to ``limit`` topics joined with derived stats, sorted per ``sort``."""

    key, desc = _parse_sort(sort)
    order_col = _SORT_COLUMNS[key]
    order_expr = order_col.desc() if desc else order_col.asc()

    # Subquery: latest business case verdict per topic
    latest_verdict = (
        select(BusinessCase.relevance_verdict)
        .where(BusinessCase.topic_id == Topic.id)
        .order_by(BusinessCase.generated_at.desc())
        .limit(1)
        .correlate(Topic)
        .scalar_subquery()
        .label("relevance_verdict")
    )

    stmt = (
        select(
            Topic.id,
            Topic.title,
            Topic.description,
            Topic.first_seen_at,
            Topic.last_seen_at,
            Topic.observation_count,
            _v_topic_stats.c.breadth,
            _v_topic_stats.c.longevity_seconds,
            latest_verdict,
        )
        .select_from(
            Topic.__table__.outerjoin(  # type: ignore[attr-defined]
                _v_topic_stats,
                _v_topic_stats.c.topic_id == Topic.id,
            )
        )
        .order_by(order_expr, Topic.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.mappings().all()

    return TopicsListResponse(
        topics=[TopicResponse.model_validate(dict(row)) for row in rows],
        limit=limit,
        sort=sort,
    )


@router.get("/topics/{topic_id}", response_model=TopicDetailResponse)
async def get_topic(
    topic_id: UUID = Path(...),
    session: AsyncSession = Depends(get_session),
) -> TopicDetailResponse:
    """Return one topic + derived stats + ``topic_metadata`` + nested sources.

    Per CONTEXT G7: ``sources`` ordered ``observed_at DESC`` (most recent
    observation first — matches operator's "what just happened to this topic"
    mental model). ``raw_payload`` deliberately omitted from the source
    projection — kept lean; Phase 5 can add behind a query flag.

    ``topic_id`` is typed as ``UUID`` so FastAPI auto-rejects malformed input
    with 422 before this handler ever runs (no SQL injection vector).
    """

    topic_stmt = (
        select(
            Topic.id,
            Topic.title,
            Topic.description,
            Topic.first_seen_at,
            Topic.last_seen_at,
            Topic.observation_count,
            Topic.topic_metadata,
            _v_topic_stats.c.breadth,
            _v_topic_stats.c.longevity_seconds,
        )
        .select_from(
            Topic.__table__.outerjoin(  # type: ignore[attr-defined]
                _v_topic_stats,
                _v_topic_stats.c.topic_id == Topic.id,
            )
        )
        .where(Topic.id == topic_id)
    )
    topic_row = (await session.execute(topic_stmt)).mappings().first()
    if topic_row is None:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found")

    sources_stmt = (
        select(TopicSource)
        .where(TopicSource.topic_id == topic_id)
        .order_by(TopicSource.observed_at.desc())
    )
    source_rows = (await session.execute(sources_stmt)).scalars().all()

    payload = dict(topic_row)
    # COALESCE missing breadth/longevity to 0 (LEFT JOIN may return NULL for a
    # topic with no rows in the view — defensive; in practice every topic has
    # a v_topic_stats row because the view is unconditional).
    if payload.get("breadth") is None:
        payload["breadth"] = 0
    if payload.get("longevity_seconds") is None:
        payload["longevity_seconds"] = 0
    # topic_metadata can be NULL in the DB; coerce to empty dict for the response.
    if payload.get("topic_metadata") is None:
        payload["topic_metadata"] = {}
    payload["sources"] = [TopicSourceResponse.model_validate(s) for s in source_rows]

    return TopicDetailResponse.model_validate(payload)


__all__ = ["router"]
