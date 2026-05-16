---
plan_id: 03-02
phase: 03-scheduler-ops-baseline
title: api service shell with /healthz + /runs
status: complete
wave: 2
autonomous: true
req_ids: [OPS-001, OPS-002]
commits:
  - bd35825  # T01 pyproject
  - dcec182  # T02 app skeleton (lazy DI + schemas + main + route stubs)
  - 296315b  # T03 /healthz with DB ping
  - 64b6af5  # T04 /runs newest-first
  - b867e9b  # T05 /healthz tests
  - d1bdb4f  # T06 /runs tests
  - 5afe006  # T07 api Dockerfile
---

## Objective

Stand up the read-side `api` service shell with two operational endpoints:

- `GET /healthz` — 200 + `{status:ok, db:reachable}` happy path, 503 + `{status:degraded, db:unreachable}` when the per-request `SELECT 1` raises `DBAPIError`.
- `GET /runs` — last N `crawl_runs` rows newest-first (`?limit` default 20, clamped `[1, 100]` by FastAPI Query validation), response shape `{runs:[...], limit:N}`.

Phase 4's topic-read product API will land on top of this same FastAPI app.

## Tasks

| Task | Commit | Description |
|------|--------|-------------|
| T01 | `bd35825` | `services/api/pyproject.toml` — fastapi/uvicorn/sqlalchemy/asyncpg + pytest/pytest-asyncio/httpx dev. |
| T02 | `dcec182` | App skeleton: lazy DI (`dependencies.py`), Pydantic v2 schemas, `main.py` with lifespan, stub routers. |
| T03 | `296315b` | `routes/healthz.py` — `SELECT 1` + `DBAPIError`-aware 200/503 split. |
| T04 | `64b6af5` | `routes/runs.py` — `select(CrawlRun).order_by(started_at desc).limit(...)`, `model_validate` rows. |
| T05 | `b867e9b` | `tests/test_healthz.py` + conftest — happy-path skip-gated, error path via dependency override. |
| T06 | `d1bdb4f` | `tests/test_runs.py` — ordering + default limit (skip-gated), range validation (no DB). |
| T07 | `5afe006` | `services/api/Dockerfile` — multi-stage uv + plain python runtime, uvicorn entrypoint port 8000. |

## Key Files Created / Modified

- `services/api/pyproject.toml` — FastAPI workspace member with dev extras.
- `services/api/src/api/dependencies.py` — Lazy `_engine` / `_sessionmaker` singletons; `get_session()` per-request; `dispose_engine()` idempotent for lifespan shutdown + test resets.
- `services/api/src/api/schemas.py` — `HealthzResponse`, `RunResponse` (mirrors `crawl_runs` 1:1, `from_attributes=True`), `RunsListResponse`.
- `services/api/src/api/main.py` — `FastAPI(title='Trend Researcher API', version='0.1.0', lifespan=...)`; includes healthz + runs routers.
- `services/api/src/api/routes/{healthz,runs}.py` — endpoints.
- `services/api/tests/{__init__,conftest,test_healthz,test_runs}.py` — `db_available()` skip-gate (mirror of crawler conftest), `client()` fixture via `httpx.ASGITransport` (no port binding, no uvicorn).
- `services/api/Dockerfile` — uvicorn entrypoint.
- `packages/core/src/core/__init__.py` — extended to re-export `CrawlRun` (consistency with Topic / TopicSource public surface; consumers in api import from `core`, not `core.models` internals).

## Self-check

- `uv run --package api pytest -q` → 4 passed, 3 skipped locally (no `TEST_DATABASE_URL`); 7 passed with DB up.
- `uv run --package crawler pytest -q` → 26 passed, 9 skipped (unchanged from end of Plan 03-01, no regression from `core.__init__` export change).
- `uv run --package api python -c "from api.main import app; print(app.title)"` → `Trend Researcher API` with no `DATABASE_URL` set (proves lazy DB wiring; no top-level connection).
- `docker build -t trend-api:test -f services/api/Dockerfile .` → succeeds.
- `docker run --rm --entrypoint python trend-api:test -c "from api.main import app; print(app.title)"` → `Trend Researcher API`.

## Deviations

1. **T01 dependency-group convention.** PLAN frontmatter implied PEP 735 `[dependency-groups]`; used `[project.optional-dependencies] dev` instead, matching the existing crawler convention. Documented in T01 commit body.
2. **T02 stub routers.** PLAN listed routes/healthz.py + routes/runs.py under T03/T04 only, but `api.main` includes both routers at import time → empty `APIRouter()` stubs were written as part of T02 so the import-cleanly acceptance criterion could be verified before T03/T04 land. T03/T04 then become purely additive endpoint definitions on the existing router. Documented in T02 commit body.
3. **T02 core public surface.** Extended `packages/core/src/core/__init__.py` to re-export `CrawlRun` so api consumers import from `core`, not `core.models`. Consistent with how `Topic`/`TopicSource` are already exposed. Documented in T02 commit body.
4. **T05 unreachable-DB test.** PLAN suggested monkeypatching `core.get_settings` to an unreachable DSN. Switched to `app.dependency_overrides[get_session]` yielding a stub session whose `.execute()` raises `DBAPIError` — this exercises the route's `try/except` directly (raising inside the dependency itself surfaces as 500, wrong contract). Realistic failure mode (Postgres accepts TCP but cannot serve queries). Documented in T05 commit body.
5. **T06 range-validation test.** Same dependency-override pattern needed even for the no-DB `?limit=0/101/-1` cases, because FastAPI param validation runs in the same pass as dependency solving; without an override, `Settings()` raises `database_url required` before the 422 is produced. Documented in T06 commit body.
6. **Live-DB manual sanity deferred.** Per Phase 3 pattern (mirroring Plan 03-01 §Deviations 4), the "uvicorn starts; curl /healthz + /runs" manual check folds into the Plan 03-05 smoke step rather than being executed independently.

## Phase 3 Decisions of Record (cross-reference)

- `GET /runs` LIMIT 20 default, `?limit` clamped `[1, 100]`, no offset/cursor, `ORDER BY started_at DESC` — implemented per CONTEXT.md.
- `GET /healthz` binary contract (ok/reachable vs degraded/unreachable) — implemented per CONTEXT.md.
- DB access via `core.get_engine` + `core.get_sessionmaker` — implemented (no re-implementation in api).
- No alembic in api startup — confirmed (operator applies migrations pre-up; lifespan only disposes engine).
- ARC-001 zero-AI in ingest — preserved (api is read-only over `crawl_runs`).
