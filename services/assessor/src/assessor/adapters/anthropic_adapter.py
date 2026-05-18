"""Anthropic Claude adapter for the LLM port."""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

_log = structlog.get_logger(__name__)


class AnthropicAdapter:
    """Cloud LLM adapter using the Anthropic Messages API."""

    def __init__(self, api_key: str, default_model: str = "claude-sonnet-4-20250514") -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._base_url = "https://api.anthropic.com/v1"

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call Anthropic Messages API and return structured output."""
        model = model_id or self._default_model

        # Build request body
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": 1024,
            "messages": messages,
        }

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/messages",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        content_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block["text"]

        result: dict[str, Any] = {
            "content": content_text,
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
        }

        # Try to parse as JSON if response_schema was requested
        if response_schema and content_text:
            try:
                result["parsed"] = json.loads(content_text)
            except json.JSONDecodeError:
                _log.warning("anthropic.json_parse_failed", model=model)

        return result
