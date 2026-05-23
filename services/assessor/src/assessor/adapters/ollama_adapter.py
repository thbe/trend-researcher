"""Ollama local LLM adapter for the LLM port."""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

_log = structlog.get_logger(__name__)


class OllamaAdapter:
    """Local LLM adapter using the Ollama HTTP API."""

    # Thinking effort → Ollama params mapping
    _THINKING_PARAMS: dict[str, dict[str, Any]] = {
        "off": {"think": False, "num_predict": 1024},
        "low": {"think": True, "num_predict": 2048},
        "medium": {"think": True, "num_predict": 4096},
        "high": {"think": True, "num_predict": 8192},
    }

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "llama3",
        thinking_effort: str = "off",
        request_timeout_seconds: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._thinking_effort = thinking_effort
        self._request_timeout_seconds = float(request_timeout_seconds)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call Ollama chat API and return structured output."""
        model = model_id or self._default_model
        params = self._THINKING_PARAMS.get(self._thinking_effort, self._THINKING_PARAMS["off"])

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": params["think"],
            "options": {
                "num_predict": params["num_predict"],
            },
        }

        # Ollama supports JSON mode via format field
        if response_schema:
            body["format"] = "json"

        async with httpx.AsyncClient(timeout=self._request_timeout_seconds) as client:
            try:
                resp = await client.post(
                    f"{self._base_url}/api/chat",
                    json=body,
                )
            except httpx.TimeoutException:
                raise RuntimeError(
                    f"Ollama timeout: model '{model}' did not respond within "
                    f"{self._request_timeout_seconds:.0f}s (configurable via "
                    f"ai_config.request_timeout_seconds)"
                )
            except httpx.ConnectError:
                raise RuntimeError(f"Cannot connect to Ollama at {self._base_url}")
            except httpx.RemoteProtocolError:
                raise RuntimeError(f"Ollama disconnected unexpectedly — model '{model}' may require too much memory")
            if resp.status_code != 200:
                # Try to extract a meaningful error message from Ollama
                try:
                    err_body = resp.json()
                    err_msg = err_body.get("error", resp.text)
                except Exception:
                    err_msg = resp.text
                _log.error("ollama.request_failed", status=resp.status_code, error=err_msg, model=model)
                raise RuntimeError(f"Ollama error ({resp.status_code}): {err_msg}")
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
