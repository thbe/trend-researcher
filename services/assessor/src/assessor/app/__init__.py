"""Assessor app — composition root and CLI."""

from assessor.app.composition import build_pipeline
from assessor.app.cli import app as cli_app

__all__ = ["build_pipeline", "cli_app"]
