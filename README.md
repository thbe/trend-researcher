# Trend Researcher

A two-stage internal tool that continuously crawls major news, social, and tech sites to surface trending/viral topics, then uses AI to evaluate which of those topics matter for a specific market (starting with retail) and drafts a rough business case for the ones that do.

## Layout

This repo is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with four members:

- **`services/crawler/`** — Python ingest service (Stage 1). Deterministic, zero AI. Pulls top-N items per source, fuzzy-deduplicates, writes to Postgres.
- **`services/api/`** — TypeScript-facing API service. Reads topics + business cases from Postgres. _Scaffold only in Phase 1; implemented in Phase 4._
- **`services/assessor/`** — Python AI service (Stage 2). RAG over the topic store; produces market-relevance verdicts and business cases. _Scaffold only in Phase 1; implemented in Phase 6._
- **`packages/core/`** — Shared domain types, SQLAlchemy models, and the single Alembic migration tree owned by all services.
- **`web/`** — TypeScript + Vuetify frontend. _Scaffold only in Phase 1; implemented in Phase 4._

See `.planning/PROJECT.md` for the full scope, constraints, and decision log; `.planning/ROADMAP.md` for the 9-phase plan.

## Sources

As of Phase 2, `crawler run-once` fans out across **7 sources** (1 JSON-Firebase + 4 Reddit JSON + 2 RSS). Per-source failures are isolated — if Reddit returns 429 or an RSS feed times out, the run continues and the failed source name is recorded in the `failed_sources` log field.

| #   | `source_name`      | Type            | Endpoint                                                                  | Adapter                                                       |
| --- | ------------------ | --------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------- |
| 1   | `hackernews`       | JSON (Firebase) | `https://hacker-news.firebaseio.com/v0/topstories.json`                   | `services/crawler/src/crawler/adapters/sources/hackernews.py` |
| 2   | `reddit_all`       | JSON (Reddit)   | `https://www.reddit.com/r/all/hot.json`                                   | `services/crawler/src/crawler/adapters/sources/reddit.py`     |
| 3   | `reddit_business`  | JSON (Reddit)   | `https://www.reddit.com/r/business/hot.json`                              | `services/crawler/src/crawler/adapters/sources/reddit.py`     |
| 4   | `reddit_retail`    | JSON (Reddit)   | `https://www.reddit.com/r/retail/hot.json`                                | `services/crawler/src/crawler/adapters/sources/reddit.py`     |
| 5   | `reddit_bifl`      | JSON (Reddit)   | `https://www.reddit.com/r/BuyItForLife/hot.json`                          | `services/crawler/src/crawler/adapters/sources/reddit.py`     |
| 6   | `nyt_homepage`     | RSS (XML)       | `https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml`               | `services/crawler/src/crawler/adapters/sources/rss.py`        |
| 7   | `google_news`      | RSS (XML)       | `https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en`                   | `services/crawler/src/crawler/adapters/sources/rss.py`        |

Cross-source dedup is automatic: the same headline appearing on, say, NYT and Google News collapses to **one** row in `topics` with **two** rows in `topic_sources` (different `source_name`, possibly different `url`). See `services/crawler/tests/test_cross_source_dedup.py` for the proof.

### Disabling a source at runtime

Set `CRAWLER_DISABLED_SOURCES` in `.env` (or in the `crawler` service `environment:` block in `docker-compose.yml`) to skip one or more sources on the next crawl tick. Format is a comma-separated list of source names. The change takes effect on the next container start — no rebuild, no migration.

```bash
# .env
CRAWLER_DISABLED_SOURCES=hackernews,google_news
```

Valid source names (v1): `hackernews`, `nyt_homepage`, `google_news`.

Behavior:

- **Case-insensitive**: `HackerNews`, `hackernews`, and `HACKERNEWS` all match the same source.
- **Whitespace-tolerant**: `  hackernews ,  google_news  ` is parsed cleanly.
- **Unknown names are warnings, not errors**: an unknown name (e.g. a typo, or `reddit` which is not currently registered) logs a `crawler.disabled_sources.unknown` warning on startup and the run proceeds with the rest of the filter applied. This keeps operator typos visible without breaking the unattended 12h cadence. Phase 5's UI-driven `crawl_config` will close this gap with validated names.
- **All sources disabled is allowed**: setting `CRAWLER_DISABLED_SOURCES` to every known name returns an empty source list and the orchestrator still completes, writing a zero-totals row to `crawl_runs`. Useful for parking the crawler without tearing the stack down.
- **Empty or unset value**: no filter is applied — all registered sources run.

The active filter is logged at INFO as `crawler.disabled_sources.applied` (with the sorted disabled set) on every container start, so `docker logs crawler` shows what was skipped.

## Quickstart

End-to-end Phase 2 walking skeleton: bring up Postgres, apply the schema, run one multi-source crawl across all 7 sources, and inspect the topics table per source.

```bash
# 1. Copy env defaults (DATABASE_URL points at localhost; compose overrides for the container).
cp .env.example .env

# 2. Start Postgres (waits until healthy) and build the crawler image.
docker compose up -d postgres
docker compose build crawler

# 3. Apply the schema from the host (alembic uses host-side DATABASE_URL → localhost).
uv run --package core alembic -c packages/core/alembic.ini upgrade head

# 4. Run a one-shot multi-source crawl. Use --top-n 30 for a quick smoke; production default is 100.
docker compose run --rm crawler run-once --top-n 30

# 5. Inspect — per-source counts, total topics, and cross-source dedup spot check.
docker compose exec postgres psql -U trend -d trend_researcher -c \
  "SELECT source_name, count(*) FROM topic_sources GROUP BY source_name ORDER BY 2 DESC;"

docker compose exec postgres psql -U trend -d trend_researcher -c \
  "SELECT count(*) AS total_topics,
          sum(CASE WHEN observation_count >= 2 THEN 1 ELSE 0 END) AS multi_observation
   FROM topics;"

docker compose exec postgres psql -U trend -d trend_researcher -c \
  "SELECT t.title, count(DISTINCT ts.source_name) AS source_count
   FROM topics t JOIN topic_sources ts ON ts.topic_id = t.id
   GROUP BY t.id, t.title HAVING count(DISTINCT ts.source_name) >= 2
   ORDER BY source_count DESC LIMIT 10;"
```

Re-running step 4 should leave the topic count roughly stable (most stories repeat) and bump `topics.observation_count` for already-seen items — that is the dedup invariant. Each successful re-observation also adds a new row to `topic_sources` (one row per `(topic, source, observed_at)`).

For the full live multi-source smoke procedure, see `scripts/smoke_phase2.sh`.
