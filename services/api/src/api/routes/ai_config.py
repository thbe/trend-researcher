"""AI Configuration endpoints — per-department GET/PUT + model list (Phase 10).

Migration 0017 reshaped ``ai_config`` so each row is keyed on
``department_id`` (one row per dept). These routes use the
``X-Active-Department`` header (via :func:`get_active_department`) to pick
which row to read/write. ``GET`` returns 404 with a hint if the active
department has not yet been initialised — the SPA should then call ``PUT``
to create it.

Role matrix:
- ``GET /ai-config``         — viewer+ (any member of the active dept)
- ``GET /ai-config/models``  — viewer+ (read-only probe)
- ``PUT /ai-config``         — dept_lead+ (upserts the active dept's row)
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import (
    ActiveDepartment,
    get_active_department,
    get_session,
    require_role,
)
from api.schemas import AIConfigResponse, AIConfigUpdateRequest
from core.models import AIConfig

router = APIRouter(tags=["ai-config"])


@router.get(
    "/ai-config",
    response_model=AIConfigResponse,
    dependencies=[Depends(require_role("viewer", "analyst", "dept_lead"))],
)
async def get_ai_config(
    ad: ActiveDepartment = Depends(get_active_department),
    session: AsyncSession = Depends(get_session),
) -> AIConfigResponse:
    """Return the AI configuration for the active department."""
    result = await session.execute(
        select(AIConfig).where(AIConfig.department_id == ad.department.id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"AI config not initialised for department "
                f"{ad.department.slug!r}; create one via PUT /api/ai-config"
            ),
        )
    return AIConfigResponse.model_validate(row)


@router.put(
    "/ai-config",
    response_model=AIConfigResponse,
    dependencies=[Depends(require_role("dept_lead"))],
)
async def update_ai_config(
    body: AIConfigUpdateRequest,
    ad: ActiveDepartment = Depends(get_active_department),
    session: AsyncSession = Depends(get_session),
) -> AIConfigResponse:
    """Upsert the AI configuration for the active department.

    If a row already exists, it is updated in place. If not, a new row is
    inserted using the request body plus defaults from the ORM model for any
    field the caller omitted.
    """

    dept_id = ad.department.id
    existing = await session.get(AIConfig, dept_id)

    if existing is None:
        # Insert path — instantiate with whatever the caller provided; ORM
        # defaults cover anything they omit.
        row = AIConfig(department_id=dept_id)
        for field in (
            "provider",
            "base_url",
            "model",
            "api_token",
            "business_context",
            "opportunity_criteria",
            "risk_criteria",
            "thinking_effort",
            "request_timeout_seconds",
        ):
            val = getattr(body, field, None)
            if val is None:
                continue
            # Coerce empty strings to NULL on the nullable text columns.
            if field in {
                "api_token",
                "business_context",
                "opportunity_criteria",
                "risk_criteria",
            } and val == "":
                val = None
            setattr(row, field, val)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return AIConfigResponse.model_validate(row)

    # Update path
    touched = False
    if body.provider is not None:
        existing.provider = body.provider
        touched = True
    if body.base_url is not None:
        existing.base_url = body.base_url
        touched = True
    if body.model is not None:
        existing.model = body.model
        touched = True
    if body.api_token is not None:
        existing.api_token = body.api_token if body.api_token != "" else None
        touched = True
    if body.business_context is not None:
        existing.business_context = body.business_context if body.business_context != "" else None
        touched = True
    if body.opportunity_criteria is not None:
        existing.opportunity_criteria = body.opportunity_criteria if body.opportunity_criteria != "" else None
        touched = True
    if body.risk_criteria is not None:
        existing.risk_criteria = body.risk_criteria if body.risk_criteria != "" else None
        touched = True
    if body.thinking_effort is not None:
        existing.thinking_effort = body.thinking_effort
        touched = True
    if body.request_timeout_seconds is not None:
        existing.request_timeout_seconds = body.request_timeout_seconds
        touched = True

    if not touched:
        raise HTTPException(status_code=400, detail="No fields to update")

    existing.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(existing)
    return AIConfigResponse.model_validate(existing)


@router.get(
    "/ai-config/models",
    dependencies=[Depends(require_role("viewer", "analyst", "dept_lead"))],
)
async def list_available_models(
    ad: ActiveDepartment = Depends(get_active_department),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Query the LLM provider configured for the active department."""
    result = await session.execute(
        select(AIConfig).where(AIConfig.department_id == ad.department.id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"AI config not initialised for department "
                f"{ad.department.slug!r}; create one via PUT /api/ai-config"
            ),
        )

    base_url = row.base_url.rstrip("/")
    provider = row.provider
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if provider == "openai":
                # OpenAI-compatible: GET /v1/models — base_url already includes /v1.
                headers = {"Authorization": f"Bearer {row.api_token}"} if row.api_token else {}
                resp = await client.get(f"{base_url}/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()
                # OpenAI shape: {"data": [{"id": "...", ...}, ...]}
                items = data.get("data", []) if isinstance(data, dict) else []
                return [
                    {"name": m.get("id"), "size": None, "modified_at": None}
                    for m in items
                    if m.get("id")
                ]
            if provider == "anthropic":
                # Anthropic does not expose a public ``/models`` listing on
                # most plans — return an empty list so the UI lets users
                # type model names manually.
                return []
            # Default: ollama native /api/tags.
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models", [])
            return [
                {"name": m["name"], "size": m.get("size"), "modified_at": m.get("modified_at")}
                for m in models
            ]
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to LLM provider at {base_url}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch models: {exc}")
