"""GET /api/dashboard — aggregate counts for the dashboard view."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from core.models import Topic, BusinessCase

router = APIRouter()


class DashboardResponse(BaseModel):
    total_topics: int
    assessed_topics: int
    opportunities: int
    risks: int
    neutral: int


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    session: AsyncSession = Depends(get_session),
) -> DashboardResponse:
    """Return aggregate counts for the dashboard."""

    # Total topics
    total_topics = (await session.execute(select(func.count(Topic.id)))).scalar() or 0

    # Count by category from the latest business case per topic
    # Use a lateral/distinct-on to get only the latest assessment per topic
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
                    ORDER BY topic_id, generated_at DESC
                ) latest
                GROUP BY 1
            """)
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
