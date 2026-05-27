"""GET /api/dashboard — aggregate counts scoped to the active department.

Phase 10 (MT-006/MT-009):
- ``total_topics`` counts only topics whose source set intersects the active
  dept's enabled subscriptions in ``department_sources``.
- BC-derived counts (assessed/opportunities/risks/neutral) are filtered to
  ``business_cases.department_id = active_dept`` so each dept sees its own
  assessment landscape.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    ActiveDepartment,
    get_active_department,
    get_session,
    require_role,
)
from core.models import DepartmentSource, Topic, TopicSource

router = APIRouter()


class DashboardResponse(BaseModel):
    total_topics: int
    assessed_topics: int
    opportunities: int
    risks: int
    neutral: int


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    dependencies=[Depends(require_role("viewer", "analyst", "dept_lead"))],
)
async def get_dashboard(
    ad: ActiveDepartment = Depends(get_active_department),
    session: AsyncSession = Depends(get_session),
) -> DashboardResponse:
    """Return aggregate counts for the active department."""

    dept_id = ad.department.id

    # Total topics visible to this dept: those with at least one TopicSource
    # row whose source_name is enabled for this dept in department_sources.
    total_topics_stmt = (
        select(func.count(func.distinct(Topic.id)))
        .select_from(Topic)
        .join(TopicSource, TopicSource.topic_id == Topic.id)
        .join(
            DepartmentSource,
            DepartmentSource.source_name == TopicSource.source_name,
        )
        .where(
            DepartmentSource.department_id == dept_id,
            DepartmentSource.enabled.is_(True),
        )
    )
    total_topics = (await session.execute(total_topics_stmt)).scalar() or 0

    # Category counts from the latest business case per (topic, dept).
    # Filtered to BCs owned by the active dept.
    category_counts = (
        await session.execute(
            text("""
                SELECT
                    coalesce(raw_response->'parsed'->>'category', 'neutral') as category,
                    count(*) as cnt
                FROM (
                    SELECT DISTINCT ON (topic_id)
                        topic_id, raw_response
                    FROM business_cases
                    WHERE department_id = :dept_id
                    ORDER BY topic_id, generated_at DESC
                ) latest
                GROUP BY 1
            """),
            {"dept_id": dept_id},
        )
    ).all()

    opportunities = 0
    risks = 0
    neutral = 0
    assessed = 0
    for row in category_counts:
        cat, cnt = row[0], row[1]
        assessed += cnt
        if cat == "opportunity":
            opportunities = cnt
        elif cat == "risk":
            risks = cnt
        else:
            neutral = cnt

    return DashboardResponse(
        total_topics=total_topics,
        assessed_topics=assessed,
        opportunities=opportunities,
        risks=risks,
        neutral=neutral,
    )


__all__ = ["router"]
