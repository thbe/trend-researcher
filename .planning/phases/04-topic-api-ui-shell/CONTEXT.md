# Phase 4 — Topic API & UI Shell: Context

**Status:** discussed (planning kickoff pending)
**Mode:** mvp
**Depends on:** Phase 3 (complete)
**REQ-IDs in scope:** UI-001, UI-002, STO-006

## Domain boundary

Phase 4 is the moment the system stops being an operator-only CLI + Postgres
trail and becomes a thing a human opens in a browser. Two deliverables:

1. **Backend read API** for topics with cross-source `breadth` and time-window
   `longevity` computed in SQL (STO-006), exposed via the same FastAPI app
   that Phase 3 stood up (`/healthz` + `/runs` already there).
2. **Vuetify SPA shell** at `web/` showing a sortable topic list (UI-001,
   UI-002), with row links going to a minimal topic-detail view.

**AI scope remains zero in this phase (ARC-001 hard rule).** Phase 4 reads
from the same deterministic topic store Stage 1 writes; no LLM, no
embeddings, no assessment work.

## Carrying forward (NOT re-decided in this phase)

- **ARC-001:** No AI/LLM code in any read path either — the topic-read API
  does not call out to assessors / models / embeddings.
- **FastAPI shell shape** (Phase 3 03-02): lazy `_engine` / `_sessionmaker`
  singletons in `api.dependencies`, `get_session()` async-gen Depends,
  Pydantic v2 `ConfigDict(from_attributes=True)` for ORM → response models,
  `RunsListResponse`-style wrapper objects (never bare arrays), port 8000,
  `restart: unless-stopped` in compose, multi-stage uv Dockerfile.
- **/healthz + /runs** (Phase 3 03-02): keep working unchanged; Phase 4 only
  *adds* routers, never modifies existing ones.
- **Topic + TopicSource ORM** (Phase 1): no schema changes to existing
  tables. `Topic.observation_count` + `Topic.last_seen_at` are already
  denormalised; breadth + longevity stay derived per STO-006.
- **Phase 5 owns `crawl_config` + per-source UI control** — Phase 4 does
  NOT touch UI-003 / UI-004 / per-source enable+N.
- **Phase 6+ owns `business_cases`** — Phase 4 topic-detail endpoint
  reserves a future `business_cases: []` field but does NOT add it yet.
- **Phase 2 dedup hot-fix** (`find_candidates(limit=5000)`) and **Phase 3
  scheduler / crawl_runs / disabled-sources env** — all preserved as-is.
- **Reddit OAuth re-enable** — still backlog, not Phase 4.

## Decisions locked

### G1 Vuetify stack: Vuetify 3 + Vite + npm

The SPA is built with **Vuetify 3.x** on **Vue 3** with **Vite** as the
build tool and **npm** as the package manager.

**Why:** Vuetify 2.x is Vue 2 (EOL). Vite is the default Vue 3 dev/build
toolchain — fast HMR, zero config for the things we need. npm ships with
Node, no extra global tool to install on a fresh machine; pnpm/bun
optimise for things (workspaces, install speed at scale) we don't need
for one SPA. Single dev-experience opinion, locked for Phases 5/8.

**Implication for repo:** `package.json` + `package-lock.json` live in
`web/`. Node version is pinned via `web/.nvmrc` (= the Node major used in
the api Docker build stage, see G2). No root-level Node config; the uv
workspace stays Python-only.

### G2 SPA serving: FastAPI mounts `dist/` as same-origin static

The built SPA is served by the **same FastAPI process** that serves
`/api/*`. Layout:

- `GET /api/healthz`, `GET /api/runs`, `GET /api/topics`, `GET /api/topics/{id}`
  → JSON (existing routers re-prefixed under `/api`)
- `GET /*` → static file from `web/dist/` (with `html=True` so client-side
  routes fall through to `index.html`)

`api.main` mounts `StaticFiles(directory=<dist>, html=True)` at `/`
**after** all API routers are registered, so FastAPI routes always win
over the catch-all.

**Why:** One container, one origin, one URL the operator types. Kills
CORS entirely (G6). Kills the prod API-base-URL question (G8 prod).
nginx is not pulling weight for a single-operator internal tool.

**Trade-off accepted:**
- The api Docker build context widens from `services/api/` to the repo
  root so the multi-stage build can `COPY web/ /web/ && npm ci && npm run build`.
  This is the same kind of "compose-driven build context" already used by
  the scheduler service in Phase 3 (mounts docker socket — far bigger
  posture trade-off).
- The api image grows by the size of `dist/` (small — Vuetify 3 + Vue 3
  treeshakes well; expect ~500 KB to a few MB).
- Frontend changes now require an api-image rebuild. Acceptable: in dev
  the operator runs `npm run dev` against `localhost:8000` with the Vite
  proxy (see G8), so the rebuild is only at compose-up / release time.

**Migration / re-prefix note:** Phase 3 routes are currently at `/healthz`
and `/runs` (no prefix). Phase 4 moves them to `/api/healthz` and
`/api/runs` because the SPA catch-all at `/` would otherwise swallow
non-prefixed URLs. `scripts/smoke_phase3.sh` and the README endpoint
table must be updated in the same plan that introduces the prefix, and
the Phase 3 SUMMARY note about `/healthz` becoming `/api/healthz` is
added as a one-line breadcrumb.

### G3 SPA repo location: top-level `web/`

The Vuetify SPA lives at **`web/`**, sibling to `services/` and
`packages/`. Matches the architectural-shape statement already in
ROADMAP.md ("one Vuetify SPA (`web/`)"). Not under `services/` because
`services/*` is the implicit "Python service" convention (and the uv
workspace `members` list explicitly enumerates them); `web/` stays
outside the Python workspace entirely.

**Files / dirs created in this phase:**
- `web/package.json`, `web/package-lock.json`, `web/.nvmrc`
- `web/vite.config.ts`, `web/tsconfig.json`, `web/index.html`
- `web/src/main.ts`, `web/src/App.vue`, `web/src/plugins/vuetify.ts`
- `web/src/router/index.ts` (Vue Router for `/topics` + `/topics/:id`)
- `web/src/views/TopicList.vue`, `web/src/views/TopicDetail.vue`
- `web/src/api/client.ts` (tiny fetch wrapper, base URL = `""` for
  same-origin in prod, Vite proxy handles dev)
- `web/.gitignore` (`node_modules/`, `dist/`)
- `web/README.md` (dev workflow: `npm install`, `npm run dev`)

**Files NOT created:**
- No `services/web/`
- No SPA-specific Dockerfile (the api Dockerfile owns the build)
- No SPA pyproject / no uv workspace addition

### G4 Breadth & longevity: Postgres VIEW `v_topic_stats`

A new Alembic migration `0003_topic_stats_view.py` in
`packages/core/migrations/versions/` creates a read-only view:

```sql
CREATE VIEW v_topic_stats AS
SELECT
  t.id AS topic_id,
  COUNT(DISTINCT ts.source_name) AS breadth,
  EXTRACT(EPOCH FROM (t.last_seen_at - t.first_seen_at))::bigint AS longevity_seconds
FROM topics t
LEFT JOIN topic_sources ts ON ts.topic_id = t.id
GROUP BY t.id;
```

The downgrade drops the view. The view is the single SQL source of
truth for `breadth` and `longevity_seconds`; routes JOIN it, never
recompute inline.

**Why VIEW (not inline subquery, not denormalised columns):**
- STO-006 says derived not stored — denormalisation off the table.
- Reusable across Phase 4 list + detail, Phase 5 detail extensions,
  and Phase 8 subset-filter UI ("breadth ≥ 2") — write the formula
  once.
- Cheap: PG materialises on each query, but cardinality is small
  (hundreds of topics for the 1-2 month PoC). If it ever becomes a
  hot path, swap to `MATERIALIZED VIEW` with a refresh hook in a
  later phase — no schema rename, no callsite changes.
- An Alembic migration keeps the formula under version control; a
  raw inline `func.count(distinct)` in the route would be invisible
  to the migrations history.

**Longevity unit:** seconds in the database (raw int, lossless,
language-agnostic). Frontend formats to human-readable ("3d", "4h",
"12m") — that's a presentation concern, not a storage concern.

**ORM mapping:** declared as a read-only view-backed entity (or simply
queried via `text()` / `select(literal_column())` from the route — TBD
in PLAN). Either way, no `__tablename__` write path, no insert/update.

### G5 Topic-list API contract

**Endpoint:** `GET /api/topics`

**Query parameters:**
- `sort` (optional, default `-last_seen_at`) — single field with optional
  leading `-` for descending. Whitelist: `breadth`, `longevity`,
  `last_seen_at`. Anything else → HTTP 400 with a clear error body.
  (`longevity` resolves to `v_topic_stats.longevity_seconds` server-side.)
- `limit` (optional, default 20) — `Query(20, ge=1, le=100)`, exactly
  matching the Phase 3 `/runs` contract.

**No filter params in Phase 4.** Filters (`?since=`, `?source=`,
`?breadth_gte=`) are Phase 5+ scope. UI-002 only requires list + sort;
shipping the smallest contract that satisfies the success criteria
keeps Phase 4 tight and lets Phase 5/8 add filters when there's an
actual UI need.

**Response shape (mirrors `RunsListResponse`):**
```json
{
  "topics": [
    {
      "id": "uuid",
      "title": "...",
      "description": "..." | null,
      "first_seen_at": "2026-05-15T10:00:00Z",
      "last_seen_at": "2026-05-16T10:42:00Z",
      "observation_count": 3,
      "breadth": 2,
      "longevity_seconds": 88920
    }
  ],
  "limit": 20,
  "sort": "-last_seen_at"
}
```

No nested `sources` on the list endpoint (kept lean). No
`topic_metadata` on the list endpoint (kept lean). Both surface on the
detail endpoint (G7).

**`sort` echoed in the response** for the same reason `limit` is echoed
in `/runs`: operator / SPA can sanity-check what they actually got
back.

### G7 Topic detail endpoint: ship a minimal one now

**Endpoint:** `GET /api/topics/{topic_id}`

- `topic_id` is UUID (FastAPI auto-validates → 422 on malformed)
- 404 if not found
- 200 returns `TopicDetailResponse`:

```json
{
  "id": "uuid",
  "title": "...",
  "description": "..." | null,
  "first_seen_at": "...",
  "last_seen_at": "...",
  "observation_count": 3,
  "topic_metadata": { ... },
  "breadth": 2,
  "longevity_seconds": 88920,
  "sources": [
    {
      "id": "uuid",
      "source_name": "hackernews",
      "url": "https://...",
      "native_rank": 4,
      "observed_at": "..."
    }
  ]
}
```

`sources` ordered by `observed_at DESC`. No `raw_payload` on the list
projection (kept lean; can be added in Phase 5 if the detail view
needs it).

**Why ship now (not a 404 placeholder):**
- Data is already in DB, route + schema + tests are ~30 lines
- Makes UI-002 "each row links to a topic detail route" actually
  meaningful — link returns real data
- Phase 5 (UI-003) extends the same endpoint additively
  (`crawl_config` context isn't on this endpoint anyway; Phase 6+
  adds `business_cases: []`)
- Avoids "click row → 404" UX during the 1-2 month observation window

**Boundary preserved:** no `crawl_config` knowledge (Phase 5), no
`business_cases` knowledge (Phase 6+), no AI knowledge (ARC-001).

### G8 SPA → API base URL

- **Dev:** `npm run dev` runs Vite on `localhost:5173`; `vite.config.ts`
  `server.proxy` maps `/api/*` → `http://localhost:8000`. SPA code
  always calls `fetch("/api/topics")` — no env var, no hardcoded host.
- **Prod (compose):** SPA is served same-origin by FastAPI (G2), so
  `fetch("/api/topics")` resolves to the same host:port as the SPA. Same
  code path as dev. No `VITE_API_BASE_URL`, no `.env` file in `web/`.

**Why:** Single code path, no env-var bookkeeping, no "which URL is the
API at?" confusion. Falls naturally out of G2(b).

### G6 CORS: not applicable

Same-origin (G2) means the browser never makes a cross-origin request.
No CORS middleware is added to FastAPI in this phase. If a future phase
splits the SPA back out (separate nginx, dev tunnel to a remote api,
etc.) CORS gets revisited then.

## Files expected to change

**Backend (api service):**
- `services/api/src/api/main.py` — re-prefix existing routers under `/api`,
  add `topics` router, mount `StaticFiles` at `/` (last, after API routes)
- `services/api/src/api/routes/healthz.py` — prefix update only
- `services/api/src/api/routes/runs.py` — prefix update only
- `services/api/src/api/routes/topics.py` (new) — list + detail
- `services/api/src/api/schemas.py` — add `TopicResponse`,
  `TopicSourceResponse`, `TopicDetailResponse`, `TopicsListResponse`
- `services/api/src/api/dependencies.py` — likely add `WEB_DIST_DIR`
  resolver (env-aware: real path in container, missing in dev/tests)
- `services/api/tests/` — `test_topics_list.py`, `test_topics_detail.py`,
  test that `/api`-prefix routes work; integration test gated on
  `TEST_DATABASE_URL`
- `services/api/Dockerfile` — multi-stage: add a `node:<pinned>` builder
  that copies `web/`, runs `npm ci` + `npm run build`, then copies
  `web/dist/` into the runtime stage at a known path
- `services/api/pyproject.toml` — no dep change; StaticFiles is built-in

**Schema (`packages/core`):**
- `packages/core/migrations/versions/0003_topic_stats_view.py` (new) —
  CREATE/DROP VIEW `v_topic_stats`
- `packages/core/src/core/models.py` — optional: view-backed read entity
  (or routes use raw `select()` from the view; decide in PLAN)

**Frontend (`web/`, all new):**
- `web/package.json`, `web/package-lock.json`, `web/.nvmrc`,
  `web/.gitignore`
- `web/vite.config.ts` (incl. `server.proxy` for `/api`),
  `web/tsconfig.json`, `web/index.html`
- `web/src/main.ts`, `web/src/App.vue`,
  `web/src/plugins/vuetify.ts`
- `web/src/router/index.ts` (routes: `/topics`, `/topics/:id`)
- `web/src/api/client.ts`, `web/src/api/topics.ts` (typed fetch
  wrappers)
- `web/src/views/TopicList.vue` — Vuetify `v-data-table` with sort
  on breadth / longevity / last_seen, row click → detail route
- `web/src/views/TopicDetail.vue` — minimal display of detail
  endpoint's fields + sources list
- `web/src/lib/format.ts` — `formatLongevity(seconds: number): string`
  (`"3d"`, `"4h"`, `"12m"`)
- `web/README.md` (dev workflow)

**Compose / ops:**
- `docker-compose.yml` — api service may need a build-context widening
  (root context with `dockerfile: services/api/Dockerfile`) so the
  Dockerfile can `COPY web/ /web/`
- `.dockerignore` — exclude `web/node_modules`, `web/dist` from any
  service's build context
- `scripts/smoke_phase4.sh` (new) — modeled on `smoke_phase3.sh`:
  bring up compose, hit `/api/healthz`, hit `/api/topics?sort=-breadth`,
  hit `/api/topics/{id}` for one returned id, fetch `/` and assert
  HTML (SPA index) returns, asserts breadth + longevity_seconds are
  numbers
- `README.md` — operator section: "open `http://localhost:8000/` in a
  browser"; document the `/healthz` → `/api/healthz` move; document
  `npm run dev` workflow for SPA-only iteration

## Out of scope (explicit)

- Per-source enable/disable + N control UI (Phase 5, UI-004)
- Topic detail UI beyond the minimal field display (Phase 5, UI-003 polish)
- `crawl_config` table (Phase 5)
- AI / LLM / assessment / `business_cases` (Phase 6+)
- Auth / login / multi-tenancy (out of v1, ARC-004)
- CORS middleware (not needed under G2 same-origin; revisit if split)
- Filter params on `/api/topics` (Phase 5+; only sort + limit in v1 of list)
- Pagination beyond `?limit` (no offset, no cursor — single-operator scale)
- Real-time / SSE / WebSocket updates (operator hits refresh; PoC scale)
- Frontend tests (manual smoke + structure-only — adding Vitest is
  Phase 5+ if/when the SPA grows)
- `dedup_key`-indexed `find_candidates` replacement (still deferred
  from Phase 2 hot-fix; not in Phase 4 REQ-IDs)
- Materialized view for `v_topic_stats` (Phase 4 ships a regular view;
  promote later if hot)
- API versioning (`/api/v1/...`) — `/api/...` is fine for v1 single-
  operator; v2 problems are v2 problems

## Success criteria (mapped from ROADMAP)

1. ✅ Backend read API returns topics with `breadth` (cross-source count)
   and `longevity` (`longevity_seconds`, days observed derivable)
   computed via SQL, not stored — satisfied by G4 (`v_topic_stats`) + G5
   (`/api/topics` returns the fields).
2. ✅ Vuetify SPA loads the topic list and renders it as a sortable
   Vuetify data table — satisfied by G1 + G3 (`web/src/views/TopicList.vue`
   with `v-data-table`).
3. ✅ Sort by breadth, longevity, and last_seen all work and the resulting
   order matches a hand-checked SQL query — satisfied by G5 (whitelist
   + view-backed sort) + smoke script assertion.
4. ✅ Each row links to a topic detail route — satisfied by G7 (real
   `/api/topics/{id}` + `web/src/views/TopicDetail.vue`), not a 404
   placeholder.

## Open / deferred to planning step

- ORM-vs-raw-`select` for `v_topic_stats`: decide in PLAN (low-stakes,
  either works; ORM is more typesafe, raw is fewer files).
- Exact node version pin for the Dockerfile builder stage + `web/.nvmrc`
  (pick current LTS during PLAN).
- Whether the `/api`-prefix re-introduction is its own micro-plan or
  rolled into the topics-list plan (PLAN decides — leaning rolled-in,
  it's ~5 lines).
- Vuetify 3 minor pin: latest stable at time of PLAN.
- Whether `TopicList.vue` uses `v-data-table` (sync, client-side) or
  `v-data-table-server` (server-driven sort) — PLAN decides; for ≤100
  rows client-side sort against server-default order is fine, but
  server-driven keeps consistent with the API sort whitelist. Leaning
  server-driven for ≤100 rows because `sort` round-trips to the API
  cleanly.
- Whether `web/` is added to root `.gitignore`-friendly tooling (e.g.,
  Prettier config) — defer; Phase 4 ships only what UI-002 needs.

## Plan shape (target)

5 plans, each one a thin vertical slice:

1. **04-01** — Alembic `0003_topic_stats_view.py` (+ ORM read-entity
   if chosen) + unit tests for the view's SQL semantics
2. **04-02** — `/api/healthz` + `/api/runs` re-prefix + new
   `GET /api/topics` list endpoint + whitelist sort + tests
3. **04-03** — `GET /api/topics/{id}` detail endpoint + nested sources
   + tests
4. **04-04** — Vuetify SPA scaffold at `web/` (Vite + Vue 3 + Vuetify
   3 + Vue Router + `TopicList.vue` + `TopicDetail.vue` +
   `formatLongevity` + Vite proxy for dev)
5. **04-05** — api Dockerfile multi-stage with node builder +
   `StaticFiles` mount + `docker-compose.yml` build-context widening +
   `scripts/smoke_phase4.sh` + README updates + closeout SUMMARY

Each plan ends with `uv run --package api pytest -v` green (where
applicable) and a clean `git status` before commit.
