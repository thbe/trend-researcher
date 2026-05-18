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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def get_settings() -> Settings:
    """Return a fresh :class:`Settings` instance.

    Uses a function (not a module-level singleton) so tests can monkey-patch
    environment variables between calls.
    """

    return Settings()


__all__ = ["Settings", "get_settings"]
