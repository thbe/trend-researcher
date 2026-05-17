"""One-shot, idempotent cleanup of Google-News-only topic descriptions.

Plan 04.5.1 / T02 (operator decision m0141 = strip Google News descriptions).

Why this exists
---------------
Plan 04.5-01 backfilled ``topics.description`` from ``raw_payload->>'summary'``
for every topic. Production smoke (post-v0.5.0) discovered that Google News
RSS ``<description>`` is structurally an ``<ol><li><a>`` related-articles HTML
fragment, NOT publisher prose. ~29 of the first 30 topics inspected had this
HTML-link-list content masquerading as a description.

Plan 04.5.1 T01 fixes the going-forward behaviour by passing
``capture_summary=False`` to the Google News RssSource so RawItem.description
is forced to None. But the EXISTING dirty rows already in production
``topics.description`` need to be cleared.

Predicate
---------
NULL ``topics.description`` if and only if EVERY observed source for that
topic is ``google_news``. Cross-source topics (e.g. observed by both NYT and
Google News, where the first-non-empty merge already preserved NYT's prose)
keep their description.

Idempotency
-----------
``WHERE t.description IS NOT NULL`` guard. Re-running is a no-op.

Usage
-----
    # local docker compose:
    uv run python scripts/clear_google_news_descriptions.py --dry-run
    uv run python scripts/clear_google_news_descriptions.py

    # against prod:
    DATABASE_URL="postgresql+asyncpg://..." \\
      uv run python scripts/clear_google_news_descriptions.py --dry-run

Exit codes: 0 success, non-zero on connection / SQL failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from sqlalchemy import text

from core import get_engine, get_sessionmaker, get_settings

_log = structlog.get_logger(__name__)


# Topics whose every observed source is 'google_news' AND that still carry a
# (Google-News-shaped) description. NOT EXISTS pattern ensures we exclude any
# topic that was also observed by NYT/HN/etc.
_DRY_RUN_SQL = text("""
    SELECT COUNT(*) AS would_null
    FROM topics t
    WHERE t.description IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM topic_sources ts
        WHERE ts.topic_id = t.id AND ts.source_name = 'google_news'
      )
      AND NOT EXISTS (
        SELECT 1 FROM topic_sources ts
        WHERE ts.topic_id = t.id AND ts.source_name <> 'google_news'
      )
""")

_UPDATE_SQL = text("""
    UPDATE topics t
    SET description = NULL
    WHERE t.description IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM topic_sources ts
        WHERE ts.topic_id = t.id AND ts.source_name = 'google_news'
      )
      AND NOT EXISTS (
        SELECT 1 FROM topic_sources ts
        WHERE ts.topic_id = t.id AND ts.source_name <> 'google_news'
      )
""")


async def main(*, dry_run: bool) -> int:
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        async with session_factory() as session:
            if dry_run:
                count = int(
                    (await session.execute(_DRY_RUN_SQL)).scalar_one()
                )
            else:
                result = await session.execute(_UPDATE_SQL)
                count = result.rowcount or 0
                await session.commit()
    finally:
        await engine.dispose()

    verb = "would NULL" if dry_run else "NULLed"
    print(f"{verb} {count} google-news-only topic descriptions")
    _log.info(
        "scripts.clear_google_news_descriptions.done",
        dry_run=dry_run,
        rows=count,
    )
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="clear_google_news_descriptions",
        description="One-shot idempotent NULL of Google-News-only topic "
        "descriptions (Plan 04.5.1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned UPDATE count without writing.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run)))
