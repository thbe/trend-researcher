# Requirements — Trend Researcher

> Source of truth for what v1 must deliver. Each requirement has a stable REQ-ID used by the roadmap and phase plans.
> Format: `[CATEGORY]-[NUMBER]`. Categories: `ING` (ingest), `STO` (storage), `AI` (assessment), `UI` (frontend), `OPS` (operations), `ARC` (architecture), `OOS` (out of scope).

---

## v1 — Validated, in scope

### Ingestion (ING)

- **ING-001 — Periodic crawl scheduler.** A scheduler runs every **12 hours** and triggers a crawl pass over all enabled sources. Single global cadence; per-source overrides are explicitly NOT a v1 requirement.
- **ING-002 — Top-N per source.** Each source crawler returns its top-N items based on that source's own native ranking signal (hot, trending, top, viral, front-page, whatever the source uses). **Default N = 100 per source**, configurable per source.
- **ING-003 — Native ranking, no normalization.** Crawlers must NOT attempt to normalize or compare ranking signals across sources. Each source's order is preserved as-is and stored as part of the source-reference metadata.
- **ING-004 — Initial v1 source set.** v1 ships with crawlers for:
  - Hacker News front page
  - Reddit `r/all` hot
  - Reddit `r/business` hot
  - Reddit `r/retail` hot
  - Reddit one additional retail-adjacent sub (TBD during ING phase, e.g. `r/Entrepreneur`)
  - NYT homepage RSS
  - Google News RSS — top stories
- **ING-005 — Public/RSS/unauthenticated only.** All v1 crawlers must use public endpoints, RSS feeds, or unauthenticated public scraping. No paid APIs, no OAuth, no logged-in scraping. Sources that require auth (e.g., X trending) are deferred.
- **ING-006 — Source plugin contract.** Crawlers implement a single Python interface (`fetch() -> list[RawItem]`) so adding a source later is a drop-in change without touching the scheduler or store.
- **ING-007 — Fuzzy dedup at ingest.** Incoming items are deduplicated against existing topics using rapidfuzz-style fuzzy title/keyword matching. Match threshold is configurable; **default similarity threshold = 85** (rapidfuzz token_set_ratio). No embeddings, no LLM dedup at this layer (see OOS-002).
- **ING-008 — Update-on-recrawl semantics.** When an incoming item matches an existing topic, the crawler MUST update the existing row: append a new source-reference (if from a new source or new URL), update `last_seen_at`, increment `observation_count`. It MUST NOT insert a duplicate row.
- **ING-009 — Deterministic, AI-free ingest.** No LLM call may occur in the ingest path. This is an architectural invariant, not an optimization (see ARC-001).
- **ING-010 — Description capture from raw payload.** When a source's raw payload carries a human-readable standfirst/summary (Google News RSS `<description>`, NYT homepage `<description>`), the crawler MUST persist it to `topics.description` using a first-non-empty merge across re-observations. HN topics correctly leave `description` NULL (no such field in their payload). Added 2026-05-17 (Phase 4.5); operator request m1086.
- **ING-011 — In-process URL resolution for redirect tokens.** Google News RSS items expose CBM-base64 redirect tokens (`https://news.google.com/rss/articles/CBM...`) instead of publisher URLs. The crawler MUST attempt to decode these in-process (zero new outbound HTTP, ARC-001 preserved) and store the result in `topic_sources.resolved_url`. Decoder failures (modern opaque tokens) MUST log structlog.warn and leave `resolved_url` NULL; the SPA falls back to the original `url`. Added 2026-05-17 (Phase 4.5).

### Storage (STO)

- **STO-001 — PostgreSQL as the topic store.** Single PostgreSQL database. v1 may run a single instance with no HA.
- **STO-002 — Topic table shape.** One row per distinct topic. Required typed columns: `id`, `title`, `description`, `first_seen_at`, `last_seen_at`, `observation_count`, `created_at`, `updated_at`. Plus one `JSONB` column `metadata` for raw source-specific payload that does not deserve a typed column.
- **STO-003 — Source references as a separate table.** Many-to-one `topic_sources(topic_id, source_name, url, native_rank, observed_at, raw_payload JSONB)`. A topic can be referenced by N sources over time; each (re-)observation appends a row.
- **STO-004 — Business-case storage.** A separate `business_cases` table records AI assessments. One topic can have multiple business cases over time (one per assessment run). See AI-005 for schema.
- **STO-005 — Migrations under version control.** All schema changes via a migration tool (Alembic recommended). No ad-hoc `ALTER TABLE`.
- **STO-006 — Breadth & longevity are derivable, not stored.** `breadth = count(distinct source_name) per topic` and `longevity = last_seen_at - first_seen_at`. Computed via SQL views or queries; no denormalized columns in v1.

### AI Assessment (AI)

- **AI-001 — Assessment is an explicit run, not a hook.** Assessment runs are triggered separately from ingest (manually from UI or on a schedule), never as a side-effect of a crawl pass.
- **AI-002 — Pluggable LLM backend via `LLMPort`.** The assessor service defines an `LLMPort` (`complete(messages, model_id, response_schema) -> structured_output`) and provides multiple adapters. v1 ships **at least one local adapter** (Ollama or LMStudio — whichever is preferred during the AI phase) AND **at least one cloud adapter** (Anthropic or OpenAI). Backend choice is env-driven (`LLM_PROVIDER`, `LLM_MODEL`); switching providers requires no code change. The assessor service — not the LLM framework — owns prompt assembly and context selection. No agentic tool-use loop in v1 (see OOS-010).
- **AI-003 — RAG over Postgres topic store.** The assessment layer queries the topic store (and source references) as its retrieval context. Retrieval strategy is implementation-defined but MUST be documented in the AI phase plan.
- **AI-004 — Retail-market relevance filter.** For each candidate topic, the assessor produces a binary relevance verdict (`relevant` / `not_relevant`) for the retail market, plus a short reason. Irrelevant topics get a stored verdict but no business case.
- **AI-005 — Business-case schema (relevant topics only).** Generated business cases include:
  - `topic_id`
  - `relevance_verdict` (`relevant` | `not_relevant`)
  - `relevance_reason` (short text)
  - `importance_score` (integer 1–10)
  - `importance_rationale` (short text)
  - `opportunity_or_risk` (enum: `opportunity` | `risk` | `mixed`)
  - `suggested_action` (free text)
  - `rough_investment_estimate` (band enum: `XS` | `S` | `M` | `L` | `XL`)
  - `confidence` (`low` | `medium` | `high`)
  - `model_used` (string)
  - `generated_at` (timestamp)
- **AI-006 — Single seed market: retail.** v1 prompts and evaluation rubrics are retail-specific. Multi-market is OOS-005.
- **AI-007 — Reproducibility metadata.** Every business case stores enough context (model id, prompt version) to re-explain how it was produced.

### Frontend (UI)

- **UI-001 — TypeScript + Vuetify SPA.** Frontend is a TypeScript + Vuetify single-page app talking to a backend API.
- **UI-002 — Topic browsing view.** List/table of topics with: title, brief description, source count (breadth), days observed (longevity), first/last seen, and links to source references. Sortable by breadth, longevity, last_seen.
- **UI-003 — Topic detail view.** Per-topic page showing all source references, full metadata, and any business cases attached to the topic.
- **UI-004 — Crawl-run configuration view.** UI to view and edit per-source enabled/disabled state and per-source N value. (Schedule cadence is config-file driven in v1, not UI-editable — see ING-001.)
- **UI-005 — Trigger assessment run.** UI control to trigger an on-demand assessment run over a filterable subset of topics (e.g., topics seen in the last 7 days, breadth ≥ 2).
- **UI-006 — Business-case reading view.** UI surface for reading generated business cases, sortable by `importance_score` and filterable by `opportunity_or_risk`.

### Operations (OPS)

- **OPS-001 — Containerized local run.** The whole stack (crawler runner, Postgres, backend API, frontend) runs locally via `docker-compose up`. Single command brings it up.
- **OPS-002 — Crawl logs.** Each crawl pass writes a structured log entry per source: items fetched, items new, items updated, errors. Persisted (file or table — chosen during OPS phase).
- **OPS-003 — Manual back-pressure / pause.** Operator can disable a source via config without redeploying.

### Architecture (ARC)

- **ARC-001 — Hard separation: deterministic ingest vs AI assessment.** No LLM calls, embeddings, or other non-deterministic operations in the ingest path. Architectural invariant; enforced by code review and by keeping the AI runtime out of the crawler service.
- **ARC-002 — Externalization-ready seams.** Ingest, storage, assessment, and frontend are separate runnable units with clear contracts (HTTP/SQL boundaries). v1 does NOT externalize, but the seams must already exist so externalization is a future feature, not a rewrite.
- **ARC-003 — Source-plugin architecture.** Crawlers are plugins behind a single interface (see ING-006).
- **ARC-004 — Single-operator footprint.** No HA, no multi-region, no horizontal scaling concern in v1. Architecture documents must call out where this would change for externalization.

---

## v2+ — Out of scope for now (deferred, not rejected)

- **OOS-001 — Multi-tenancy.**
- **OOS-002 — Embeddings / pgvector / vector clustering at ingest.** (Stage 2 RAG may use embeddings internally; Stage 1 dedup must not.)
- **OOS-003 — LLM-based deduplication.** Reusing `LLMPort` from the assessor in the crawler is technically possible but explicitly deferred — see ARC-001 / ING-009. Reconsider only if PoC review reveals fuzzy dedup as a primary cause of poor business-case quality.
- **OOS-004 — Authentication / authorization.** (Internal-only PoC.)
- **OOS-005 — Multi-market support beyond retail.**
- **OOS-006 — Normalized cross-source importance scores.** (Per-source native ranking is sufficient for v1.)
- **OOS-007 — Public-facing UI, SSO, billing, audit logs, SLA work.**
- **OOS-008 — Per-source crawl-cadence overrides.** (Single global 12h cadence in v1.)
- **OOS-009 — Authenticated/paid-API sources.** (Notably X trending; deferred until value of public-source v1 is proven.)
- **OOS-010 — Agentic LLM tool-use loop.** v1 assessment is single-shot: deterministic RAG fetches context, then one LLM call produces the structured business case. The LLM does NOT autonomously query the database or invoke tools.

---

## Multi-Tenant Platform (MT-*)

Requirements introduced by **Phase 10 — Multi-Tenant Market Intelligence Platform**.
These supersede OOS-001 (multi-tenancy) and OOS-005 (multi-market) for the scope
defined here. Original AI-006 ("single seed market: retail") is preserved as the
*default* department behaviour but no longer an architectural constraint.

- **MT-001 — Departments as first-class entities.** The system supports N ≥ 1 departments coexisting with isolated per-department configuration (sources subscription, AI config, framework selection, business context). Departments are managed by system superadmins.
- **MT-002 — Per-(user, department) RBAC.** Users may belong to multiple departments; role is keyed on the `(user, department)` pair. Roles: `viewer` (read), `analyst` (read + assess), `dept_lead` (read + assess + manage dept config + write harmonization Net View). System superadmin is a separate orthogonal boolean flag (`users.is_superadmin`).
- **MT-003 — Global topics, per-department assessments.** Topics remain a single global deduplicated stream (ARC-001 preserved). All assessment artefacts (business_cases, assessment_jobs) are scoped to a `(department, framework)` pair.
- **MT-004 — Crawler runs as single global one-shot job.** The crawler continues to run once per cadence; its effective source list is the **union** of all departments' active source subscriptions. `crawl_runs` rows still reflect one global run per invocation.
- **MT-005 — Pluggable assessment frameworks.** Assessment frameworks are pluggable; v1 seeds `verdict` (current schema preserved verbatim), `swot`, and `pestle`. Each department selects ≥ 1 enabled framework with one marked as default. Same topic can be assessed under multiple frameworks within one department.
- **MT-006 — Business cases keyed by (topic, department, framework).** `business_cases` rows are uniquely keyed on `(topic_id, department_id, framework_id, prompt_version, model_used)`. Framework-specific structured output lives in a `structured_output` JSONB column; existing denormalised top-level fields (`relevance_verdict`, `relevance_reason`) are populated from the framework's top-level slots for cheap sorting/filtering.
- **MT-007 — Cross-department harmonization view.** A harmonization view per topic shows side-by-side `business_cases` from every `(department, framework)` pair that assessed it, plus an optional admin-authored Net View free-text annotation persisted in `topic_harmonizations`. Any logged-in user can read; only `dept_lead` (of any dept) or `is_superadmin` can write the Net View.
- **MT-008 — Lossless default-department migration.** Existing single-tenant production data migrates losslessly into a seeded `Default` department; the existing seed user becomes `is_superadmin = true` and `dept_lead` of Default. All pre-migration `topics`, `business_cases`, `ai_config`, `crawl_config`, `assessment_jobs` remain visible and behaviour is identical to pre-migration until a second department is created.
- **MT-009 — Ingest stays AI-free under multi-tenancy.** ARC-001 is preserved across the multi-tenant refactor; the crawler's only new dependency on departments is reading the union source-subscription list from `department_sources`. No AI code path exists in the crawler or in any `department_sources` resolution (verified by grep).

---

## Traceability

| REQ-ID    | Title                                | Phase         | Status   |
| --------- | ------------------------------------ | ------------- | -------- |
| ING-001   | Periodic crawl scheduler             | Phase 3          | proposed |
| ING-002   | Top-N per source                     | Phase 1       | proposed |
| ING-003   | Native ranking, no normalization     | Phase 1       | proposed |
| ING-004   | Initial v1 source set                | Phase 2       | proposed |
| ING-005   | Public/RSS/unauthenticated only      | Phase 1       | proposed |
| ING-006   | Source plugin contract               | Phase 1       | proposed |
| ING-007   | Fuzzy dedup at ingest                | Phase 1       | proposed |
| ING-008   | Update-on-recrawl semantics          | Phase 1       | proposed |
| ING-009   | Deterministic, AI-free ingest        | Phase 1       | proposed |
| ING-010   | Description capture from raw payload | Phase 4.5     | done     |
| ING-011   | In-process URL resolution            | Phase 4.5     | done     |
| STO-001   | PostgreSQL topic store               | Phase 1       | proposed |
| STO-002   | Topic table shape                    | Phase 1       | proposed |
| STO-003   | Source references table              | Phase 1       | proposed |
| STO-004   | Business-case storage                | Phase 6       | proposed |
| STO-005   | Migrations under version control     | Phase 1       | proposed |
| STO-006   | Breadth & longevity derivable        | Phase 4       | proposed |
| AI-001    | Assessment as explicit run           | Phase 6       | proposed |
| AI-002    | Pluggable LLM backend via LLMPort    | Phase 6       | proposed |
| AI-003    | RAG over Postgres                    | Phase 6       | proposed |
| AI-004    | Retail-market relevance filter       | Phase 6       | proposed |
| AI-005    | Business-case schema                 | Phase 7       | proposed |
| AI-006    | Single seed market: retail           | Phase 6       | proposed |
| AI-007    | Reproducibility metadata             | Phase 6       | proposed |
| UI-001    | TS + Vuetify SPA                     | Phase 4       | proposed |
| UI-002    | Topic browsing view                  | Phase 4       | proposed |
| UI-003    | Topic detail view                    | Phase 5       | proposed |
| UI-004    | Crawl-run configuration view         | Phase 5       | proposed |
| UI-005    | Trigger assessment run               | Phase 8       | proposed |
| UI-006    | Business-case reading view           | Phase 8       | proposed |
| OPS-001   | Containerized local run              | Phase 3       | proposed |
| OPS-002   | Crawl logs                           | Phase 3       | proposed |
| OPS-003   | Manual back-pressure / pause         | Phase 3       | proposed |
| ARC-001   | Hard separation invariant            | Phase 1       | proposed |
| ARC-002   | Externalization-ready seams          | Phase 9       | superseded (folded into Phase 10) |
| ARC-003   | Source-plugin architecture           | Phase 1       | proposed |
| ARC-004   | Single-operator footprint            | Phase 9       | superseded (folded into Phase 10) |
| MT-001    | Departments as first-class entities  | Phase 10      | proposed |
| MT-002    | Per-(user, department) RBAC          | Phase 10      | proposed |
| MT-003    | Global topics, per-dept assessments  | Phase 10      | proposed |
| MT-004    | Crawler as single global job         | Phase 10      | proposed |
| MT-005    | Pluggable assessment frameworks      | Phase 10      | proposed |
| MT-006    | Business cases keyed by (topic, dept, framework) | Phase 10 | proposed |
| MT-007    | Cross-department harmonization view  | Phase 10      | proposed |
| MT-008    | Lossless default-department migration | Phase 10     | proposed |
| MT-009    | Ingest stays AI-free under multi-tenancy | Phase 10  | proposed |

---
_Last updated: 2026-05-27 (Phase 10 plan 10-00 — MT-001..MT-009 added; ARC-002/ARC-004 marked superseded; Phase 9 superseded by Phase 10)_
