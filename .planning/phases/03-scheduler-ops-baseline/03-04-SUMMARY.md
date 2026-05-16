---
plan_id: 03-04
phase_id: 03-scheduler-ops-baseline
title: scheduler service (alpine + crond) + compose wiring
status: complete
req_ids: [ING-001, OPS-001]
commits:
  - hash: 33a08fb
    subject: "feat(03-04-T01): scheduler Dockerfile (alpine + crond + docker-cli)"
  - hash: a429d95
    subject: "feat(03-04-T02): scheduler crontab (12h cadence at 00:00 + 12:00 UTC)"
  - hash: 158083b
    subject: "feat(03-04-T03): scheduler entrypoint.sh (echo crontab + exec crond)"
  - hash: e8a73b9
    subject: "docs(03-04-T04): scheduler README with trust-model warning"
  - hash: 700f5dd
    subject: "feat(03-04-T05): docker-compose adds api + scheduler services"
---

## Objective

Stand up the scheduler service that fires the crawler every 12h and
wire it into `docker-compose.yml` alongside the existing postgres +
crawler and the api service shipped in Plan 03-02. After this plan,
`docker compose up -d` brings up a complete Phase 3 stack: postgres
(data), api (control plane), crawler (one-shot on demand), scheduler
(triggers crawler on cadence).

## Tasks

| # | Subject | Commit |
|---|---|---|
| T01 | scheduler Dockerfile (alpine + crond + docker-cli) | `33a08fb` |
| T02 | scheduler crontab (12h cadence at 00:00 + 12:00 UTC) | `a429d95` |
| T03 | scheduler entrypoint.sh (echo crontab + exec crond) | `158083b` |
| T04 | scheduler README with trust-model warning | `e8a73b9` |
| T05 | docker-compose adds api + scheduler services | `700f5dd` |

## Files

Created:
- `services/scheduler/Dockerfile` (alpine:3.20 + busybox-suid + docker-cli + docker-cli-compose)
- `services/scheduler/crontab` (2 non-empty lines, `0 0,12 * * *` UTC)
- `services/scheduler/entrypoint.sh` (+x, echoes banner + crontab + execs `crond -f -l 8`)
- `services/scheduler/README.md` (6 sections, includes required trust-model warning)

Modified:
- `docker-compose.yml` (added api + scheduler services; added `CRAWLER_DISABLED_SOURCES: ""` to crawler env; refreshed top comment for 4-service layout)

## Self-check vs CONTEXT.md decision A.1 (scheduler-in-container)

- [x] Base image alpine:3.20 (pinned minor).
- [x] BusyBox `crond -f -l 8` (foreground, log level info, becomes PID 1).
- [x] Crontab anchored at `0 0,12 * * *` UTC (NOT a 12h drift schedule).
- [x] Trigger: `cd /workspace && docker compose run --rm crawler run-once` against host docker socket.
- [x] Cron stdout/stderr redirected to `/proc/1/fd/1` so `docker logs trend-scheduler` shows every run.
- [x] crawler service `restart` policy still absent (Phase 1 one-shot invariant preserved).
- [x] scheduler + api services `restart: unless-stopped`.
- [x] Trust-model warning (docker socket = root on host) called out explicitly in `services/scheduler/README.md` with the do-not-deploy-multi-tenant caveat.
- [x] ARC-001 preserved: no AI in ingest path; scheduler is a deterministic trigger only.

## Plan-level acceptance — results

- `docker compose config` exit 0.
- `docker compose up -d postgres api scheduler` → all 3 containers Up; postgres Healthy.
- `curl http://localhost:8000/healthz` → 200 `{status:ok, db:reachable}`.
- `docker logs trend-scheduler` shows the startup banner, the active crontab, and `crond` running foreground.
- `docker compose down -v` cleans up cleanly.

End-to-end cron-tick-actually-writes-`crawl_runs` verification deferred to Plan 03-05 smoke (alembic upgrade + manual cron trigger + `SELECT count(*) FROM crawl_runs`).

## Deviations

1. **T01 build verification used T02/T03 file contents.** The Dockerfile COPYs `crontab` and `entrypoint.sh`, so the docker build can't succeed without them on disk. Files were written alongside T01 to allow the build to verify, then committed separately for T02 and T03 to keep each commit aligned with its narrow acceptance criterion. Documented in the T01 commit body.
2. **T05 manual `/runs` returns 500.** Operator-applied migrations are deferred per Plan 03-02; without `alembic upgrade head` the `crawl_runs` table doesn't exist and the SELECT 500s. NOT in 03-04 acceptance — full `/runs` smoke belongs to 03-05. Documented in the T05 commit body.
3. **Live end-to-end cron tick not observed.** A real 00:00/12:00 UTC tick (or a manual `sh -c 'cd /workspace && docker compose run --rm crawler run-once'` from inside the scheduler container) is a 03-05 smoke step, not a 03-04 step.

## Phase 3 decisions touched

- A.1 (cron-in-container) — fully implemented here.
- A.2 (FastAPI /healthz + /runs) — wired into compose stack; api service now reachable on :8000.
- C (CRAWLER_DISABLED_SOURCES env var) — surfaced in `docker-compose.yml` as the empty default so operators see the knob.
- D (smoke + post-close 24h observation) — still pending in 03-05.
