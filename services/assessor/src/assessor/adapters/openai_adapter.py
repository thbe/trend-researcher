"""OpenAI-compatible adapter for the LLM port.

Works with any server exposing the OpenAI Chat Completions API:
- LM Studio (default http://localhost:1234/v1)
- vLLM
- llama.cpp server
- OpenAI itself
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

_log = structlog.get_logger(__name__)


class OpenAIAdapter:
    """LLM adapter using the OpenAI Chat Completions API."""

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "lm-studio",
        default_model: str = "local-model",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call OpenAI-compatible chat/completions endpoint."""
        model = model_id or self._default_model

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.3,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        content_text = data["choices"][0]["message"]["content"]

        result: dict[str, Any] = {
            "content": content_text,
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
        }

        # Try to parse as JSON if response_schema was requested
        if response_schema and content_text:
            # Strip markdown code fences that local models often wrap around JSON
            text_to_parse = content_text.strip()
            if text_to_parse.startswith("```"):
                # Remove opening fence (```json or ```)
                text_to_parse = text_to_parse.split("\n", 1)[-1] if "\n" in text_to_parse else ""
            if text_to_parse.endswith("```"):
                text_to_parse = text_to_parse[:-3].rstrip()
            try:
                result["parsed"] = json.loads(text_to_parse)
            except json.JSONDecodeError:
                _log.warning("openai_compat.json_parse_failed", model=model)

        return result
