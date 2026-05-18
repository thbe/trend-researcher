"""Assessor CLI — explicit invocation of the assessment pipeline.

The assessment is invoked explicitly (CLI or API endpoint), never as an
ingest hook — the Stage 1 / Stage 2 separation invariant remains intact (SC6).

Usage:
    # Assess all unassessed topics (up to 50):
    uv run --package assessor python -m assessor.app.cli assess

    # Assess a specific topic:
    uv run --package assessor python -m assessor.app.cli assess --topic-id <uuid>

    # Dry-run (show what would be assessed):
    uv run --package assessor python -m assessor.app.cli assess --dry-run
"""

from __future__ import annotations

import asyncio
import sys

import typer
import structlog

_log = structlog.get_logger(__name__)

app = typer.Typer(name="assessor", help="Stage 2 AI assessment pipeline")


@app.command()
def assess(
    topic_id: str | None = typer.Option(None, help="Assess a single topic by ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show topics without assessing"),
    limit: int = typer.Option(50, help="Max topics to assess in batch mode"),
) -> None:
    """Run the retail relevance assessment pipeline."""
    asyncio.run(_assess_async(topic_id=topic_id, dry_run=dry_run, limit=limit))


async def _assess_async(
    *,
    topic_id: str | None,
    dry_run: bool,
    limit: int,
) -> None:
    from assessor.app.composition import build_pipeline

    pipeline, engine = build_pipeline()
    try:
        if topic_id:
            topic_ids = [topic_id]
        else:
            topic_ids = await pipeline._rag.get_unassessed_topic_ids(limit=limit)

        if not topic_ids:
            print("No unassessed topics found.")
            return

        if dry_run:
            print(f"Would assess {len(topic_ids)} topic(s):")
            for tid in topic_ids:
                print(f"  - {tid}")
            return

        print(f"Assessing {len(topic_ids)} topic(s)...")
        results = await pipeline.assess_batch(topic_ids)

        relevant = sum(1 for r in results if r["relevance_verdict"] == "relevant")
        print(f"Done: {len(results)} assessed, {relevant} relevant, {len(results) - relevant} not-relevant")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    app()
