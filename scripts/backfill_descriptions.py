"""One-shot, idempotent backfill of topics.description + topic_sources.resolved_url.

Plan 04.5-01 / T05 (locked D-Q2 = A "explicit one-shot script").

Why this exists
---------------
Before Plan 04.5-01, the crawler discarded every RSS ``<description>`` /
``<summary>`` it fetched (the bytes landed in ``topic_sources.raw_payload->>
'summary'`` but never reached ``topics.description``). All 167 production
topic rows therefore had ``description IS NULL`` at the moment T01–T04
shipped, even though the source data was already on disk.

Similarly, every existing ``topic_sources`` row for ``source_name =
'google_news'`` had a CBM redirect token in ``url`` and no
``resolved_url`` (the column did not exist until migration 0004).

Rather than wait for the next 12h crawl to re-populate description
(which would only catch topics observed AGAIN — leaving "one-shot" trends
NULL forever), this script does a single explicit pass:

* **Pass 1** — for every topic with ``description IS NULL``, copy the
  earliest non-empty ``raw_payload->>'summary'`` from its observations
  into ``topics.description``.
* **Pass 2** — for every ``google_news`` row with ``resolved_url IS NULL``
  whose ``url`` looks like a CBM token, run the in-process decoder and
  write the result.

Idempotency
-----------
Both passes have ``WHERE … IS NULL`` guards. Run the script ten times in a
row — the 2nd through 10th are no-ops by design. This is the
documented safety net for "operator panics and re-runs."

Invocation
----------
Local (docker-compose):
    docker compose exec api uv run --directory services/crawler \\
        python -m scripts.backfill_descriptions

Cloud Run (one-shot job; requires the script + its imports be present in
the deployed image — they are, via the api service's PYTHONPATH):
    gcloud run jobs create trend-backfill-04-5-01 \\
        --image=<latest image> --command=python \\
        --args=-m,scripts.backfill_descriptions
    gcloud run jobs execute trend-backfill-04-5-01 --region=europe-west2

Flags
-----
``--dry-run``: prints the planned UPDATE counts without writing anything.
Useful for the verify gate and for operator pre-flight on prod.

Exit codes: 0 on success or no-op; 1 on any uncaught DB exception.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from sqlalchemy import text

from core import get_engine, get_sessionmaker, get_settings

from crawler.adapters.sources.google_news_url import decode_google_news_url


_log = structlog.get_logger("scripts.backfill_descriptions")


# Pass 1: pick the EARLIEST non-empty summary per topic_id, write it to
# topics.description, but only where the topic currently has NULL. The
# DISTINCT ON + ORDER BY trick keeps Postgres-native and avoids a Python
# round-trip per topic.
_PASS1_SQL = text("""
    UPDATE topics t
    SET description = sub.summary,
        updated_at = now()
    FROM (
      SELECT DISTINCT ON (ts.topic_id)
             ts.topic_id,
             ts.raw_payload->>'summary' AS summary
      FROM topic_sources ts
      WHERE ts.raw_payload->>'summary' IS NOT NULL
        AND length(trim(ts.raw_payload->>'summary')) > 0
      ORDER BY ts.topic_id, ts.observed_at ASC
    ) sub
    WHERE t.id = sub.topic_id
      AND t.description IS NULL
""")

# Pass 1 dry-run: same predicate, count only.
_PASS1_DRY_RUN_SQL = text("""
    SELECT COUNT(*) AS would_update
    FROM topics t
    WHERE t.description IS NULL
      AND EXISTS (
        SELECT 1 FROM topic_sources ts
        WHERE ts.topic_id = t.id
          AND ts.raw_payload->>'summary' IS NOT NULL
          AND length(trim(ts.raw_payload->>'summary')) > 0
      )
""")

# Pass 2: select google_news rows that still need a resolved_url.
_PASS2_SELECT_SQL = text("""
    SELECT id, url
    FROM topic_sources
    WHERE source_name = 'google_news'
      AND resolved_url IS NULL
      AND url LIKE 'https://news.google.com/rss/articles/CBM%'
""")

_PASS2_UPDATE_SQL = text(
    "UPDATE topic_sources SET resolved_url = :decoded WHERE id = :row_id"
)


async def _run_pass1(session, *, dry_run: bool) -> int:
    if dry_run:
        result = await session.execute(_PASS1_DRY_RUN_SQL)
        return int(result.scalar_one())
    result = await session.execute(_PASS1_SQL)
    return result.rowcount or 0


async def _run_pass2(session, *, dry_run: bool) -> tuple[int, int]:
    """Returns (updated, decoder_failures)."""
    rows = (await session.execute(_PASS2_SELECT_SQL)).all()
    if dry_run:
        # In dry-run we still invoke the decoder so the operator sees the
        # real decode-success rate before committing. No writes.
        would_update = 0
        decoder_failures = 0
        for row in rows:
            if decode_google_news_url(row.url) is not None:
                would_update += 1
            else:
                decoder_failures += 1
        return would_update, decoder_failures

    updated = 0
    decoder_failures = 0
    for row in rows:
        decoded = decode_google_news_url(row.url)
        if decoded is None:
            decoder_failures += 1
            continue
        await session.execute(
            _PASS2_UPDATE_SQL, {"decoded": decoded, "row_id": row.id}
        )
        updated += 1
    return updated, decoder_failures


async def main(*, dry_run: bool) -> int:
    settings = get_settings()
    engine = get_engine(settings.database_url)
    session_factory = get_sessionmaker(engine)
    try:
        async with session_factory() as session:
            pass1_count = await _run_pass1(session, dry_run=dry_run)
            pass2_updated, pass2_failed = await _run_pass2(session, dry_run=dry_run)
            if not dry_run:
                await session.commit()
    finally:
        await engine.dispose()

    verb = "would backfill" if dry_run else "backfilled"
    print(
        f"{verb} descriptions: {pass1_count}, "
        f"{verb} resolved_urls: {pass2_updated}, "
        f"decoder failures (skipped): {pass2_failed}"
    )
    _log.info(
        "scripts.backfill_descriptions.done",
        dry_run=dry_run,
        descriptions=pass1_count,
        resolved_urls=pass2_updated,
        decoder_failures=pass2_failed,
    )
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="backfill_descriptions",
        description="One-shot idempotent backfill for topics.description "
        "+ topic_sources.resolved_url (Plan 04.5-01).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned UPDATE counts without writing to the database.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    try:
        sys.exit(asyncio.run(main(dry_run=args.dry_run)))
    except Exception as exc:  # pragma: no cover - operator-visible failure path
        _log.exception("scripts.backfill_descriptions.failed", error=str(exc))
        sys.exit(1)
