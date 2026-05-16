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

---

## Amendment — 2026-05-16 (post-plan, pre-execute)

### Trigger
Execute-phase 4 kicked off Wave 1. Operator surfaced a deployment-shape
decision during the first blocker discussion: production target is
**Google Cloud Run** with a **single all-in-one container** holding
Postgres + Python app, persistence via a **GCS volume** mounted at
`/app/data` containing rotated `pg_dump` files, and an **external Cloud
Scheduler** hitting a **PAT-secured cron API endpoint** instead of an
in-container cron loop.

I initially pushed back ("Cloud Run can't do volumes / cold start would
take minutes / you'd need Cloud SQL") — all three claims were wrong.
Operator pointed at `../food-assistant/` sibling repo which ships
exactly this pattern in production. After reading its Dockerfile,
docker-entrypoint.sh, docker-compose.yml, cloudbuild.yaml, and
scripts/pg-dump-rotate.sh I issued a correction. Pattern is proven,
well-bounded, and reusable across the operator's `*-assistant/` repos.

Operator decision (verbatim short-form): **"Do suggested"** —
A=colocated tests (`packages/core/tests/`, `services/*/tests/`),
B=adopt food-assistant pattern verbatim, C=delete scheduler service
in-phase.

### New gray areas (G9–G11)

| ID  | Area                              | Disposition                        |
| --- | --------------------------------- | ---------------------------------- |
| G9  | Dump cadence + corruption tolerance | **Defaulted to food-assistant precedent** |
| G10 | PAT secret source + rotation       | **Defaulted to GCP Secret Manager + env var** |
| G11 | Scheduler service deletion timing  | **Operator-decided: same phase**   |

### G9 — Dump cadence: 30s debounce + on-shutdown final + 3-slot ring

Mirrors `food-assistant/scripts/pg-dump-rotate.sh` + `docker-entrypoint.sh`:
- Debounced post-write dump from FastAPI background task — quiescent
  window 30 s (env `DB_DUMP_DEBOUNCE_MS=30000`). Coalesces bursts so
  one crawl-run produces one dump, not 77.
- Final dump on SIGTERM/SIGINT (entrypoint `trap cleanup`) — Cloud Run
  sends SIGTERM with 10 s grace by default; we configure 30 s grace
  (`--cpu-throttling`/`--no-cpu-throttling` + signal timeout) so the
  cleanup() has room to finish.
- Non-blocking `flock -n 9` so a stuck dump never queues another.
- 3-slot ring: `.tmp → latest → .prev` with atomic `mv` (GCS FUSE
  guarantees object-level atomicity for `mv`). Corruption tolerance:
  restore chain tries `latest → .prev → fresh schema` so one bad dump
  doesn't brick the container.
- Verification step: `pg_restore --list` is run against the staged
  dump before it's promoted, so a corrupt dump never rotates over a
  good one.

### G10 — PAT secret: GCP Secret Manager → Cloud Run env var; local .env

- Production: a single GCP Secret Manager secret `trend-internal-pat`
  is mounted as env var `TREND_INTERNAL_PAT` at Cloud Run deploy time
  via `--set-secrets=TREND_INTERNAL_PAT=trend-internal-pat:latest`.
  Rotation = update the secret + redeploy (or wait for next deploy);
  no app-side rotation logic in v1.
- Local dev: `.env` file at repo root (gitignored) sets the same
  variable. `docker-compose.yml` reads `${TREND_INTERNAL_PAT:-}` and
  passes it through. Empty/unset → the `/api/internal/crawl` endpoint
  returns 503 on any call (fail-closed, not fail-open).
- Comparison is **constant-time** (`hmac.compare_digest`) to avoid
  timing-side-channel leaks. Bearer token format: `Authorization:
  Bearer <pat>`.
- Length / format requirements documented in 04-06; operator generates
  via `python -c "import secrets; print(secrets.token_urlsafe(32))"`
  (44-char URL-safe base64).

### G11 — Scheduler service: delete in this phase

The `services/scheduler/` directory (alpine + crond + docker-cli image
+ crontab + entrypoint.sh + README.md, ~7 files, Phase 3 deliverable)
is **deleted in 04-06** as part of the same phase that introduces the
PAT-secured `/api/internal/crawl` endpoint. Reasons:
- The scheduler's only job was to fire `docker compose run --rm
  crawler run-once` every 12 h. Cloud Run replaces this with Cloud
  Scheduler → HTTPS POST → `/api/internal/crawl`.
- Keeping the local-compose cron in parallel would mean two divergent
  trigger paths — one cron-loop, one HTTP — that can drift. One trigger
  shape for both local + prod is cleaner.
- `crawl_runs` table + `GET /api/runs` (Phase 3 telemetry) are NOT
  deleted; they keep working unchanged. Telemetry shape is independent
  of trigger shape.
- Compose drops the `scheduler` service; operator triggers locally via
  `curl -H "Authorization: Bearer $TREND_INTERNAL_PAT" -X POST
  http://localhost:8000/api/internal/crawl` or, for raw bypass,
  `docker compose run --rm crawler run-once` (Typer CLI still works).
- Old uv workspace hot-fix that explicitly enumerated `members` to
  exclude `services/scheduler/` (Phase 3 700533e) is left as-is —
  enumerating the right members is the right pattern regardless of
  whether `scheduler/` exists.

### Architectural consequences carried forward

- Production Dockerfile rewritten in 04-05 around `ubuntu:24.04` runtime
  with `postgresql-16` + `postgresql-client-16` installed (instead of
  `python:3.12-slim-bookworm`). Python + uv venv copied in from a
  builder stage; web `dist/` copied in from the node builder stage
  (G1-G2 unchanged).
- A `docker-entrypoint.sh` shell script (port of food-assistant's 169
  lines, adapted: Python venv launch + Alembic upgrade + DATABASE_URL
  toggle for embedded-vs-external PG) runs on container start.
- A `scripts/pg-dump-rotate.sh` (verbatim port from food-assistant
  with `PG_DB` + dump-path env-var renames) is shipped.
- A `cloudbuild.yaml` (steal food-assistant verbatim with rename of
  service / repo / bucket / env vars) lands in 04-06.
- Local `docker-compose.yml` keeps the separate `postgres:16-alpine`
  service for dev DX (entrypoint detects `DATABASE_URL` is set → skips
  embedded PG boot — same toggle food-assistant uses).
- New FastAPI middleware `pat_auth.py` (HTTPBearer + constant-time
  compare). New route `routes/internal.py` exposing
  `POST /api/internal/crawl` (PAT-required; in-process invocation of
  `crawler.app.orchestrator.run_once` via a background task; returns
  202 with a `crawl_run_id`).
- Tests colocated under `packages/core/tests/` and `services/*/tests/`
  (uv-workspace-idiomatic; deferred decision from Wave 1 prep finally
  locked here).

### What does NOT change

- G1–G8 design contract: **fully preserved**. UI-SPEC, brand palette,
  same-origin SPA, Postgres VIEW, sort whitelist, detail-endpoint
  shape, dev-vs-prod base-URL story — all unchanged.
- 04-01 / 04-02 / 04-03 / 04-04 plan tasks: **unchanged**. Only 04-05
  is rewritten; 04-06 is added.
- ARC-001 (no AI in any read path): preserved.
  `/api/internal/crawl` is a deterministic trigger, not an AI call.
- The 04-UI-SPEC.md design contract is independent of deployment
  topology — zero changes.

### Revised plan shape (6 plans, 6 waves)

1. 04-01 — Alembic VIEW (unchanged, W1, autonomous)
2. 04-02 — list endpoint + /api/* re-prefix (unchanged, W2, autonomous)
3. 04-03 — detail endpoint (unchanged, W3, autonomous)
4. 04-04 — Vuetify SPA scaffold (unchanged, W4, autonomous)
5. 04-05 — Ubuntu+PG-16 Dockerfile + entrypoint + dump-rotate + smoke
   (REWRITTEN, W5, NOT autonomous — smoke is operator gate)
6. 04-06 — scheduler deletion + PAT middleware + /api/internal/crawl +
   cloudbuild.yaml (NEW, W6, partially autonomous — first Cloud Run
   deploy is operator gate but local PAT-tests are autonomous)

### Plan-checker self-verify on amended plans

Will be re-run inline against 04-05 (rewritten) + 04-06 (new) before
the amendment commit lands. 04-01..04-04 unchanged → prior pass holds.
