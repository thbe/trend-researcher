"""LLM port — protocol for language model adapters."""

from __future__ import annotations

from typing import Any, Protocol


class LLMPort(Protocol):
    """Adapter contract for language model calls.

    Implementations: AnthropicAdapter, OllamaAdapter.
    Switching providers requires only env-var changes (LLM_PROVIDER, LLM_MODEL).
    """

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model_id: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send messages to the LLM and return structured output.

        Parameters
        ----------
        messages : list of {"role": ..., "content": ...} dicts
        model_id : override the configured model (optional)
        response_schema : JSON schema hint for structured output (optional)

        Returns
        -------
        dict with at least "content" key (raw text) and optionally "parsed"
        (structured output if response_schema was provided).
        """
        ...
