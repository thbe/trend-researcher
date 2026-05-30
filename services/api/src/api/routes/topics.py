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

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import Column, MetaData, Table, and_, delete, exists, or_, select, func, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    ActiveDepartment,
    get_active_department,
    get_session,
    require_role,
)
from api.schemas import (
    TopicCleanupRequest,
    TopicCleanupResponse,
    TopicDetailResponse,
    TopicResponse,
    TopicSourceResponse,
    TopicsListResponse,
)
from core.models import BusinessCase, CrawlConfig, DepartmentSource, Topic, TopicSource

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


@router.get(
    "/topics",
    response_model=TopicsListResponse,
    dependencies=[Depends(require_role("viewer", "analyst", "dept_lead"))],
)
async def list_topics(
    sort: str = Query(_DEFAULT_SORT),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ad: ActiveDepartment = Depends(get_active_department),
    session: AsyncSession = Depends(get_session),
) -> TopicsListResponse:
    """Return up to ``limit`` topics joined with derived stats, sorted per ``sort``.

    Per Phase 10 (MT-006/MT-009): topics are filtered to those that have at
    least one ``topic_sources`` row whose ``source_name`` is enabled for the
    active department in ``department_sources``. ``relevance_verdict`` comes
    from the latest ``business_cases`` row scoped to the same department.

    NOTE on ``breadth``: stays a GLOBAL topic property (count of distinct
    sources observing it across the platform) — it is the "viral index" of
    the topic itself and is not narrowed to dept subscriptions on purpose.
    """

    key, desc = _parse_sort(sort)
    order_col = _SORT_COLUMNS[key]
    order_expr = order_col.desc() if desc else order_col.asc()

    dept_id = ad.department.id

    # Dept-scope predicate: this topic has at least one TopicSource whose
    # source is either (a) explicitly enabled for the active dept via
    # department_sources, OR (b) OWNED by the active dept (crawl_config.
    # department_id). The ownership branch honors the contract documented
    # in department_sources.py: owners are implicitly subscribed and their
    # owned sources are never togglable off. Without it, a dept that creates
    # a source via Crawl Config sees 0 topics from that source until they
    # also manually visit Source Subscriptions (which won't even show the
    # owned row as toggleable). This makes ownership self-sufficient.
    dept_source_exists = exists(
        select(1)
        .select_from(TopicSource)
        .outerjoin(
            DepartmentSource,
            and_(
                DepartmentSource.source_name == TopicSource.source_name,
                DepartmentSource.department_id == dept_id,
            ),
        )
        .outerjoin(
            CrawlConfig,
            CrawlConfig.source_name == TopicSource.source_name,
        )
        .where(
            TopicSource.topic_id == Topic.id,
            or_(
                and_(
                    DepartmentSource.department_id == dept_id,
                    DepartmentSource.enabled.is_(True),
                ),
                CrawlConfig.department_id == dept_id,
            ),
        )
        .correlate(Topic)
    )

    # Subquery: latest business case verdict per (topic, active_dept)
    latest_verdict = (
        select(BusinessCase.relevance_verdict)
        .where(
            BusinessCase.topic_id == Topic.id,
            BusinessCase.department_id == dept_id,
        )
        .order_by(BusinessCase.generated_at.desc())
        .limit(1)
        .correlate(Topic)
        .scalar_subquery()
        .label("relevance_verdict")
    )

    # Subquery: distinct source names as comma-separated string (global —
    # shows the full provenance trail of the topic, not narrowed to dept).
    source_names_sub = (
        select(func.string_agg(func.distinct(TopicSource.source_name), literal_column("', '")))
        .where(TopicSource.topic_id == Topic.id)
        .correlate(Topic)
        .scalar_subquery()
        .label("source_names")
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
            source_names_sub,
        )
        .select_from(
            Topic.__table__.outerjoin(  # type: ignore[attr-defined]
                _v_topic_stats,
                _v_topic_stats.c.topic_id == Topic.id,
            )
        )
        .where(dept_source_exists)
        .order_by(order_expr, Topic.id)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.mappings().all()

    # Total count for pagination — same dept filter applied.
    count_stmt = (
        select(func.count(Topic.id))
        .select_from(Topic)
        .where(dept_source_exists)
    )
    total = (await session.execute(count_stmt)).scalar() or 0

    return TopicsListResponse(
        topics=[TopicResponse.model_validate(dict(row)) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        sort=sort,
    )


@router.get(
    "/topics/{topic_id}",
    response_model=TopicDetailResponse,
    dependencies=[Depends(require_role("viewer", "analyst", "dept_lead"))],
)
async def get_topic(
    topic_id: UUID = Path(...),
    ad: ActiveDepartment = Depends(get_active_department),
    session: AsyncSession = Depends(get_session),
) -> TopicDetailResponse:
    """Return one topic + derived stats + ``topic_metadata`` + nested sources.

    Per Phase 10 (MT-006/MT-009): 404 if the topic has no ``topic_sources``
    row whose source is enabled for the active dept — a dept must not learn
    of topics it does not subscribe to even by guessing IDs.

    Per CONTEXT G7: ``sources`` ordered ``observed_at DESC`` (most recent
    observation first — matches operator's "what just happened to this topic"
    mental model). ``raw_payload`` deliberately omitted from the source
    projection — kept lean; Phase 5 can add behind a query flag.

    ``topic_id`` is typed as ``UUID`` so FastAPI auto-rejects malformed input
    with 422 before this handler ever runs (no SQL injection vector).
    """

    dept_id = ad.department.id

    dept_source_exists = exists(
        select(1)
        .select_from(TopicSource)
        .join(
            DepartmentSource,
            DepartmentSource.source_name == TopicSource.source_name,
        )
        .where(
            TopicSource.topic_id == Topic.id,
            DepartmentSource.department_id == dept_id,
            DepartmentSource.enabled.is_(True),
        )
        .correlate(Topic)
    )

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
        .where(and_(Topic.id == topic_id, dept_source_exists))
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


@router.post("/topics/cleanup", response_model=TopicCleanupResponse)
async def cleanup_topics(
    body: TopicCleanupRequest,
    session: AsyncSession = Depends(get_session),
) -> TopicCleanupResponse:
    """Manually purge topics / topic observations.

    Filters (AND-combined):
    - ``source_name``: restrict to observations from this source only.
    - ``older_than_days``: restrict to items older than N days
      (``observed_at`` for sources, ``last_seen_at`` for topics).

    At least one filter is required (empty body → 400) so an accidental
    call cannot wipe the entire store.

    Behaviour:
    - If ``source_name`` is given, delete matching ``topic_sources`` rows
      first, then sweep any ``topics`` left with zero remaining sources.
    - If ``source_name`` is omitted, delete ``topics`` whose
      ``last_seen_at`` is older than the cutoff (cascade removes their
      ``topic_sources``).
    """

    if body.source_name is None and body.older_than_days is None:
        raise HTTPException(
            status_code=400,
            detail="At least one of source_name or older_than_days is required.",
        )

    cutoff: datetime | None = None
    if body.older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=body.older_than_days)

    sources_deleted = 0
    topics_deleted = 0

    if body.source_name is not None:
        # Step 1: delete matching topic_sources rows.
        src_stmt = delete(TopicSource).where(TopicSource.source_name == body.source_name)
        if cutoff is not None:
            src_stmt = src_stmt.where(TopicSource.observed_at < cutoff)
        src_result = await session.execute(src_stmt)
        sources_deleted = int(src_result.rowcount or 0)  # type: ignore[attr-defined]

        # Step 2: delete orphan topics (no remaining sources at all).
        orphan_subq = (
            select(Topic.id)
            .outerjoin(TopicSource, TopicSource.topic_id == Topic.id)
            .group_by(Topic.id)
            .having(func.count(TopicSource.id) == 0)
        )
        topic_stmt = delete(Topic).where(Topic.id.in_(orphan_subq))
        topic_result = await session.execute(topic_stmt)
        topics_deleted = int(topic_result.rowcount or 0)  # type: ignore[attr-defined]
    else:
        # No source filter → age-only purge across all topics.
        assert cutoff is not None  # guaranteed by the 400 guard above
        topic_stmt = delete(Topic).where(Topic.last_seen_at < cutoff)
        topic_result = await session.execute(topic_stmt)
        topics_deleted = int(topic_result.rowcount or 0)  # type: ignore[attr-defined]
        # topic_sources rows are removed via ON DELETE CASCADE on the FK; we
        # don't report a separate count here (the cascade is opaque to us).

    await session.commit()

    return TopicCleanupResponse(
        topic_sources_deleted=sources_deleted,
        topics_deleted=topics_deleted,
        source_name=body.source_name,
        older_than_days=body.older_than_days,
    )


@router.post("/topics/cleanup-orphans", response_model=TopicCleanupResponse)
async def cleanup_orphan_topics(
    session: AsyncSession = Depends(get_session),
) -> TopicCleanupResponse:
    """Delete topics that have zero associated ``topic_sources`` rows.

    Orphans shouldn't normally exist (the FK has ON DELETE CASCADE), but they
    can appear if rows were inserted manually, if a previous cleanup raced
    with an ingest, or after a partial restore. Safe to run any time — it is
    a no-op when there are no orphans.
    """
    orphan_subq = (
        select(Topic.id)
        .outerjoin(TopicSource, TopicSource.topic_id == Topic.id)
        .group_by(Topic.id)
        .having(func.count(TopicSource.id) == 0)
    )
    result = await session.execute(delete(Topic).where(Topic.id.in_(orphan_subq)))
    topics_deleted = int(result.rowcount or 0)  # type: ignore[attr-defined]
    await session.commit()

    return TopicCleanupResponse(
        topic_sources_deleted=0,
        topics_deleted=topics_deleted,
        source_name=None,
        older_than_days=None,
    )


__all__ = ["router"]
