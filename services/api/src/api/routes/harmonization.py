"""Harmonization endpoints (Phase 10, plan 10-05, MT-011 / MT-012).

Cross-department side-by-side view of all business cases for a topic, plus
an optional admin-authored "Net View" meta-assessment.

Routes:
- GET  /api/topics/{topic_id}/harmonization — any authenticated user
- PUT  /api/topics/{topic_id}/harmonization — dept_lead (any dept) or superadmin
- DELETE /api/topics/{topic_id}/harmonization — same write auth
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import (
    AssessmentFramework,
    BusinessCase,
    Department,
    Topic,
    TopicHarmonization,
    User,
)
from api.dependencies import get_current_user, get_session, require_can_harmonize
from api.schemas import (
    HarmonizationBusinessCaseEntry,
    HarmonizationNetView,
    HarmonizationPutRequest,
    HarmonizationResponse,
)

router = APIRouter(tags=["harmonization"])


async def _load_harmonization(
    topic_id: str,
    session: AsyncSession,
) -> HarmonizationResponse:
    """Build the full harmonization response for a topic."""

    # Load topic
    topic_result = await session.execute(
        select(Topic).where(Topic.id == topic_id)
    )
    topic = topic_result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )

    # Load all business cases for this topic (cross-department)
    bc_result = await session.execute(
        select(BusinessCase)
        .where(BusinessCase.topic_id == topic_id)
        .options(
            selectinload(BusinessCase.department),
            selectinload(BusinessCase.framework),
        )
        .order_by(BusinessCase.created_at.desc())
    )
    business_cases_rows = bc_result.scalars().all()

    business_cases = [
        HarmonizationBusinessCaseEntry(
            id=bc.id,
            department={"id": bc.department.id, "name": bc.department.name},
            framework={
                "id": bc.framework.id,
                "key": bc.framework.key,
                "name": bc.framework.name,
                "display_component": bc.framework.display_component,
            },
            structured_output=bc.structured_output or {},
            relevance_verdict=bc.relevance_verdict,
            importance_score=(bc.structured_output or {}).get("importance"),
            confidence=(bc.structured_output or {}).get("confidence"),
            created_at=bc.created_at,
            model_used=bc.model_used,
        )
        for bc in business_cases_rows
    ]

    # Load harmonization (net view)
    harm_result = await session.execute(
        select(TopicHarmonization)
        .where(TopicHarmonization.topic_id == topic_id)
        .options(selectinload(TopicHarmonization.author))
    )
    harm = harm_result.scalar_one_or_none()

    net_view = None
    if harm is not None:
        authored_by = None
        if harm.author is not None:
            authored_by = {"id": harm.author.id, "username": harm.author.username}
        net_view = HarmonizationNetView(
            text=harm.net_view,
            authored_by=authored_by,
            authored_at=harm.authored_at,
            updated_at=harm.updated_at,
        )

    return HarmonizationResponse(
        topic={
            "id": topic.id,
            "title": topic.title,
            "description": topic.description,
            "first_seen_at": str(topic.first_seen_at),
            "last_seen_at": str(topic.last_seen_at),
        },
        business_cases=business_cases,
        net_view=net_view,
    )


@router.get(
    "/topics/{topic_id}/harmonization",
    response_model=HarmonizationResponse,
)
async def get_harmonization(
    topic_id: str,
    _current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HarmonizationResponse:
    """Cross-department harmonization view for a topic.

    Any authenticated user can read (cross-dept visibility by design).
    """
    return await _load_harmonization(topic_id, session)


@router.put(
    "/topics/{topic_id}/harmonization",
    response_model=HarmonizationResponse,
)
async def put_harmonization(
    topic_id: str,
    body: HarmonizationPutRequest,
    current_user: User = Depends(require_can_harmonize),
    session: AsyncSession = Depends(get_session),
) -> HarmonizationResponse:
    """Create or update the Net View annotation for a topic.

    Requires dept_lead (any department) or superadmin.
    Last-write-wins semantics (acceptable for v1).
    """

    # Verify topic exists
    topic_result = await session.execute(
        select(Topic).where(Topic.id == topic_id)
    )
    if topic_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Topic not found",
        )

    # Upsert harmonization
    harm_result = await session.execute(
        select(TopicHarmonization).where(TopicHarmonization.topic_id == topic_id)
    )
    harm = harm_result.scalar_one_or_none()

    if harm is None:
        harm = TopicHarmonization(
            topic_id=topic_id,
            net_view=body.net_view,
            authored_by=current_user.id,
        )
        session.add(harm)
    else:
        harm.net_view = body.net_view
        harm.authored_by = current_user.id
        # Manually bump updated_at (no DB trigger in v1)
        from datetime import datetime, timezone

        harm.updated_at = datetime.now(timezone.utc).isoformat()

    await session.commit()

    return await _load_harmonization(topic_id, session)


@router.delete(
    "/topics/{topic_id}/harmonization",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_harmonization(
    topic_id: str,
    _current_user: User = Depends(require_can_harmonize),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove the Net View annotation for a topic.

    Idempotent: returns 204 even if no harmonization existed.
    Requires dept_lead (any department) or superadmin.
    """

    await session.execute(
        delete(TopicHarmonization).where(TopicHarmonization.topic_id == topic_id)
    )
    await session.commit()
