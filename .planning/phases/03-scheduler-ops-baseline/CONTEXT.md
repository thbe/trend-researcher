# Phase 3 — Scheduler & Ops Baseline: Context

**Status:** discussed (planning kickoff pending)
**Mode:** mvp
**Depends on:** Phase 2 (complete)
**REQ-IDs in scope:** ING-001, OPS-001, OPS-002, OPS-003

## Domain boundary

Make the crawler run itself unattended every 12h for the 1–2 month PoC observation window, with the operational surface needed to trust what it produces. **AI scope remains zero in this phase (ARC-001 hard rule).**

This phase is the moment the system stops being "operator runs `docker compose run --rm crawler` by hand" and becomes "comes up via `docker compose up`, ticks every 12h, leaves a queryable trail."

## Carrying forward (NOT re-decided in this phase)

- **ARC-001:** No AI/LLM code in any ingest path
- **ING-001:** 12h global cadence, no per-source overrides
- **OOS-008:** No per-source crawl-cadence (locked out of v1)
- **Stateless one-shot crawler:** Phase 1 architecture preserved — each cron tick runs a fresh container, exits 0
- **Phase 5 owns `crawl_config` table:** UI-editable per-source config is NOT pulled forward into Phase 3 (Phase 2 CONTEXT.md explicit)
- **Phase 2 dedup hot-fix:** `find_candidates(limit=5000)` recent-window scan stays as-is; the proper indexed `dedup_key` lookup is queued for later (operator did not select for Phase 3)
- **Reddit OAuth re-enable:** Backlog item, not in Phase 3

## Decisions locked

### A.1 Scheduler mechanism: cron-in-its-own-tiny-container

A new compose service (e.g. `scheduler`) runs an alpine + crond image with a 1-line crontab that fires `docker compose run --rm crawler` every 12h. The host docker socket is mounted into the scheduler container so it can drive `docker compose` from inside compose.

**Why:** Self-contained — `docker compose up -d` literally schedules itself. No host crontab, no systemd timer, no operator surgery on the host beyond starting compose. Works identically on the operator's laptop and any future server.

**Trade-off accepted:** Mounting the docker socket into a container is effectively root-on-host. Tolerable for a single-operator internal tool; documented in OPS notes.

### A.2 api-service shell scope: FastAPI with `/healthz` + `/runs`

The `services/api/` package becomes a real FastAPI app with two endpoints:
- `GET /healthz` — returns 200 + DB-ping result (proves the api can boot, import `packages/core`, reach Postgres)
- `GET /runs` — returns the last N rows from `crawl_runs` (operational telemetry; satisfies "did the last few crawls actually happen?" without ssh-into-host or `docker logs` scraping)

**Why:** Once `crawl_runs` exists (Area B), exposing it costs ~30 extra lines. Pays off immediately for Area D verification (`curl localhost:8000/runs | jq`) and across the 1-2 month observation window.

**Boundary preserved:** Phase 4 still owns the product topic-read API. `/runs` is operational/observability surface, separate concern.

### B Log sink: `crawl_runs` Postgres table

A new Alembic migration in `packages/core` adds a `crawl_runs` table:
- `id` (PK)
- `started_at` (timestamptz)
- `finished_at` (timestamptz)
- `totals_inserted` (int)
- `totals_updated` (int)
- `totals_errors` (int)
- `per_source` (JSONB) — mirrors orchestrator's per-source dict
- `failed_sources` (text[])

The crawler's `run_once()` writes one row per crawl-run. Existing structlog JSON output to stdout is preserved (still useful for `docker logs`).

**Why:** Queryable with SQL; composes cleanly with `/runs`; sets up Phase 9's logbook as a natural extension instead of a "migrate file logs into a table" event later. Migration cost is small.

**Boundary preserved:** This table is operational telemetry for the crawler service. It does NOT leak into `crawl_config` (Phase 5) or business-case storage (Phase 6+).

### C Runtime source-disable: `.env` edit

A new env var `CRAWLER_DISABLED_SOURCES=name1,name2` is parsed at container startup. `build_sources()` in `services/crawler/src/crawler/app/composition.py` filters out any source name in the disabled set before returning the source list to the orchestrator.

**Why:** Each crawl is already a fresh container that reads env at startup — OPS-003 is satisfied with ~10 lines and zero new infrastructure. Matches how the rest of the crawler is configured today (`DATABASE_URL`, `CRAWLER_TOP_N`, `LOG_FORMAT` are all env). Operator workflow: edit `.env` → next 12h tick uses the change.

**Boundary preserved:** Phase 5's UI-editable `crawl_config` table is NOT pulled forward. The env mechanism is the ops escape hatch; Phase 5 builds the proper UI-driven config alongside it (or supersedes it — that's a Phase 5 decision).

**Acknowledged gap:** Env vars aren't queryable from the api shell. "Which sources are enabled right now?" requires reading `.env` or `docker compose exec crawler env | grep DISABLED`. Acceptable for a single operator; Phase 5 closes the gap properly.

### D 24h-unattended verification: smoke + post-close real-cron observation

**Phase exit gate (closes Phase 3):**
- A `scripts/smoke_phase3.sh` (modeled on `scripts/smoke_phase2.sh`) that:
  1. Brings up the full stack via `docker compose up -d`
  2. Triggers 3 manual crawls in succession (`docker compose run --rm crawler`)
  3. Asserts: 3 new rows in `crawl_runs`, `observation_count` advances on at least one persistent topic across the 3 runs, `last_seen_at` advances accordingly, `/healthz` returns 200, `/runs` returns the 3 rows
- This proves the wiring end-to-end without blocking on wall-clock.

**Post-close observation (NOT a phase exit gate):**
- After Phase 3 closes, the operator manually verifies after 24-48h of real cron ticks that 2-4 cron-triggered crawls actually fired and produced `crawl_runs` rows. A one-line note is appended to a "phase 3 post-close observations" entry in the PoC observation log.
- If the real cron tick fails, opens a Phase 3.1 hot-fix.

**Why:** Avoids 24h of dead phase-close time while still producing real evidence the cron actually fires unattended. Matches the existing Phase 2 smoke pattern.

## Files expected to change

- `docker-compose.yml` — add `scheduler` service + `api` service; mount docker socket on scheduler
- `services/scheduler/` (new) — Dockerfile (alpine + crond), crontab file, README
- `services/api/src/api/` — FastAPI app, `/healthz`, `/runs` routes, Pydantic models, tests
- `services/api/Dockerfile` (new)
- `services/api/pyproject.toml` — add fastapi, uvicorn deps
- `packages/core/src/.../models.py` — `CrawlRun` SQLAlchemy model
- `packages/core/migrations/versions/...` — Alembic migration for `crawl_runs`
- `services/crawler/src/crawler/ports/crawl_run_repository_port.py` (new) — port for writing crawl_runs
- `services/crawler/src/crawler/adapters/persistence/sqlalchemy_crawl_run_repository.py` (new) — adapter
- `services/crawler/src/crawler/app/orchestrator.py` — write a `crawl_runs` row at end of `run_once()`
- `services/crawler/src/crawler/app/composition.py` — `build_sources()` reads `CRAWLER_DISABLED_SOURCES`, filters
- `services/crawler/tests/...` — unit tests for disabled-sources filter + crawl_run write
- `scripts/smoke_phase3.sh` (new)
- `README.md` — operator section: how to disable a source, how to read `/runs`, scheduler tuning

## Out of scope (explicit)

- AI / LLM / assessment work (Phase 6+)
- UI-editable per-source config (Phase 5)
- Topic-read product API (Phase 4)
- Reddit OAuth or any new source onboarding (later)
- `dedup_key`-indexed `find_candidates` replacement (deferred; not in Phase 3 REQ-IDs)
- Multi-tenancy / auth (out of v1 entirely per ARC-004)
- File rotation / log retention strategy beyond stdout (`crawl_runs` table is the durable record)

## Success criteria (mapped from ROADMAP)

1. ✅ `docker compose up` brings up Postgres + api shell + scheduler — satisfied by A.1 + A.2
2. ✅ Crawler exits 0 per run (already true; preserved by cron-triggering one-shot invocation)
3. ✅ Each crawl produces a structured per-source log record — satisfied by B (`crawl_runs` table)
4. ✅ Source can be disabled at runtime without rebuild — satisfied by C (`.env` edit)
5. ✅ 24h+ unattended observation_count + last_seen_at advance — satisfied by D smoke (phase exit) + post-close real-cron observation

## Open / deferred to planning step

- Concrete crawl-row write timing: end of `run_once()` only, or also a "started" row at start (decide in PLAN)
- Exact crontab time-of-day anchor (00:00 + 12:00 UTC vs. drift-tolerant; decide in PLAN — operator preference)
- Whether `/runs` paginates or just `LIMIT N` with default N=20 (decide in PLAN)
- Cron container base image pinning (alpine version)
