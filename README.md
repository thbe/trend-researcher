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
