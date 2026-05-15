"""Shared core package: domain types, ORM models, settings, and DB plumbing.

This package owns the v1 Postgres schema for every service in the
Trend Researcher workspace.
"""

from core.config import Settings, get_settings
from core.db import get_engine, get_sessionmaker
from core.models import Base, CrawlRun, Topic, TopicSource

__version__ = "0.1.0"

__all__ = [
    "Base",
    "CrawlRun",
    "Settings",
    "Topic",
    "TopicSource",
    "__version__",
    "get_engine",
    "get_sessionmaker",
    "get_settings",
]
