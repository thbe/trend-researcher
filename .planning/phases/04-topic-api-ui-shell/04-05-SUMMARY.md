# Plan 04-05 — Production Container + StaticFiles + Dump Rotation — SUMMARY

**Wave:** 5 of 6 (Phase 4)
**Status:** ✅ Complete
**HEAD at closeout:** `4b3213f`
**Image artifact:** `trend-api:dev` — **597 MB**

## Task table

| #   | Task                                                                | Commit    | Autonomous | Notes |
| --- | ------------------------------------------------------------------- | --------- | ---------- | ----- |
| T01 | `services/api/Dockerfile` 3-stage rewrite                           | `c35d550` | yes        | node:20-alpine web → uv python → ubuntu:24.04 + pg-16 runtime |
| T01.fix | venv portability hot-fix (operator-gate discovery)              | `7c43b93` | yes        | ubuntu:24.04 builder + uv binary copy + `UV_PROJECT_ENVIRONMENT=/app/.venv` + `WORKDIR /app`; see below |
| T02 | `docker-entrypoint.sh` + verbatim `scripts/pg-dump-rotate.sh`       | `fd15430` | yes        | Embedded PG boot, restore chain, SIGTERM cleanup w/ final dump |
| T03 | `DumpDebouncer` middleware + `StaticFiles` SPA mount in `main.py`   | `c31c8a2` | yes        | Mount LAST after `/api/*` routers per G2; 30 s default debounce |
| T04 | `.dockerignore` + compose `appdata` volume + `stop_grace_period: 30s` | `991e4a1` | yes        | Scheduler service untouched (deletion is 04-06 T06) |
| T05 | DB-free tests: 5 dump-debouncer + 2 static-mount                    | `700019d` | yes        | api suite: **19 passed, 17 skipped** (no regression vs prior 12) |
| T06 | `scripts/smoke_phase4.sh` (10 local + 5+ prod-image opt-in)         | `b755650` | yes        | `bash -n` clean, chmod +x, prod-image gated on `SMOKE_PHASE4_PROD_IMAGE=1` |
| T07 | Operator-gate smoke + `SMOKE-RESULTS.md`                            | `4b3213f` | **no**     | **10/10 local-compose PASS**; prod-image deferred to 04-06; eyeball-test items 11–13 deferred |
| T08 | README updates + this SUMMARY                                       | (this commit) | yes    | Open the UI, frontend pointer, container persistence section |

## Acceptance gates (Wave 5)

| Gate                                                  | Result |
| ----------------------------------------------------- | ------ |
| Image builds cleanly (`docker compose build api`)     | PASS — 597 MB |
| Container boots stable across `down && up`            | PASS (after T01 hot-fix) |
| `GET /api/healthz` → `{"status":"ok"}`                | PASS   |
| `GET /api/topics` returns numeric breadth + longevity | PASS   |
| `GET /api/topics?sort=garbage` → 400                  | PASS (G5 holds) |
| `GET /` → 200 + `text/html` SPA shell                 | PASS   |
| `/api/*` not shadowed by StaticFiles                  | PASS (mount ordering G2) |
| 30 s dump debouncer middleware: env-off skips, env-on schedules + coalesces | PASS (5 DB-free tests) |
| Final-dump-on-SIGTERM ordering correct                | PASS (manual review of `cleanup()` trap) |
| `pg-dump-rotate.sh` verbatim from food-assistant      | PASS (`grep -c '^#'` = 31) |
| api pytest suite                                      | PASS — 19 passed, 17 skipped (DB-gated) |

## CONTEXT.md decision recap

- **G1** stack (Python + FastAPI + Vuetify + uv workspace) — preserved.
- **G2** mount ordering: `/api/*` routers → middleware → `StaticFiles("/")` LAST — implemented in `services/api/src/api/main.py`.
- **G3** sort whitelist (`breadth`, `longevity`, `last_seen_at`) — carried from 04-02, smoke step #5 reverifies 400 on garbage.
- **G4** nested sources on detail only — carried from 04-03.
- **G5** topic metadata as opaque JSONB — carried from 04-03.
- **G6** UI thbe palette (#EF233C primary) — carried from 04-04.
- **G7** detail surface (sources + raw metadata accordion) — carried from 04-04.
- **G8** same-origin SPA fetch (no CORS, no client auth) — verified live (`GET /` and `GET /api/*` share `:8000`).
- **G9** dump cadence + corruption tolerance — **implemented this wave**: 30 s debounce + on-shutdown final dump + 3-slot ring rotation in `pg-dump-rotate.sh` + `pg_restore --list` verify + `flock -n 9` lock + restore chain `latest → .prev → fresh`.
- **G10** PAT auth on internal endpoints — **deferred to 04-06** (no internal write endpoints exist yet; 04-06 adds `/api/internal/crawl`).
- **G11** scheduler removal — **deferred to 04-06** (compose `scheduler:` block intentionally left in place this wave; 04-06 T06 deletes the entire `services/scheduler/` tree).

## REQ coverage

| REQ ID  | Status | Notes |
| ------- | ------ | ----- |
| UI-001  | ✅      | Vuetify SPA served from container at `/`, list + detail views live |
| STO-006 | ✅      | Topic store (`topics` + `topic_sources` + `topic_metadata` + `v_topic_stats`) fully behind read API, durable across container restarts via `appdata` volume + dump rotation |

## T01 hot-fix call-out (transparency)

The original T01 Dockerfile used the astral `uv:python3.12-bookworm-slim` builder image, which placed python at `/usr/local/bin/python3.12` (Debian + uv-managed); the runtime ubuntu:24.04 has python at `/usr/bin/python3.12`. The venv interpreter symlink was dead on copy, and uv had additionally baked the absolute build-time path (`/build/.venv`) into console-script shebangs and editable-install `.pth` files. Container restart-looped exit 127 on `/app/.venv/bin/alembic`.

**Fix (commit `7c43b93`):** replaced the builder base with `FROM ubuntu:24.04` + apt `python3.12` + `COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv` (single static binary). Set `UV_PROJECT_ENVIRONMENT=/app/.venv` and `WORKDIR /app` in the builder so all shebangs and `.pth` files bake the runtime-correct `/app` paths. Image size unchanged.

Lesson captured for 04-06 / Cloud Run: do not mix builder/runtime Linux distros when shipping a uv-managed venv. Always either (a) match the distro across stages, or (b) materialise the venv at the final runtime path during build.

## Follow-ups (carry-forward to 04-06 and beyond)

1. **Wave 6 (Plan 04-06)** — adds PAT-secured `POST /api/internal/crawl` (closes G10), deletes `services/scheduler/` + the compose `scheduler:` block (closes G11), wires `cloudbuild.yaml` for Artifact Registry + Cloud Run deploy, externalizes scheduling to Cloud Scheduler. **Operator gate at T09** = first Cloud Run deploy + smoke against the live URL.
2. **Phase 4.5 (new discuss-phase, after Phase 4 verifier closes)** — capture description/snippet from existing feed payloads (Google News RSS `<description>`, NYT homepage standfirst — both already in fetched bytes, just discarded by Phase 2 parsers); resolve Google News redirect URLs to publisher domain. Triggered by operator feedback at end of Wave 5 ("I can only see the headline, isn't there more context available for analysis?"). No new HTTP fetches required; ARC-001 (no AI) preserved.
3. **Deferred-acceptance batch (13 items)** still open — postgres-bound test runs from 04-01..04-03 (items 1–10) + SPA visual smoke items 11–13. Will be cleared at Phase 4 verifier closeout after 04-06 ships.

## Files touched (Wave 5)

| File                                                                | Lines    | Status |
| ------------------------------------------------------------------- | -------- | ------ |
| `services/api/Dockerfile`                                           | 135      | rewritten T01 + T01.fix |
| `services/api/docker-entrypoint.sh`                                 | 188      | new    |
| `services/api/src/api/main.py`                                      | 66       | +21 (middleware + StaticFiles mount) |
| `services/api/src/api/dependencies.py`                              | 79       | +17 (`get_web_dist_dir`) |
| `services/api/src/api/middleware/__init__.py`                       | 1        | new    |
| `services/api/src/api/middleware/dump_debouncer.py`                 | 115      | new    |
| `services/api/tests/test_dump_debouncer.py`                         | 135      | new (5 tests) |
| `services/api/tests/test_static_mount.py`                           | 80       | new (2 tests) |
| `scripts/pg-dump-rotate.sh`                                         | 72       | new (verbatim from food-assistant) |
| `scripts/smoke_phase4.sh`                                           | 172      | new    |
| `.dockerignore`                                                     | 30       | new    |
| `docker-compose.yml`                                                | +volumes/stop_grace_period | edit |
| `web/.gitignore`                                                    | 5        | +1 (`*.tsbuildinfo`) |
| `README.md`                                                         | +Open the UI + persistence section | edit |
| `.planning/phases/04-topic-api-ui-shell/SMOKE-RESULTS.md`           | 52       | new (T07 artifact) |
| `.planning/phases/04-topic-api-ui-shell/04-05-SUMMARY.md`           | (this)   | new    |
