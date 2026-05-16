# Phase 4 — Discussion Log

**Phase:** 04-topic-api-ui-shell
**Date:** 2026-05-16
**Mode:** discuss (single-operator, MVP_MODE=true)
**REQ-IDs in scope:** UI-001, UI-002, STO-006

## Gray areas surfaced

Eight candidate areas identified during scout:

| ID | Area                                        | Disposition                       |
| -- | ------------------------------------------- | --------------------------------- |
| G1 | Vuetify stack (version, bundler, pkg mgr)   | Defaulted (operator: no opinion)  |
| G2 | SPA serving model (nginx / fastapi / dev)   | **Operator-decided**              |
| G3 | SPA repo location (`web/` vs `services/web/`) | Defaulted (operator: no opinion)  |
| G4 | Breadth & longevity compute strategy        | **Operator-decided**              |
| G5 | Topic-list API contract                     | **Operator: take recommendation** |
| G6 | CORS                                        | N/A (killed by G2 decision)       |
| G7 | Topic detail placeholder shape              | **Operator: take recommendation** |
| G8 | API base URL story                          | Defaulted (operator: no opinion)  |

## Decisions

### G1 — Vuetify 3 + Vite + npm (defaulted)
Operator declined to dig in; defaulted to the lowest-friction Vue 3
ecosystem stack. Vuetify 2.x is Vue 2 (EOL), so 3.x is the only real
option. Vite is the default Vue 3 toolchain. npm ships with Node.

### G2 — FastAPI serves `dist/` same-origin (operator pick: option b)
> "G2 is b."

Operator chose option (b): FastAPI mounts `web/dist/` as static files
behind a `/` catch-all (with `html=True` for SPA route fallback). API
routes move to `/api/*` prefix so the catch-all doesn't swallow them.

Consequences accepted in the same decision:
- Kills CORS entirely (G6 → N/A)
- Kills the prod API-base-URL question (G8 prod → empty)
- api Docker build context widens to repo root so the Dockerfile can
  `COPY web/` and build the SPA in a node multi-stage
- `/healthz` and `/runs` from Phase 3 become `/api/healthz` and
  `/api/runs` — breadcrumb noted in CONTEXT.md, smoke + README updated
  in the same plan that introduces the prefix
- One container, one origin, one URL the operator types in the browser

### G3 — `web/` top-level (defaulted)
Operator declined to dig in; defaulted to the location already named in
ROADMAP.md "Architectural shape" section. `services/web/` would have
been the alternative but `services/*` is the implicit Python-service
convention (uv workspace `members`).

### G4 — Postgres VIEW `v_topic_stats` via Alembic (operator pick: option a)
> "G4 should be a view."

Operator chose option (a): a real `CREATE VIEW v_topic_stats AS ...`
shipped via a new Alembic migration (`0003_topic_stats_view.py` in
`packages/core/migrations/versions/`).

View columns: `topic_id`, `breadth`, `longevity_seconds`.

**Sub-decision (longevity unit):**
Operator confirmed:
> "In the DB it could be seconds, in the frontend it should be human
> readable."

→ DB stores `longevity_seconds` (raw `EXTRACT(EPOCH FROM ...)::bigint`).
Frontend has a `formatLongevity(seconds): string` helper rendering "3d",
"4h", "12m". Storage is lossless and language-agnostic; presentation is
a presentation concern.

Reusable for Phase 5 detail extensions and Phase 8 assessment subset
filters ("breadth ≥ 2"). One formula, one migration, one source of
truth.

### G5 — Recommendation accepted (operator delegated)
> "I don't have an opinion on G5, what is the recommendation?"

Recommendation accepted by silence on the followup. Locked:

- **Endpoint:** `GET /api/topics`
- **Sort:** single `?sort=` param with leading `-` for desc.
  Whitelist `breadth`, `longevity`, `last_seen_at`. Default
  `-last_seen_at`. Anything else → HTTP 400.
- **Pagination:** `?limit=20` default, `Query(20, ge=1, le=100)` —
  exactly mirrors `/runs` to keep one pagination idiom across the API.
- **Filters:** none in Phase 4. Pushed to Phase 5+ when the UI actually
  wants them. UI-002 only requires list + sort.
- **Response shape:** wrapper object `{topics: [...], limit: N, sort: "..."}` —
  mirrors `RunsListResponse` (Phase 3 locked-in idiom: never bare arrays;
  leaves room for `next_cursor` / `total` later).
- **Row fields:** `id, title, description, first_seen_at, last_seen_at,
  observation_count, breadth, longevity_seconds`. No nested sources, no
  `topic_metadata` — those live on the detail endpoint.

### G6 — N/A (consequence of G2)
Same-origin means no cross-origin request, so no CORS middleware in
Phase 4. Revisit if a future phase splits the SPA back out.

### G7 — Recommendation accepted (operator delegated)
> "Same for G7."

Recommendation accepted: **ship a minimal `GET /api/topics/{id}` now**
(option c), not a 404 placeholder.

- `topic_id` UUID, FastAPI auto-validates (422 on malformed)
- 404 if topic not found
- 200 returns: list-endpoint fields + `topic_metadata` + nested
  `sources` (ordered `observed_at DESC`, fields:
  `id, source_name, url, native_rank, observed_at`)
- Reuses `v_topic_stats` from G4 for breadth + longevity_seconds
- Phase 5 extends this endpoint additively (no rewrite); Phase 6+ adds
  a future `business_cases: []` field

Rationale: ~30 LoC, data already exists, avoids "click row → 404" UX
during the 1-2 month PoC observation window.

### G8 — Vite proxy dev + same-origin prod (defaulted)
Operator declined to dig in; defaulted to the natural consequence of
G2. SPA code always calls `fetch("/api/...")`. In dev, Vite's
`server.proxy` maps `/api/*` → `http://localhost:8000`. In prod,
same-origin (G2) makes it Just Work. No env var, no `VITE_API_BASE_URL`,
no `.env` in `web/`.

## Plan-count agreement

Operator confirmed:
> "Ok for 2."

→ Phase 4 plans around **5 plans**:

1. 04-01 — Alembic 0003 `v_topic_stats` view + unit tests
2. 04-02 — `/api/*` re-prefix + `GET /api/topics` list endpoint + tests
3. 04-03 — `GET /api/topics/{id}` detail endpoint + tests
4. 04-04 — Vuetify 3 SPA scaffold (`web/`) with TopicList + TopicDetail
   + Vite proxy
5. 04-05 — api Dockerfile multi-stage (node + Python) + StaticFiles
   mount + compose build-context widening + `scripts/smoke_phase4.sh` +
   README + closeout

## Anti-patterns checked

- **No AI in this phase:** ARC-001 reinforced; read API is pure SQL +
  Pydantic, no LLM / embeddings / assessor calls.
- **No Phase 5 pull-forward:** explicitly out of scope — no
  `crawl_config`, no enable/N control UI, no per-source toggles.
- **No Phase 6+ pull-forward:** no `business_cases`, no
  `assessment_jobs`, no AI runtime in api Dockerfile.
- **No schema denormalisation for breadth/longevity:** STO-006 honoured
  via VIEW (G4).
- **No bare-array JSON responses:** wrapper objects per Phase 3 idiom.
- **No new dependency on `services/` glob in uv workspace:** `web/` is
  outside the Python workspace entirely.

## Open / deferred (to PLAN step)

- ORM read-entity vs raw `select()` for `v_topic_stats` (low-stakes)
- Node LTS version pin for Dockerfile builder + `web/.nvmrc`
- Whether `/api` re-prefix is folded into 04-02 (leaning yes)
- Vuetify 3 minor version pin (latest stable at PLAN time)
- `v-data-table` client-side vs `v-data-table-server` server-driven
  (leaning server-driven for clean API-sort round-trip)
- Frontend test framework (Vitest) — deferred; Phase 5+ if SPA grows
