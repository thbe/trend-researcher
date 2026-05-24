"""Application settings for ``packages/core``.

Loaded from environment variables (and optionally a ``.env`` file at the
process working directory). Only one required setting in v1: the async
SQLAlchemy database URL.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration sourced from environment / .env."""

    database_url: str

    # Auth: seed user credentials (upserted on app startup)
    auth_seed_username: str = "admin"
    auth_seed_password: str = "0nly4%Testing"

    # Auth: session cookie signing key (random default for dev; override in prod)
    auth_secret_key: str = "dev-secret-change-in-production"
    auth_session_ttl_hours: int = 24

    # AI Assessment (Phase 6)
    # Default backend is the bundled Ollama container (`http://ollama:11434`),
    # which works on every host the Compose stack runs on. macOS operators
    # typically override these via the `ai_config` DB row to point at oMLX
    # (https://omlx.ai/), a much faster macOS-native OpenAI-compatible server
    # at http://127.0.0.1:8000/v1. Provider is auto-detected from `base_url`
    # in routes/assessment.py (`/v1` → OpenAI-compatible, `anthropic` → Claude,
    # otherwise Ollama).
    llm_provider: str = "ollama"  # "ollama" | "openai" (oMLX / LM Studio / vLLM) | "anthropic"
    llm_model: str = "qwen3.5:latest"
    llm_api_key: str = ""  # required for anthropic / hosted OpenAI; unused for local Ollama / oMLX
    llm_base_url: str = "http://ollama:11434"  # bundled Ollama service name on the Compose network
    assessment_prompt_version: str = "v1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def get_settings() -> Settings:
    """Return a fresh :class:`Settings` instance.

    Uses a function (not a module-level singleton) so tests can monkey-patch
    environment variables between calls.
    """

    return Settings()


__all__ = ["Settings", "get_settings"]
