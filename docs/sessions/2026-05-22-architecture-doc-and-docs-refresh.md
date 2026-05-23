# Session: 2026-05-22 — Architecture Doc + Top-Level Docs Refresh

## Summary

Created a brand-new `docs/ARCHITECTURE.md` capturing the as-built system and
refreshed the three existing top-level docs (`README.md`, `docs/API.md`,
`docs/DEPLOYMENT.md`) to remove drift accumulated through Phase 4+
(Stage 2 assessment, opportunity/risk criteria, configurable Ollama
timeout, Ollama in local compose but not in prod).

No code was touched — docs-only commit, no container rebuild required.

## Earlier in the same working day (context)

Three small code commits had landed before the docs work and are referenced
by the new documentation:

- `a983767` — feat(ai-config): make Ollama request timeout configurable per
  deployment. Adds migration `0015`, `AIConfig.request_timeout_seconds`
  (default 120, range 10–3600), wires it through `OllamaAdapter`,
  schema, route, and the AI-config Vuetify form.
- `207d119` — fix(web): preserve topic list state across back-navigation by
  serialising `page`, `ipp`, `sort` into the URL query string.
- `1a8ed0f` — fix(web): use `v-model` bindings on the topic list table for
  proper two-way state sync.

## Changes (this session)

### New: `docs/ARCHITECTURE.md`
Full as-built architecture document (~280 lines), structured as:

1. Goals & Constraints (locked stack, AI boundary, dedup boundary,
   operational footprint).
2. Logical Layers — ASCII diagram SPA → API → Stage 1 / Stage 2 → Postgres.
3. Component Map — per-directory walkthrough:
   - `packages/core` — 9 ORM models, Alembic.
   - `services/crawler` — hex layout (adapters/ports/domain/app).
   - `services/assessor` — hex layout; LLM adapter selection
     pseudo-code from `api/routes/assessment.py::_build_pipeline`.
   - `services/api` — routers, middleware, SPA static mount.
   - `web/` — Vue 3 + Vuetify SPA, Pinia, Vue Router.
4. Data Flow — ingest sequence diagram + assessment sequence diagram
   + per-request boundaries table.
5. Deployment Topologies — local compose (4 containers incl. ollama)
   vs. prod Cloud Run + embedded PG + GCS-FUSE.
6. Trust Boundaries & Auth — table of cookie/PAT/none.
7. Schema Evolution — Alembic conventions; `0014` / `0015` as canonical
   extension examples.
8. Extensibility Points — "you want to… / touch this" table.
9. Non-Goals — deliberately excluded scope.
10. References — cross-links to other docs and `.planning/`.

### Updated: `README.md`
- "Stage 2 — Assessment (AI, not yet implemented)" → reframed as
  implemented with pluggable Ollama / OpenAI / Anthropic adapters.
- Project structure: `alembic/` 7 → 15 migration versions; assessor
  marked as implemented hex layout; ollama added to compose summary.
- API endpoints table expanded from 9 → 20 routes (topics detail, crawl,
  assess, assess/{id}, assess/jobs, jobs/{id}, business-cases,
  ai-config GET/PUT/models, dashboard).
- New "AI Configuration" subsection covering `business_context`,
  `opportunity_criteria`, `risk_criteria`, `thinking_effort`,
  `request_timeout_seconds`, and adapter auto-routing by `base_url`.
- Cross-link block to ARCHITECTURE.md / API.md / DEPLOYMENT.md.
- Note that prod does **not** bundle Ollama.

### Updated: `docs/API.md`
- `GET /api/ai-config` response: added `opportunity_criteria`,
  `risk_criteria`, `request_timeout_seconds`; added adapter-selection
  note (anthropic / openai / ollama by `base_url` heuristic).
- `PUT /api/ai-config` body: same three fields; validation
  (`10 <= request_timeout_seconds <= 3600`); clarified that the timeout
  only affects the Ollama adapter.

### Updated: `docs/DEPLOYMENT.md`
- Cross-link to ARCHITECTURE.md from overview.
- New "LLM Provider (configured in DB, not env)" subsection with the
  base_url → adapter mapping table; clarifies Ollama is local-only;
  API-key rotation is a `PUT /api/ai-config` call (no redeploy).

## Files Modified
- `docs/ARCHITECTURE.md` — **new**, full document
- `README.md` — Stage 2 description, endpoint table, project structure,
  AI config section, doc cross-links
- `docs/API.md` — AIConfig GET + PUT sections
- `docs/DEPLOYMENT.md` — overview cross-link + LLM provider subsection

## Commit
- `c5987bc` — `docs: add ARCHITECTURE.md and refresh README/API/DEPLOYMENT to reflect current state` — pushed to `main`

## Verification
- `git status` clean; local `main` and `origin/main` both at `c5987bc`.
- No code change → no container rebuild performed.
- Pre-existing LSP false positives (sqlalchemy / core.models /
  assessor.adapters unresolved on host) ignored per project convention.

## Notes for Future Sessions
- Source of truth for AIConfig fields is
  `services/api/src/api/schemas.py::AIConfigResponse` /
  `AIConfigUpdateRequest`.
- LLM adapter selection logic lives in
  `services/api/src/api/routes/assessment.py::_build_pipeline`
  (lines 29-75) — keep ARCHITECTURE.md §3 in sync if it changes.
- Compose stack now has 4 services: `postgres`, `crawler` (one-shot,
  no restart), `api` (4000→8000), `ollama` (11434, healthchecked).
  Volumes: `postgres_data`, `appdata`, `ollama_data`.
- Next likely doc drift triggers: new LLM provider adapter, new
  endpoint, new AIConfig field, schema migration that adds a
  user-visible model.
