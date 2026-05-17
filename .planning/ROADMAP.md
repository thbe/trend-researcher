# Roadmap: Trend Researcher

## Overview

Trend Researcher is built as a **Vertical MVP**: each phase ships a thin, runnable end-to-end slice rather than a complete horizontal layer. Phase 1 lands the repo skeleton, Postgres, the topic schema, and a single working crawler — enough to see real topics in the database after one run. Subsequent phases broaden the source set, add scheduling and ops, surface the data through a Vuetify UI, layer the AI assessment pipeline on top, and finally harden the PoC for the 1–2 month observation period that decides whether the idea is worth productizing.

The hard architectural rule throughout: **Stage 1 ingest stays AI-free and deterministic; AI lives only in Stage 2 assessment.** Every phase is built with externalization-ready seams so the same code can later be lifted into a multi-tenant product without a rewrite.

**Architectural shape (locked at Phase 1):**
- **Monorepo, multi-service.** Three small Python services (`crawler`, `api`, `assessor`) + one shared package (`packages/core`) + one Vuetify SPA (`web/`), all orchestrated via a single `docker-compose.yml`.
- **Ports & adapters inside each stage.** Domain logic is pure Python; sources, persistence, RAG, and AI runners are adapters behind ports. This is what makes the externalization-readiness claim (ARC-002) testable rather than aspirational.
- **Crawler is a stateless one-shot job**, triggered externally on a 12h cadence. No in-process scheduler living forever inside the crawler container.
- **Single Alembic migration tree** owned by `packages/core`. All services read the same schema; no service owns a migration that touches another service's tables.
- **Pluggable LLM backend via `LLMPort`.** The assessor service owns prompt assembly and context selection; the LLM is called through a thin port with adapters for local (Ollama / LMStudio) and cloud (Anthropic / OpenAI / Gemini) providers. Backend choice is env-driven. Single-shot RAG → completion; no agentic loop.
- **Assessment runs through a job-queue seam** (a `assessment_jobs` Postgres table is sufficient for PoC). The trigger endpoint enqueues, the assessor drains. UI never blocks on a model call.
- **Crawl config split:** mutable per-source `enable` + `N` live in a `crawl_config` Postgres table (UI-writable); cadence and ops settings stay in env / config file.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation & First Crawl** - Repo skeleton, Postgres schema, dedup, and one working crawler (HN) writing to DB
- [x] **Phase 2: Multi-Source Ingest** - Plug in remaining v1 sources behind the source-plugin contract
- [x] **Phase 3: Scheduler & Ops Baseline** - 12h periodic runs, structured logs, single-command docker-compose
- [x] **Phase 4: Topic API & UI Shell** - Backend read API + Vuetify SPA with sortable topic list (breadth/longevity) — Deployed to Cloud Run `https://trend-researcher-3g5goqptla-nw.a.run.app` on 2026-05-17 via `cloudbuild.yaml` v0.4.1 (commit `a33d8d3`)
- [ ] **Phase 5: Topic Detail & Crawl Config UI** - Topic detail view with sources + per-source enable/N control
- [ ] **Phase 6: AI Assessment Foundation** - Local OpenCode runner, RAG over Postgres, retail relevance verdict, business_cases table
- [ ] **Phase 7: Business-Case Generation** - Full business-case schema with importance, opportunity/risk, investment band, confidence
- [ ] **Phase 8: Assessment UI** - Trigger-assessment UI with subset filter + business-case reading view
- [ ] **Phase 9: PoC Hardening & Observation Setup** - Externalization audit, scaling notes, run logbook for the 1–2 month review

## Phase Details

### Phase 1: Foundation & First Crawl
**Goal**: Stand up the monorepo skeleton with the locked architectural shape (multi-service layout, ports & adapters per stage, single Alembic tree in `packages/core`), Postgres schema, dedup, and a single working crawler (HackerNews) that writes deduplicated topics to the database. After this phase, running the crawler service one-shot puts real HN front-page topics into Postgres.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: ARC-001, ARC-003, ING-002, ING-003, ING-005, ING-006, ING-007, ING-008, ING-009, STO-001, STO-002, STO-003, STO-005
**Success Criteria** (what must be TRUE):
  1. Monorepo layout exists with `services/crawler/`, `services/api/` (scaffold only), `services/assessor/` (scaffold only), `packages/core/`, and `web/` (scaffold only) — only `crawler` and `core` carry real code in this phase
  2. Inside `services/crawler/`, the package is split into `domain/`, `ports/`, `adapters/sources/`, `adapters/persistence/`, `app/` — no I/O code lives in `domain/` (verified by import inspection)
  3. `docker-compose up postgres crawler` brings up the database; Alembic migrations (owned by `packages/core`) create `topics` and `topic_sources` tables
  4. Running the HN crawler once as a one-shot job inserts ~30 deduplicated topic rows with their source refs and native ranks, then exits cleanly (no in-process scheduler)
  5. Running the HN crawler a second time does NOT create duplicate topic rows — existing rows are updated (last_seen bumped, observation_count incremented, new source ref appended if URL changed)
  6. `SourcePort` (`fetch() -> list[RawItem]`) and `TopicRepositoryPort` exist as documented Python protocols/ABCs in `services/crawler/ports/`; HN and the Postgres repo are the first conforming adapters
  7. No AI/LLM code path exists in any ingest module (verified by grep across `services/crawler/` and `packages/core/`)
**Plans**: 5 (3 waves)

Plans:
- [x] 01-01: Monorepo skeleton & uv workspace (Wave 1)
- [x] 01-02: Postgres schema, models, Alembic in packages/core (Wave 2)
- [x] 01-03: Crawler ports, domain types, dedup (zero I/O) (Wave 2)
- [x] 01-04: HN source & Postgres repository adapters (Wave 3)
- [x] 01-05: Crawler app, Typer CLI, docker-compose, E2E first crawl (Wave 3)

### Phase 2: Multi-Source Ingest
**Goal**: Onboard the remaining v1 sources (Reddit r/all + r/business + r/retail + 1 TBD retail-adjacent sub, NYT homepage RSS, Google News top stories RSS) behind the source-plugin contract from Phase 1. Pick the retail-adjacent subreddit during the phase.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: ING-004
**Success Criteria** (what must be TRUE):
  1. All six v1 sources (HN, Reddit r/all, Reddit r/business, Reddit r/retail, the chosen retail-adjacent sub, NYT RSS, Google News RSS) implement the source-plugin contract
  2. Running all crawlers once produces topic rows from each source with correct `source_name` attribution in `topic_sources`
  3. Cross-source deduplication works: a story that appears on both NYT and Google News collapses to a single topic with two source refs
  4. Each source's native ranking (`native_rank`) is preserved per source — no cross-source normalization is performed

**Phase 2 reality (post-execution):** ships **3 sources** (HN + NYT homepage + Google News), not 7. Reddit's anonymous endpoints (both `/.json` and `/.rss`) return HTTP 403 to `httpx` from datacenter IPs regardless of User-Agent — the WAF fingerprints the TLS / HTTP-client stack. Plain `curl` from the same network gets 200, and `httpx` from a residential IP also gets 200, so the adapter works for the operator locally but is incompatible with future scheduled deployment without OAuth. The 4 `RedditJsonSource` adapter file is kept in tree (still has unit tests) but is NOT registered in `build_sources()`. Reddit OAuth is parked as Phase 3+ follow-up. Full analysis in `.planning/phases/02-multi-source-ingest/CONTEXT.md` "Reddit access reality" + `SMOKE-RESULTS.md`.

**Phase 2 in-flight bug fix:** Plan 02-04 also discovered and shipped a hot-fix for `find_candidates` (recent-window scan default `limit` 50 → 5000). Phase 1's 50-row window silently broke the moment the DB grew past 50 topics. The proper fix (indexed `dedup_key` column lookup) is parked for Phase 3.

Plans:
- [x] 02-01: Reddit JSON adapter (Wave 1) — adapter shipped + tested; later unregistered in 02-04 (kept in tree)
- [x] 02-02: RSS adapter + NYT/Google News registration (Wave 2)
- [x] 02-03: Orchestrator failed_sources field + cross-source dedup proof (Wave 3)
- [x] 02-04: Live E2E smoke + hot-fixes (dedup window 50→5000, Reddit drop) + closeout (Wave 4)

### Phase 3: Scheduler & Ops Baseline
**Goal**: Move from "manual crawl invocation" to "runs itself every 12 hours" via an external scheduler invoking the crawler as a one-shot job. Add the operational baseline needed to leave it running unattended for the PoC observation window.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: ING-001, OPS-001, OPS-002, OPS-003
**Success Criteria** (what must be TRUE):
  1. A single `docker-compose up` brings up Postgres + the api-service shell + a scheduler mechanism (cron-in-container or equivalent) that triggers the crawler as a stateless one-shot job every 12 hours
  2. The crawler container starts, runs all enabled sources once, writes results, and exits — verified by container exit code 0 and no long-lived crawler process
  3. Each crawl produces structured per-source log records (timestamp, source, item count, dedup hits, errors) — chosen sink (file vs. table) is documented in OPS notes
  4. A source can be disabled at runtime via config change without rebuilding or redeploying any image (config change picked up by the next scheduled run)
  5. After 24+ hours of unattended operation, observation_count and last_seen_at on persistent trending stories increase as expected

**Phase 3 reality (post-execution):** ships exactly as planned — 5 vertical slices, 28 task commits + 5 SUMMARY commits. One in-flight hot-fix surfaced during smoke: the root `pyproject.toml` `[tool.uv.workspace]` `members` glob `services/*` was tripping on the new `services/scheduler/` directory (alpine + crond image, no Python pyproject.toml) and breaking `uv lock` / `uv sync` runs. Replaced the glob with an explicit member list. uv.lock unchanged. Live 3-trigger E2E smoke (`scripts/smoke_phase3.sh`) green on 2026-05-16: 77 topics ingested then 2× updated, 3 crawl_runs rows written, `/healthz` ok, `/runs?limit=5` returns 3 rows newest-first, scheduler crontab loaded in container logs. The 24h-unattended success criterion (#5) is captured as an empty section in `SMOKE-RESULTS.md` for operator post-fill after the next two scheduled tick windows; this is the conscious deferral locked in CONTEXT.md decision D.

Plans:
- [x] 03-01: crawl_runs table + write path (Wave 1)
- [x] 03-02: api service shell with /healthz + /runs (Wave 2)
- [x] 03-03: CRAWLER_DISABLED_SOURCES env filter (Wave 3)
- [x] 03-04: scheduler service (alpine + crond) + docker-compose wiring (Wave 4)
- [x] 03-05: scripts/smoke_phase3.sh + Phase 3 closeout (Wave 5)

### Phase 4: Topic API & UI Shell
**Goal**: Expose topics through a backend read API and stand up the Vuetify SPA with the primary topic list view — sortable by breadth, longevity, and last-seen. After this phase, a human can open the UI and see what's trending across all six sources.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: UI-001, UI-002, STO-006
**Success Criteria** (what must be TRUE):
  1. [x] Backend read API returns topics with `breadth` (cross-source count) and `longevity` (days observed) computed via SQL, not stored
  2. [x] Vuetify SPA loads the topic list and renders it as a sortable Vuetify data table
  3. [x] Sort by breadth, longevity, and last_seen all work and the resulting order matches a hand-checked SQL query
  4. [x] Each row links to a topic detail route (placeholder/empty page acceptable in this phase)

Plans:
- [x] 04-01 (W1): Alembic 0003 `v_topic_stats` view (breadth, longevity_seconds) + tests
- [x] 04-02 (W2, deps: 04-01): `/api/*` re-prefix + `GET /api/topics` list endpoint (sort whitelist + limit) + tests
- [x] 04-03 (W3, deps: 04-02): `GET /api/topics/{id}` detail endpoint + nested sources + tests
- [x] 04-04 (W4, deps: 04-03): Vuetify 3 SPA scaffold at `web/` (TopicList + TopicDetail + Vite proxy + formatLongevity + thbe brand palette)
- [x] 04-05 (W5, deps: 04-04, **autonomous=false**): Ubuntu+PG-16 3-stage Dockerfile + docker-entrypoint.sh + `scripts/pg-dump-rotate.sh` + StaticFiles mount + dump-debouncer middleware + `scripts/smoke_phase4.sh` (local + prod-image modes) + README + SUMMARY
- [x] 04-06 (W6, deps: 04-05, **autonomous=false**): PAT-secured `POST /api/internal/crawl` + DELETE `services/scheduler/` tree + drop scheduler from compose + `cloudbuild.yaml` (Cloud Run + GCS-FUSE + Secret Manager) + `.env.example` + PAT tests + `CLOUD-RUN-DEPLOY.md` + first Cloud Run deploy + closeout

**Phase 4 deployed:** `https://trend-researcher-3g5goqptla-nw.a.run.app` on 2026-05-17 (Cloud Run europe-west2, revision 00002, image v0.4.1, commit `a33d8d3`). 6/6 smoke PASS; Cloud Scheduler job `trend-researcher-crawl` ENABLED on `0 */12 * * *` UTC.

**Phase 4 amendment (2026-05-16, post-plan / pre-execute):** production target locked to single-container Cloud Run + GCS-FUSE dump-sync + PAT-secured cron API, adopting the `food-assistant` sibling-repo pattern verbatim. Plan shape grew from 5 → 6 plans (04-05 rewritten; 04-06 added). `services/scheduler/` deleted in-phase (replaced by Cloud Scheduler → `/api/internal/crawl`). Locked decisions G9 (30 s debounce + 3-slot ring + `pg_restore --list` verify), G10 (GCP Secret Manager → `TREND_INTERNAL_PAT`, `hmac.compare_digest`, fail-closed 503), G11 (scheduler-deletion same phase). See `.planning/phases/04-topic-api-ui-shell/DISCUSSION-LOG.md` amendment section + `CONTEXT.md` amendment block.

### Phase 5: Topic Detail & Crawl Config UI
**Goal**: Make individual topics inspectable (sources, raw payloads where relevant) and let the operator manage crawl scope — enable/disable sources and tune per-source `N` — from the UI without editing config files. Introduces the `crawl_config` Postgres table as the single source of truth for mutable crawl settings.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: UI-003, UI-004
**Success Criteria** (what must be TRUE):
  1. Topic detail view shows: title, description, all source refs (source name + URL + native rank + observed_at), first_seen, last_seen, observation_count
  2. `crawl_config` Postgres table exists (Alembic migration in `packages/core`) holding per-source `enabled` and `n` values; the crawler reads it at the start of each run
  3. Crawl-config view in the UI lists all sources with an enable/disable toggle and an editable per-source N value, and writes changes to `crawl_config`
  4. Toggling a source off in the UI causes the next scheduled crawl to skip that source (cadence stays env-driven; only enable + N are UI-mutable)
  5. Cadence and other operational settings remain in env / config file — they are NOT exposed in the crawl-config UI

Plans:
- [ ] 05-01: TBD

### Phase 6: AI Assessment Foundation
**Goal**: Land the first end-to-end AI slice: define `LLMPort` and `RAGPort` in the assessor service, ship one local LLM adapter (Ollama or LMStudio) and one cloud LLM adapter (Anthropic or OpenAI), pull one topic from Postgres via a RAG harness, and emit a binary retail-relevance verdict with a reason — persisted into a new `business_cases` table. The assessor service owns prompt assembly end-to-end. This is the moment Stage 2 comes online.
**Mode:** mvp
**Depends on**: Phase 5
**Requirements**: AI-001, AI-002, AI-003, AI-004, AI-006, AI-007, STO-004
**Success Criteria** (what must be TRUE):
  1. `business_cases` table exists via Alembic migration in `packages/core` with the v1 schema columns (topic_id, relevance_verdict, relevance_reason, model_used, prompt_version, generated_at) — full business-case fields land in Phase 7
  2. `LLMPort` (`complete(messages, model_id, response_schema) -> structured_output`) and `RAGPort` exist in `services/assessor/ports/`; one local adapter (Ollama or LMStudio) and one cloud adapter (Anthropic or OpenAI) implement `LLMPort`
  3. Switching providers requires only env-var changes (`LLM_PROVIDER`, `LLM_MODEL`) — no code change, no rebuild
  4. Prompt templates and context-selection logic live in `services/assessor/domain/` — no prompt assembly happens inside any LLM adapter
  5. Running the assessment pipeline against a single topic produces one row in `business_cases` with a binary `relevance_verdict` (relevant/not-relevant for retail) and a non-empty `relevance_reason`, generated via single-shot RAG → LLM call (no agentic loop)
  6. The assessment is invoked explicitly (CLI or API endpoint), never as an ingest hook — the Stage 1 / Stage 2 separation invariant remains intact
  7. `model_used` and `prompt_version` are recorded on every row so the same topic can be re-assessed later (with the same or different provider) and results compared
  8. The RAG harness reads from Postgres, not from a separate vector store

Plans:
- [ ] 06-01: TBD

### Phase 7: Business-Case Generation
**Goal**: Extend Phase 6's relevance-only assessment into the full business-case schema: importance score with rationale, opportunity-or-risk classification, suggested action, rough investment band (XS–XL), confidence level. Add the trigger-assessment endpoint behind a job-queue seam so the UI never blocks on a model call.
**Mode:** mvp
**Depends on**: Phase 6
**Requirements**: AI-005
**Success Criteria** (what must be TRUE):
  1. `business_cases` schema is extended (Alembic migration in `packages/core`) to include importance_score (1–10), importance_rationale, opportunity_or_risk enum, suggested_action, rough_investment_estimate (XS/S/M/L/XL), confidence (low/med/high)
  2. `assessment_jobs` Postgres table exists holding queued assessment work (job_id, subset_filter, status, created_at, finished_at, business_case_ids)
  3. POST endpoint accepts an assessment request (single topic id or a subset filter), enqueues an `assessment_jobs` row, and returns the `job_id` immediately — it does NOT wait for the model call to finish
  4. The assessor service drains the job queue, runs assessment via the configured `LLMPort` adapter (Phase 6), writes business_cases, and marks the job done
  5. Running assessment on a relevant topic produces a row populated across all business-case fields with internally consistent values (e.g., a high importance + low confidence is flagged in the rationale, not silently inconsistent)
  6. Assessment runs are reproducible: re-running with the same `prompt_version` and `model_used` against the same topic data produces structurally equivalent output (field-presence and verdict stable, free-text may vary)

Plans:
- [ ] 07-01: TBD

### Phase 8: Assessment UI
**Goal**: Close the loop — let the operator trigger assessment from the UI for a filtered subset of topics and read the resulting business cases in a dedicated, sortable view.
**Mode:** mvp
**Depends on**: Phase 7
**Requirements**: UI-005, UI-006
**Success Criteria** (what must be TRUE):
  1. UI exposes a "trigger assessment" action that accepts a subset filter (e.g., last 24h, top-N by breadth, single topic) and calls the Phase 7 endpoint, receiving a `job_id` back
  2. UI shows assessment job status (queued / running / done / failed) for triggered jobs and surfaces the resulting business_cases when the job completes (polling acceptable for PoC)
  3. Business-case reading view lists all business_cases sortable by importance_score and filterable by opportunity_or_risk
  4. Each topic's detail page (Phase 5) now also shows its associated business_case history with timestamps and model_used per case
  5. Triggering assessment on an empty subset shows a clear "nothing to assess" UI state, not an error

Plans:
- [ ] 08-01: TBD

### Phase 9: PoC Hardening & Observation Setup
**Goal**: Get the system into shape for the 1–2 month observation window that determines PoC success. Audit that the externalization-ready seams actually hold, write down what would change at scale, and set up a lightweight logbook so reviewing 5 business cases at the end of the window is tractable.
**Mode:** mvp
**Depends on**: Phase 8
**Requirements**: ARC-002, ARC-004
**Success Criteria** (what must be TRUE):
  1. Architecture audit document confirms ingest / store / assessment / UI are separable units (each has an explicit module boundary, public interface, and could be lifted into its own service without code surgery into siblings)
  2. Scaling notes document captures the concrete changes that would be required to externalize: multi-tenancy hooks, auth boundaries, per-tenant data isolation strategy, what breaks at 100x topic volume — written as guidance, not implemented
  3. A run logbook (file or DB-backed) records every assessment run with timestamp, subset filter used, business_case ids produced — sufficient to pick "5 generated business cases" for the success-criterion review in 1–2 months
  4. README documents the PoC success criterion and how to perform the review at the end of the observation window

Plans:
- [ ] 09-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & First Crawl | 5/5 | Complete | 2026-05-14 |
| 2. Multi-Source Ingest | 4/4 | Complete | 2026-05-15 |
| 3. Scheduler & Ops Baseline | 5/5 | Complete | 2026-05-16 |
| 4. Topic API & UI Shell | 0/6 | Planned (amended: +04-06 for Cloud Run deploy) | - |
| 5. Topic Detail & Crawl Config UI | 0/TBD | Not started | - |
| 6. AI Assessment Foundation | 0/TBD | Not started | - |
| 7. Business-Case Generation | 0/TBD | Not started | - |
| 8. Assessment UI | 0/TBD | Not started | - |
| 9. PoC Hardening & Observation Setup | 0/TBD | Not started | - |
