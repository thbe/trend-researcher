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

As of Phase 2, `crawler run-once` fans out across **3 sources** (1 JSON-Firebase + 2 RSS). Per-source failures are isolated — if an RSS feed times out or returns malformed XML, the run continues and the failed source name is recorded in the `failed_sources` column on the new `crawl_runs` row (and in the structlog `failed_sources` field).

| #   | `source_name`      | Type            | Endpoint                                                                  | Adapter                                                       |
| --- | ------------------ | --------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------- |
| 1   | `hackernews`       | JSON (Firebase) | `https://hacker-news.firebaseio.com/v0/topstories.json`                   | `services/crawler/src/crawler/adapters/sources/hackernews.py` |
| 2   | `nyt_homepage`     | RSS (XML)       | `https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml`               | `services/crawler/src/crawler/adapters/sources/rss.py`        |
| 3   | `google_news`      | RSS (XML)       | `https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en`                   | `services/crawler/src/crawler/adapters/sources/rss.py`        |

Reddit was planned but dropped — its Cloudflare WAF blocks datacenter-IP `httpx` requests regardless of User-Agent. The `RedditJsonSource` adapter is kept in `services/crawler/src/crawler/adapters/sources/reddit.py` but is not registered in `build_sources()`. See `.planning/phases/02-multi-source-ingest/CONTEXT.md` "Reddit access reality" for the full investigation.

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

As of Phase 3 a single `docker compose up -d` brings up **Postgres + api + scheduler**; the scheduler then triggers the crawler automatically every 12 hours (at 00:00 and 12:00 UTC). Manual one-off runs still work via `docker compose run --rm crawler`.

```bash
# 1. Copy env defaults (DATABASE_URL points at localhost; compose overrides for the container).
cp .env.example .env

# 2. Start Postgres (waits until healthy) and build all images.
docker compose up -d postgres
docker compose build crawler api scheduler

# 3. Apply the schema from the host (alembic uses host-side DATABASE_URL → localhost).
uv run --package core alembic -c packages/core/alembic.ini upgrade head

# 4. Bring up the api + scheduler. The crawler runs on its own cron tick from here on.
docker compose up -d api scheduler

# 5. (Optional) Trigger a one-off crawl without waiting for the next 12h tick.
docker compose run --rm crawler run-once --top-n 30
```

For the full live end-to-end smoke procedure, see `scripts/smoke_phase3.sh` (Phase 3) or `scripts/smoke_phase2.sh` (Phase 2, crawler-only).

### Operator endpoints

The api service exposes all endpoints under the `/api/*` prefix on `http://localhost:8000`:

- `GET /api/healthz` — liveness + DB-ping; returns `200 {"status":"ok","db":"reachable"}` when Postgres is reachable, `503 {"status":"degraded","db":"unreachable"}` otherwise.
- `GET /api/runs?limit=N` — last N rows from the `crawl_runs` operational telemetry table (one row per `crawler run-once` invocation), newest-first. `limit` defaults to 20 and is clamped to `[1, 100]`.
- `GET /api/topics?sort=&limit=N` — paginated topic list joined with derived `v_topic_stats` (`breadth` = distinct source count, `longevity_seconds` = `last_seen_at - first_seen_at` in seconds). `sort` whitelist `{breadth, longevity, last_seen_at}` with optional leading `-` for desc (default `-last_seen_at`); non-matches → `400`. `limit` defaults to 20, clamped to `[1, 100]`. Response shape: `{topics:[...], limit, sort}`. No nested `sources` or `topic_metadata` on list rows.
- `GET /api/topics/{id}` — per-topic detail with nested `sources[]` (one entry per `(source_name, observed_at)` observation, ordered by `observed_at DESC`) and the full `topic_metadata` JSONB blob. Returns `404` for unknown ids.

> **Phase 4 endpoint migration note:** in Phase 3 these routes lived at `/healthz` and `/runs`. Phase 4 re-prefixed all API routes under `/api/*` so the SPA catch-all (mounted at `/` in Phase 4 wave 5) doesn't swallow them. Update any operator scripts accordingly — bare `/healthz` and `/runs` now return `404`.

### Open the UI

The Vuetify SPA is built into the production api image and served at `/` by the same FastAPI process that owns `/api/*`. Once `docker compose up -d postgres api` is healthy, open:

**http://localhost:8000/**

You should see the Topics list (most-recently-observed first). Click any row for the per-topic detail view (sources, observation timeline, raw metadata). The SPA reads only from `/api/*` — same origin, no CORS, no client-side auth.

For frontend development with hot-reload (Vite on `:5173`, proxying `/api` → `:8000`), see [`web/README.md`](web/README.md).

### Container persistence

The production api image is **self-contained**: a single `ubuntu:24.04`-based container with `postgresql-16` embedded alongside the FastAPI app (single port `:8000`, single container). On startup it boots the embedded Postgres, runs Alembic migrations, restores from `${PERSIST_DIR}/trend_researcher.dump` if present (latest → previous → fresh-schema fallback), and launches uvicorn. A 30 s-debounced middleware fires `scripts/pg-dump-rotate.sh` after any successful write (POST/PUT/PATCH/DELETE 2xx/3xx) to capture the new state, and SIGTERM triggers a final dump before clean shutdown. The compose stack mounts a named volume `appdata` at `/app/data` so the dump survives container restarts; on Cloud Run the same path is backed by GCS-FUSE (Phase 4 wave 6).

To use an **external** Postgres instead (e.g. local compose development with `trend-postgres` separate), set `DATABASE_URL=postgresql+asyncpg://...` on the api container — the embedded boot path is skipped entirely.

Inspecting recent crawls:

```bash
# Quick sanity check
curl -fs localhost:8000/api/healthz

# Last 5 crawls — when they ran, what they inserted/updated, what failed
curl -s 'localhost:8000/api/runs?limit=5' \
  | jq '.runs[] | {started_at, totals_inserted, totals_updated, totals_errors, failed_sources}'

# Trending topics by breadth (which stories show up across the most sources)
curl -s 'localhost:8000/api/topics?sort=-breadth&limit=10' \
  | jq '.topics[] | {title, breadth, longevity_seconds, last_seen_at}'
```

The same data is also queryable directly:

```bash
docker compose exec postgres psql -U trend -d trend_researcher -c \
  "SELECT started_at, totals_inserted, totals_updated, totals_errors, failed_sources
   FROM crawl_runs ORDER BY started_at DESC LIMIT 5;"
```

### Cadence

The `scheduler` container runs a single 1-line cron in `services/scheduler/crontab`:

```
0 0,12 * * * cd /workspace && docker compose run --rm crawler run-once
```

Anchored at `00:00` and `12:00` UTC (not drift-tolerant — every tick is at the same wall-clock time regardless of how long the previous crawl took).

To change the cadence:

1. Edit `services/scheduler/crontab` to the new schedule.
2. Rebuild the scheduler image: `docker compose build scheduler`.
3. Restart the service: `docker compose up -d scheduler`.

`services/scheduler/README.md` covers the docker-socket trust-model note (the scheduler mounts the host docker socket so it can fire `docker compose run --rm crawler`; this is effectively root-on-host and is the reason this stack is single-operator-internal-tool only).

For end-to-end verification that the full Phase 3 stack works (`/api/healthz`, scheduler crontab loaded, 3 manual triggers writing 3 `crawl_runs` rows, `/api/runs` returning them), see `scripts/smoke_phase3.sh`.

## Quickstart — crawler only (Phase 2)

If you want to drive the crawler directly without the scheduler (e.g. for development on the ingest path), the Phase 2 walking-skeleton procedure still works:

```bash
# 1. Copy env defaults.
cp .env.example .env

# 2. Start Postgres and build the crawler image.
docker compose up -d postgres
docker compose build crawler

# 3. Apply the schema.
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
