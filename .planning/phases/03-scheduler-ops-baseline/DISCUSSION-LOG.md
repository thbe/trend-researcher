# Phase 3 — Discussion Log

**Date:** 2026-05-15
**Mode:** discuss (default, no flags)
**Operator cadence:** single-letter/number replies → proceed inline-sequentially without per-step confirmation

## Areas selected

Operator selected **A B C D** from 6 surfaced gray areas (A scheduler+api shell, B log sink, C source-disable, D 24h verification). Skipped:
- **E:** Dedup-window hot-fix carry-over (`find_candidates` → indexed `dedup_key` lookup) — not in Phase 3 REQ-IDs, deferred
- **F:** Anything else — not invoked

## Q&A trail

### Area A — Scheduler + api-service shell scope

**A.1 — Scheduler mechanism**
Options: (1) cron-in-its-own-tiny-container, (2) APScheduler in api-service shell, (3) host-level cron/systemd, (4) docker-compose restart loop with sleep
Recommendation: 1
**Operator chose: 1** — cron-in-container, mounted docker socket, satisfies "single docker compose up" cleanest.

**A.2 — api-service shell scope (initial)**
Options: (1) empty container, (2) `/healthz`-only FastAPI, (3) `/healthz` + `/runs`
Recommendation: 2 (decoupled from B)
**Operator chose: 2** — `/healthz`-only baseline.

**A.2 — re-asked after B unlocked it**
Once B picked the table sink, exposing `/runs` became near-free.
Options: (1) keep `/healthz`-only, (2) upgrade to `/healthz` + `/runs`
Recommendation: 2
**Operator chose: 2** — upgraded. `/runs` is operational telemetry, not product surface; Phase 4 still owns topic reads.

### Area B — Crawl-log sink (OPS-002)

Options: (1) stdout-only, (2) JSON-lines file in mounted volume, (3) `crawl_runs` Postgres table
Recommendation: 3
**Operator chose: 3** — `crawl_runs` table via Alembic migration in packages/core. Composes with `/runs`, sets up Phase 9 logbook naturally.

### Area C — Runtime source-disable (OPS-003)

Options: (1) `.env` edit + next-run pickup, (2) mounted YAML/TOML config, (3) tiny `source_state` table
Recommendation: 1 (respects Phase 2 boundary on `crawl_config`)
**Operator chose: 1** — `CRAWLER_DISABLED_SOURCES` env var, parsed at startup, `build_sources()` filters. Phase 5 owns the UI-editable mechanism.

### Area D — 24h-unattended verification approach

Options: (1) wait 24h before phase close, (2) fast-forward smoke only, (3) both
Recommendation: 3
**Operator chose: 3** — `scripts/smoke_phase3.sh` (3 manual triggers) closes the phase; post-close real-cron observation appended to PoC observation log; Phase 3.1 hot-fix if cron tick fails.

## Boundaries reaffirmed during discussion

- ARC-001 — no AI in ingest
- ING-001 — 12h global cadence
- OOS-008 — no per-source cadence
- Phase 5 owns `crawl_config` table — NOT pulled forward
- Phase 2 `find_candidates` indexed-lookup → not in Phase 3
- Reddit OAuth → backlog
