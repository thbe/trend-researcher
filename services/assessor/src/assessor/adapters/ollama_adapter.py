"""Ollama local LLM adapter for the LLM port."""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

_log = structlog.get_logger(__name__)


class OllamaAdapter:
    """Local LLM adapter using the Ollama HTTP API."""

    def __init__(self, base_url: str = "http://localhost:11434", default_model: str = "llama3") -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call Ollama chat API and return structured output."""
        model = model_id or self._default_model

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }

        # Ollama supports JSON mode via format field
        if response_schema:
            body["format"] = "json"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/chat",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        content_text = data.get("message", {}).get("content", "")

        result: dict[str, Any] = {
            "content": content_text,
            "model": data.get("model", model),
            "usage": {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
        }

        if response_schema and content_text:
            try:
                result["parsed"] = json.loads(content_text)
            except json.JSONDecodeError:
                _log.warning("ollama.json_parse_failed", model=model)

        return result
