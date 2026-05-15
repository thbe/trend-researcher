"""Typer CLI for the crawler service.

Single command: ``crawler run-once`` — performs one full crawl across all
configured sources and exits. The crawler is a stateless one-shot job by
design (no in-process scheduler).
"""

from __future__ import annotations

import asyncio
import os

import typer

from crawler.app.composition import build_repository, build_sources
from crawler.app.logging import configure_logging
from crawler.app.orchestrator import run_once as run_once_async

app = typer.Typer(help="Trend Researcher crawler — one-shot job runner.")


@app.command("version")
def version_cmd() -> None:
    """Print the crawler package version."""
    from crawler import __version__

    typer.echo(__version__)


@app.command("run-once")
def run_once_cmd(
    top_n: int = typer.Option(
        None,
        "--top-n",
        "-n",
        help="Items per source. Defaults to CRAWLER_TOP_N env var or 100.",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="Log level: DEBUG / INFO / WARNING / ERROR.",
    ),
) -> None:
    """Run a single crawl across all configured sources, then exit."""
    configure_logging(level=log_level)
    effective_top_n = (
        top_n if top_n is not None else int(os.getenv("CRAWLER_TOP_N", "100"))
    )

    async def _main() -> dict:
        # Build inside the loop so the engine's pool binds to *this* loop,
        # then dispose inside it too — avoids "Event loop is closed" /
        # "attached to a different loop" tracebacks at shutdown.
        sources = build_sources()
        topic_repo, _crawl_run_repo, engine = build_repository()
        # _crawl_run_repo is unpacked here (T05) and threaded into the
        # orchestrator in task T06, which extends run_once_async to accept it.
        try:
            return await run_once_async(sources, topic_repo, effective_top_n)
        finally:
            await engine.dispose()

    stats = asyncio.run(_main())
    typer.echo(f"crawl complete: {stats['totals']}")


if __name__ == "__main__":
    app()
