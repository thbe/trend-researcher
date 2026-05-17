"""``GET /topics`` — paginated topic list enriched with derived stats.

LEFT JOIN of ``topics`` (ORM) × ``v_topic_stats`` (Postgres view created in
Alembic 0003) so the route reports ``breadth`` and ``longevity_seconds``
from a single source of truth (STO-006 — derived columns live in the view,
not duplicated on the table or recomputed in Python).

Per CONTEXT G4 the view is consumed via lightweight ``Table(..., autoload=False)``
declaration (no ``Base.metadata`` entry, no ORM read-entity) — fewer files,
keeps the view out of ``Base.metadata.create_all`` / ``drop_all``.

Per CONTEXT G5 the contract is:
- ``sort`` whitelist ``{breadth, longevity, last_seen_at}`` with optional
  leading ``-`` for desc, default ``-last_seen_at``, non-matches → 400.
- ``limit`` ``Query(20, ge=1, le=100)``.
- Response wrapper ``{topics:[...], limit, sort}`` echoing the validated
  sort key (including the ``-`` prefix if any).
- No nested ``sources``, no ``topic_metadata`` on list rows (detail endpoint
  in 04-03 handles those).

Mounted at ``/api/topics`` (prefix applied in ``main.py``, per G2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas import TopicResponse, TopicsListResponse
from core.models import Topic

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


__all__ = ["router"]
