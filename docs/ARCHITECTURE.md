# Architecture

> **Status:** as-built, current as of `main` @ Phase 10 complete (multi-tenant platform with harmonization).
> **Audience:** developers maintaining the system, operators deploying it, future contributors evaluating where new functionality belongs.

---

## 1. Goals & Constraints (recap)

Trend Researcher is a single-operator internal tool that delivers **360° situational awareness** for a target market (retail in v1) by combining deterministic crawling with AI-driven relevance assessment.

The architecture is shaped by four locked constraints:

| Constraint | Implication |
|---|---|
| **AI lives only in Stage 2 (assessment)** | Ingest must be reproducible without API keys / models. Topic store stays trustworthy and cheap. |
| **Stage 1 dedup is fuzzy string matching only** | No embeddings / no AI in `services/crawler`. `rapidfuzz` ratios over normalised titles. |
| **Single-operator footprint** | No HA, no multi-region, no compliance regime. One container can be the whole production deployment. |
| **Locked stack** | Python (ingest, API, assess) + PostgreSQL + TypeScript/Vuetify. AI tooling pluggable behind an adapter. |

---

## 2. Logical Layers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Vue 3 + Vuetify SPA (web/)                         │
│   Dashboard │ Topic list │ Topic detail │ AI config │ Crawl config │ Login  │
│   Dept switcher │ Framework cards │ Harmonization tab │ Settings views │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │ HTTP + cookie session
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       FastAPI control plane (services/api/)                 │
│  Routes: topics │ runs │ crawl-config │ ai-config │ assessment │ dashboard  │
│  Routes: departments │ harmonization │ frameworks │ users                    │
│  Cross-cutting: auth middleware │ RBAC deps │ dump-debouncer │ SPA mount    │
└─────────────────────────────────────────────────────────────────────────────┘
                │                          │                            │
                │ invokes orchestrator     │ enqueues background job    │
                ▼                          ▼                            │
┌────────────────────────┐  ┌──────────────────────────────────────┐    │
│  Stage 1 — Ingest      │  │  Stage 2 — Assessment (AI)           │    │
│  services/crawler/     │  │  services/assessor/                  │    │
│                        │  │                                      │    │
│  Sources (RSS/API) →   │  │  AssessmentPipeline:                 │    │
│  RawItem normalisation │  │    RAG (PostgresRAGAdapter) ──┐      │    │
│  → fuzzy dedup         │  │    LLM port  ─── adapter ─────┤      │    │
│  → TopicRepository     │  │      ├─ OllamaAdapter         │      │    │
│                        │  │      ├─ OpenAIAdapter         │      │    │
│                        │  │      └─ AnthropicAdapter      │      │    │
│                        │  │    → BusinessCase persistence │      │    │
└────────────┬───────────┘  └──────────────────┬────────────┴──────┘    │
             │                                 │                        │
             └──────────────┬──────────────────┴────────────────────────┘
                            ▼
            ┌──────────────────────────────────┐
            │   PostgreSQL 16 (packages/core)  │
            │   Tables: topic, topic_source,   │
            │   crawl_run, crawl_config, user, │
            │   ai_config, assessment_job,     │
            │   business_case                  │
            └──────────────────────────────────┘
```

The **only** AI-bearing layer is `services/assessor`. Everything below it (Postgres, crawler, models) and the SPA above it remain AI-free.

---

## 3. Component Map

### 3.1 `packages/core` — Shared kernel

Single source of truth for persistence. No service contains its own ORM models.

- `core/models.py` — SQLAlchemy 2 declarative models:
  - `Topic`, `TopicSource` — deduplicated topic store with per-source observations.
  - `CrawlRun` — per-run telemetry (totals, per-source breakdown, failed sources).
  - `CrawlConfig` — runtime-editable source roster (enabled, top_n, capture_summary, feed_url).
  - `User` — bcrypt-hashed credentials for SPA login.
  - `AIConfig` — singleton row (`key='default'`) holding base_url, model, api_token, business_context, opportunity_criteria, risk_criteria, thinking_effort, **request_timeout_seconds**.
  - `AssessmentJob` — background job state for batch assessments.
  - `BusinessCase` — AI verdict + reasoning per topic.
- `core/db.py` — async engine + session factory.
- `core/config.py` — `Settings` (pydantic) — env-var loader.
- `alembic/versions/` — schema migrations (0001…0015). Applied automatically at container boot.

### 3.2 `services/crawler` — Stage 1 (ingest)

Hexagonal layout (`adapters` / `ports` / `domain` / `app`):

- `ports/source_port.py` — abstract source contract (`fetch_top(n) -> list[RawItem]`).
- `adapters/sources/` — concrete sources: NYT, Google News, Hacker News, Reddit, BBC, etc. Each pulls top-N by the source's native ranking signal.
- `domain/raw_item.py` — normalised, source-agnostic item.
- `domain/dedup.py` — `rapidfuzz`-based fuzzy matching over normalised titles. **The only dedup mechanism.** Threshold and policy live here.
- `ports/topic_repository_port.py` / `adapters/persistence/` — write/update `Topic` + `TopicSource` rows. Re-crawls **upsert** (accumulate observations, bump `last_seen_at`), never duplicate.
- `app/orchestrator.py` — fan-out across enabled sources, per-source error isolation, run telemetry.
- `app/cli.py` — Typer CLI (`crawler run-once …`) used by docker-compose and by `POST /api/internal/crawl`.

**Invariants:**
- No `import openai|anthropic|ollama|httpx_llm` anywhere under `services/crawler/`.
- No embeddings, no vector store, no semantic similarity.
- One source failing must never block other sources or the run as a whole (recorded in `failed_sources`).

### 3.3 `services/assessor` — Stage 2 (AI)

Same hexagonal layout. **The only AI-bearing module.**

- `ports/llm.py` — abstract LLM contract (`assess(prompt, …) -> structured output`).
- `ports/rag.py` — abstract retrieval contract.
- `adapters/ollama_adapter.py`, `openai_adapter.py`, `anthropic_adapter.py` — pluggable providers. All honour the same prompt protocol.
- `adapters/postgres_rag.py` — pulls topic + source context from Postgres for the prompt.
- `domain/pipeline.py` — `AssessmentPipeline`: RAG → prompt → LLM → parse → persist `BusinessCase` + verdict on `Topic`.
- `domain/prompts.py` — versioned prompt (current: **v4** with materiality gate + negative few-shots). Bumped when behaviour changes.
- `app/cli.py`, `app/composition.py` — standalone CLI entry point (in addition to API-triggered assessments).

**Adapter selection** (in `services/api/src/api/routes/assessment.py::_build_pipeline`):

```
if "anthropic" in base_url        → AnthropicAdapter
elif "openai" in base_url or api_token → OpenAIAdapter
else                              → OllamaAdapter(request_timeout_seconds=…)
```

Selection is purely a function of the values in the `ai_config` row — no code change required to switch providers in production.

### 3.4 `services/api` — Control plane

Single FastAPI app. Hosts both JSON API and (in prod) the built SPA.

- `api/main.py` — app construction, middleware order, conditional SPA `StaticFiles` mount when `WEB_DIST_DIR` is set.
- `api/routes/` — one router per resource:
  - `auth.py` → login/logout/me (HMAC-SHA256 signed cookie sessions, bcrypt password verification).
  - `topics.py` → list + detail.
  - `runs.py` → recent crawl runs.
  - `crawl_config.py` → list + per-source update.
  - `ai_config.py` → GET/PUT singleton + `GET /ai-config/models` (proxies Ollama `/api/tags`).
  - `assessment.py` → `POST /assess` (batch background job), `POST /assess/{id}` (sync), `GET /assess/jobs[/{id}]`, `GET /business-cases`.
  - `dashboard.py` → aggregate counts.
  - `internal.py` → `POST /internal/crawl` (Bearer-PAT-authenticated, called by Cloud Scheduler).
  - `healthz.py` → unauthenticated liveness + DB ping.
- `api/middleware/` — auth guard (rejects unauthenticated `/api/*` except login/logout/healthz/internal) + dump-debouncer (triggers `pg-dump-rotate.sh` ≤30s after writes, prod only).
- `api/schemas.py` — Pydantic request/response models.

### 3.5 `web/` — SPA

- Vue 3 + Vuetify 3 + Vite + TypeScript.
- `src/router/index.ts` — routes + global auth guard hitting `/api/me`.
- `src/views/` — `Dashboard`, `TopicList`, `TopicDetail`, `AIConfig`, `CrawlConfig`, `Assessment`, `Login`.
- `src/api/` — thin typed wrappers around `fetch`, throwing `ApiError` on non-2xx.
- **State persistence convention:** list views encode pagination & sort into the URL query string (`?page=…&ipp=…&sort=…`) and bind them via `v-model:` on Vuetify data tables, so browser back-navigation restores prior view state.
- Built artefacts (`web/dist`) are copied into the API container at `/app/web_dist` and served by FastAPI's `StaticFiles` SPA-fallback mount.

---

## 4. Data Flow

### 4.1 Ingest (Stage 1)

```
Cloud Scheduler ──POST /api/internal/crawl (Bearer PAT)──▶ FastAPI
                                                           │
                                                           ▼
                                          crawler.app.orchestrator.run_once()
                                                           │
              ┌─────────────────────────┬──────────────────┼──────────────────────┐
              ▼                         ▼                  ▼                      ▼
        NYT source              GoogleNews source     HN source             … other sources
        (fetch_top N)           (fetch_top N)         (fetch_top N)         (fetch_top N)
              │                         │                  │                      │
              └────────── normalise to RawItem ────────────┴──────────────────────┘
                                                  │
                                                  ▼
                                   domain.dedup (rapidfuzz fuzzy match
                                   against existing Topic.title within
                                   recent window)
                                                  │
                                ┌─────────────────┴─────────────────┐
                                ▼                                   ▼
                          NEW topic                          EXISTING topic
                          INSERT topic                       UPSERT topic_source row,
                          INSERT topic_source                 bump last_seen_at,
                                                              increment observation_count
                                                  │
                                                  ▼
                                          CrawlRun row written
                                          (per-source totals, failed sources)
```

**Concurrency:** sources run in parallel via asyncio. The dedup decision is per-item, not per-batch; a single Postgres transaction commits the topic + source rows for one source's batch.

### 4.2 Assessment (Stage 2)

```
SPA user clicks "Assess Topics"
                │
                ▼
       POST /api/assess?limit=N
                │
                ▼
   Insert AssessmentJob(state=pending)
   Schedule background task _run_job(job_id)
   Return job_id immediately
                │
                ▼
  _run_job (background, single-flight)
       │
       │  load AIConfig singleton
       │  build pipeline (adapter chosen by base_url heuristic)
       ▼
   for each unassessed topic (up to limit):
       RAG: PostgresRAGAdapter assembles topic+sources context
       LLM: adapter.assess(prompt v4, business_context, opportunity_criteria,
                            risk_criteria, request_timeout_seconds)
       parse verdict (relevant|not_relevant + category + reason)
       INSERT business_case
       UPDATE topic.relevance_verdict
       bump job.completed_topics / failed_topics
   set job.state = completed / failed
                │
                ▼
   SPA polls GET /api/assess/jobs/{id} until state == completed
```

**Why background?** A 20-topic batch on `qwen3:4b` at ~7 tok/s can take 10+ minutes. The HTTP request returns immediately with a job id; the SPA polls.

### 4.3 Per-request boundaries

| Concern | Where it lives |
|---|---|
| HTTP timeout per LLM call | `OllamaAdapter._request_timeout_seconds` (configurable via `ai_config.request_timeout_seconds`, default 120s, range 10-3600s) |
| Batch concurrency | One job at a time per `AssessmentJob` row; topics serialised within a job |
| Per-source crawl error isolation | `orchestrator.run_once` catches per-source exceptions, records in `failed_sources` |
| DB write debouncing (prod) | `DumpDebouncer` middleware in `api.middleware` — coalesces writes into one `pg-dump-rotate.sh` invocation per 30s window |

---

## 5. Deployment Topologies

### 5.1 Local / Development (docker-compose)

```
┌──────────────────────────────────────────────────────────────┐
│  Host (Linux/macOS)                                          │
│                                                              │
│  ┌───────────────┐   ┌────────────────┐   ┌──────────────┐ │
│  │ trend-postgres│◀──│   trend-api     │──▶│ trend-ollama │ │
│  │  (postgres:16)│   │  (FastAPI+SPA)  │   │   (ollama)   │ │
│  │   :5432       │   │  :4000→:8000    │   │   :11434     │ │
│  └───────────────┘   └────────────────┘   └──────────────┘ │
│         ▲                    ▲                              │
│         │                    │                              │
│         │            ┌───────────────┐                      │
│         └────────────│ trend-crawler │ (one-shot, no restart)│
│                      └───────────────┘                      │
└──────────────────────────────────────────────────────────────┘
```

- External Postgres (no embedded PG). API connects via service name `postgres`.
- Ollama runs locally; `ai_config.base_url = http://ollama:11434` by default.
- SPA is served by the same FastAPI container from `/app/web_dist`.
- `docker compose run --rm crawler` to trigger a one-shot crawl, or `POST /api/crawl` from the UI.

### 5.2 Production (Cloud Run)

```
                  Cloud Scheduler ──12h──▶ POST /api/internal/crawl (Bearer)
                                                │
                                                ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  Cloud Run service: trend-researcher (europe-west2)            │
   │  Single revision, min=0 max=1, 2vCPU/2GiB, 600s timeout        │
   │                                                                │
   │  ┌──────────────────────────────────────────────────────────┐ │
   │  │  Container (Ubuntu 24.04)                                │ │
   │  │                                                          │ │
   │  │  uvicorn (FastAPI) ◀──▶ embedded PostgreSQL 16          │ │
   │  │       │                  (/var/lib/postgresql, tmpfs)    │ │
   │  │       │                       │                          │ │
   │  │       │             pg_dump / pg_restore                 │ │
   │  │       ▼                       │                          │ │
   │  │  /app/web_dist (SPA)          ▼                          │ │
   │  │                       /app/data ◀── GCS-FUSE             │ │
   │  └──────────────────────────────────┬────────────────────────┘ │
   └────────────────────────────────────┼─────────────────────────┘
                                        ▼
                          gs://trend-researcher-data
                          (trend_researcher.dump, .dump.prev)
```

- **No** Ollama in production. `ai_config.base_url` is set to a hosted endpoint (OpenAI- or Anthropic-compatible) so the adapter-selector picks `OpenAIAdapter` / `AnthropicAdapter`.
- Postgres is embedded inside the container; durability is achieved by debounced `pg_dump` to GCS-FUSE-mounted `/app/data` (see `docs/DEPLOYMENT.md` §"Embedded Postgres Architecture").
- Boot sequence: GCS dump restore → Alembic upgrade → uvicorn. Graceful shutdown: SIGTERM → final dump → `pg_ctl stop`.

---

## 6. Trust Boundaries & Auth

| Boundary | Mechanism | Notes |
|---|---|---|
| Browser ↔ API | HttpOnly cookie `tr_session` (HMAC-SHA256 signed) | Set by `POST /api/login`. Verified by middleware on every `/api/*` request. |
| Cloud Scheduler ↔ API | `Authorization: Bearer <TREND_INTERNAL_PAT>` | Only `/api/internal/*` accepts this; never accepts session cookies. |
| API → LLM provider | `ai_config.api_token` from DB (operator-set) | Stored in plaintext in the singleton row; rotate by `PUT /api/ai-config`. |
| Container ↔ GCS | Cloud Run service-account IAM | Object-level read+write on `gs://trend-researcher-data`. |
| Public bypass | `/api/healthz`, `/api/login`, `/api/logout` | Explicit allow-list in auth middleware. |

**Password handling:** bcrypt with default cost factor. Seed user (`AUTH_SEED_USERNAME` / `AUTH_SEED_PASSWORD`) is created idempotently on boot — never overwrites an existing user.

---

## 7. Schema Evolution

- All schema changes go through Alembic in `packages/core/alembic/versions/`.
- Migrations are auto-applied at container boot by the entrypoint (`alembic upgrade head`). There is no manual migration step in production.
- Naming: `NNNN_short_description.py`, sequential integers. As of writing: `0015_ai_config_request_timeout`.
- Each migration is reversible (`downgrade()` implemented).

When extending `AIConfig`: add the column with a `server_default`, mirror it in the SQLAlchemy model, the Pydantic schemas, the route handler, and the SPA form. The `0014_ai_config_criteria.py` / `0015_ai_config_request_timeout.py` pair is the canonical reference for this 5-file pattern.

---

## 8. Extensibility Points

| You want to… | Touch this |
|---|---|
| Add a new source (e.g. Mastodon) | `services/crawler/adapters/sources/<name>.py` implementing `SourcePort`. Register in `app/composition.py`. Insert row in `crawl_config`. |
| Add a new LLM provider | `services/assessor/adapters/<name>_adapter.py` implementing `LLMPort`. Add a branch in `routes/assessment.py::_build_pipeline`. |
| Change the relevance prompt | `services/assessor/domain/prompts.py`. **Bump `prompt_version`** so persisted `BusinessCase` rows record which version produced them. |
| Add a new market beyond retail | Multi-tenant the `ai_config` table (currently singleton on `key='default'`). Add `market_id` to `business_case`. Out of scope for v1. |
| Surface a new aggregate on the dashboard | Add a SQL query + response field in `routes/dashboard.py`, then a tile in `web/src/views/Dashboard.vue`. |

---

## 9. Non-Goals (deliberate omissions)

These are **not** in the architecture and adding them requires re-litigating a locked constraint:

- AI in ingest (semantic dedup, LLM summarisation of titles, etc.) — violates the AI-boundary constraint.
- Vector store / embeddings — `rapidfuzz` is the dedup ceiling for v1.
- Multi-region / HA — single-operator tool, not justified.
- Streaming LLM responses to the SPA — batch assessment with polling is sufficient.
- A separate scheduler service — Cloud Scheduler handles cadence; in compose, manual or one-shot.

---

## 10. Multi-Tenant Model (Phase 10)

**Core principle:** Topics are global; assessments are scoped per (department, framework).

### Tenancy & RBAC

| Concept | Implementation |
|---------|---------------|
| Department | `departments` table; users belong to 1+ depts via `user_departments` |
| Roles | `superadmin` (global), `dept_lead`, `analyst` — per (user, dept) |
| Active context | `X-Active-Department-Id` header selects working department |
| Auth | bcrypt + HMAC-SHA256 signed cookie; `get_current_user` + role deps |

### Assessment Frameworks

Pluggable assessment types (`assessment_frameworks` table): Verdict, SWOT, PESTLE. Each department enables a subset via `department_frameworks`. The assessor dispatches to framework-specific prompt templates and stores results in `business_cases.structured_output` (JSONB).

### Harmonization Layer

Cross-department synthesis lives in `topic_harmonizations` (one row per topic). Any authenticated user can **read** harmonizations (cross-dept visibility). Only `dept_lead+` or `superadmin` can **write** (net view authoring). The SPA renders a tabbed view: "My Department" (filtered business cases) vs "Cross-Department" (all cases + net view editor).

### Data Model Additions (Phase 10)

```
departments, user_departments, department_sources,
assessment_frameworks, department_frameworks,
topic_harmonizations
```

Migrations 0014–0020 (additive, safe to apply incrementally).

---

## 11. References

- `README.md` — quickstart, repo layout, env-var reference.
- `docs/API.md` — full HTTP API reference.
- `docs/DEPLOYMENT.md` — Cloud Run runbook, embedded-PG durability model, rollback procedures.
- `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` — original scope and phased delivery plan.
- `.planning/phases/*/` — per-phase plans and post-implementation summaries (authoritative record of how each component was built).
