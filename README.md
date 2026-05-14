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

## Quickstart

End-to-end Phase 1 walking skeleton: bring up Postgres, apply the schema, run one HackerNews crawl, and inspect the topics table.

```bash
# 1. Copy env defaults (DATABASE_URL points at localhost; compose overrides for the container).
cp .env.example .env

# 2. Start Postgres (waits until healthy) and build the crawler image.
docker compose up -d postgres
docker compose build crawler

# 3. Apply the schema from the host (alembic uses host-side DATABASE_URL → localhost).
uv run --package core alembic -c packages/core/alembic.ini upgrade head

# 4. Run a one-shot crawl. Use --top-n 30 for a quick smoke; production default is 100.
docker compose run --rm crawler run-once --top-n 30

# 5. Inspect.
docker compose exec postgres psql -U trend -d trend_researcher -c \
  "SELECT count(*) AS topics FROM topics;"
docker compose exec postgres psql -U trend -d trend_researcher -c \
  "SELECT count(*) AS sources FROM topic_sources;"
```

Re-running step 4 should leave the topic count roughly stable (≤ ~5 new) and bump `topic_sources.observation_count` for already-seen items — that is the dedup invariant.
