"""AI Configuration endpoints — GET/PUT singleton settings + model list."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_session
from api.schemas import AIConfigResponse, AIConfigUpdateRequest
from core.models import AIConfig

router = APIRouter(tags=["ai-config"])


@router.get("/ai-config", response_model=AIConfigResponse)
async def get_ai_config(
    session: AsyncSession = Depends(get_session),
) -> AIConfigResponse:
    """Return the current AI configuration."""
    result = await session.execute(select(AIConfig).where(AIConfig.key == "default"))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="AI config not initialized")
    return AIConfigResponse.model_validate(row)


@router.put("/ai-config", response_model=AIConfigResponse)
async def update_ai_config(
    body: AIConfigUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> AIConfigResponse:
    """Update the AI configuration."""
    values: dict = {"updated_at": datetime.now(timezone.utc)}
    if body.base_url is not None:
        values["base_url"] = body.base_url
    if body.model is not None:
        values["model"] = body.model
    if body.api_token is not None:
        values["api_token"] = body.api_token if body.api_token != "" else None
    if body.business_context is not None:
        values["business_context"] = body.business_context if body.business_context != "" else None
    if body.opportunity_criteria is not None:
        values["opportunity_criteria"] = body.opportunity_criteria if body.opportunity_criteria != "" else None
    if body.risk_criteria is not None:
        values["risk_criteria"] = body.risk_criteria if body.risk_criteria != "" else None
    if body.thinking_effort is not None:
        values["thinking_effort"] = body.thinking_effort

    if len(values) == 1:
        raise HTTPException(status_code=400, detail="No fields to update")

    stmt = (
        update(AIConfig)
        .where(AIConfig.key == "default")
        .values(**values)
        .returning(AIConfig)
    )
    result = (await session.execute(stmt)).first()
    if result is None:
        raise HTTPException(status_code=404, detail="AI config not initialized")
    await session.commit()
    return AIConfigResponse.model_validate(result[0])


@router.get("/ai-config/models")
async def list_available_models(
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Query the configured LLM provider for available models."""
    # Read current config to get the base_url
    result = await session.execute(select(AIConfig).where(AIConfig.key == "default"))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="AI config not initialized")

    base_url = row.base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
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
