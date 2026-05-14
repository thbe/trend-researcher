"""Structured logging configuration for the crawler service.

Containers default to JSON output (one event per line, easy to ship to any log
collector). Local developers can flip to a coloured console renderer with
``LOG_FORMAT=text``.
"""

from __future__ import annotations

import logging
import os

import structlog


def configure_logging(level: str = "INFO", json_output: bool | None = None) -> None:
    """Configure structlog for the running process.

    Parameters
    ----------
    level:
        Standard logging level name (``DEBUG``/``INFO``/``WARNING``/``ERROR``).
    json_output:
        If ``True`` use ``JSONRenderer``; if ``False`` use ``ConsoleRenderer``.
        When ``None`` (the default), falls back to the ``LOG_FORMAT`` env var:
        ``LOG_FORMAT=text`` selects the console renderer, anything else
        (including unset) selects JSON.
    """

    if json_output is None:
        json_output = os.getenv("LOG_FORMAT", "json").lower() != "text"

    renderer: structlog.types.Processor
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


__all__ = ["configure_logging"]
