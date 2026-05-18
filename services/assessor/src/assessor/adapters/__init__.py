"""LLM adapters — Anthropic (cloud) and Ollama (local)."""

from assessor.adapters.anthropic_adapter import AnthropicAdapter
from assessor.adapters.ollama_adapter import OllamaAdapter

__all__ = ["AnthropicAdapter", "OllamaAdapter"]
