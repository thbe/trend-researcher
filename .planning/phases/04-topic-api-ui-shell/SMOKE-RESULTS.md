# Phase 4 — Smoke Results (Plan 04-05 T07)

- **Date:** 2026-05-17 17:03 UTC
- **HEAD SHA:** `7c43b93`
- **Image:** `trend-api:dev` (597 MB)
- **Mode:** local-compose (prod-image mode skipped — runs in 04-06)

## Local-compose smoke (live verification against `docker compose up -d postgres api`)

| # | Step                                                          | Result |
| - | ------------------------------------------------------------- | ------ |
| 1 | `docker compose up -d postgres api` — both Up                 | PASS   |
| 2 | `trend-postgres` healthy; `trend-api` Up 11m, port 8000 bound | PASS   |
| 3 | `GET /api/healthz` → `{"status":"ok","db":"reachable"}`       | PASS   |
| 4 | `GET /api/topics?limit=2` → JSON `topics[]`, numeric `breadth` + `longevity_seconds` | PASS |
| 5 | `GET /api/topics?sort=garbage` → HTTP **400** (G5 whitelist holds) | PASS |
| 6 | `GET /` → HTTP **200**, `content-type: text/html; charset=utf-8` (SPA served via StaticFiles) | PASS |
| 7 | `GET /api/healthz` after `GET /` → still 200 (StaticFiles mount does not shadow `/api/*`, G2) | PASS |
| 8 | `/app/.venv/bin/alembic --version` → `alembic 1.18.4` (post-hot-fix venv portable) | PASS |
| 9 | `/app/.venv/bin/uvicorn --version` → `0.47.0`                  | PASS   |
| 10 | 3 topics in DB from prior crawler runs (Supreme Court / Steve Cohen / Louisiana primaries — all google_news, observation_count=3) | PASS |

**10 / 10 local-compose PASS.**

## Prod-image mode

Skipped this gate — exercises pg_dump rotation + SIGTERM cleanup() and is owned by Plan 04-06 (first Cloud Run deploy verifies it in production). Wave 5 ships the entrypoint + script + scaffold; Wave 6 validates end-to-end against Cloud Run.

To run locally before 04-06:

```bash
SMOKE_PHASE4_PROD_IMAGE=1 ./scripts/smoke_phase4.sh
```

## T01 hot-fix call-out

Container restart-looped on first compose-up with `exit 127: cannot execute: required file not found` on `/app/.venv/bin/alembic`. Two layered bugs in the original 3-stage Dockerfile:

1. Astral `uv:python3.12-bookworm-slim` builder placed python at `/usr/local/bin/python3.12` (Debian + uv-managed), while runtime `ubuntu:24.04` has `/usr/bin/python3.12` — the venv interpreter symlink was dead on copy.
2. `uv sync` froze the absolute build-time venv path (`/build/.venv`) into console-script shebangs and editable-install `.pth` files, so even after fixing the interpreter the entry points pointed at non-existent `/build/...` paths.

**Fix (commit `7c43b93`):** replaced the astral image with `FROM ubuntu:24.04` + apt `python3.12` + `COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv` (single static binary); set `UV_PROJECT_ENVIRONMENT=/app/.venv` + `WORKDIR /app` in the builder stage so shebangs and `.pth` files bake the runtime-correct `/app` paths.

Image size unchanged (597 MB). Runtime now stable across `docker compose down && up`.

## Eyeball / DevTools (operator deferred)

Browser eyeball-test (list renders, click-to-detail, external-URL no-Referer) deferred to operator. Carried into the Phase 4 deferred-acceptance batch (items 11–13) alongside the postgres-bound batch from 04-01..04-03. Does not block Wave 5 closeout — the SPA HTML shell, `/api/topics` JSON, and StaticFiles serving are all verified above.

## Outcome

**PASS** — Wave 5 acceptance bar met. Topic API + Vuetify SPA shell + embedded-PG container + 30 s dump-debouncer middleware all live behind a single port (`:8000`). Proceeding to Wave 6 (Plan 04-06: PAT-secured `/api/internal/crawl` + delete `services/scheduler/` + `cloudbuild.yaml` + first Cloud Run deploy).
