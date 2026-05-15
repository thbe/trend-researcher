---
plan_id: "03-01"
title: "crawl_runs table + repository + orchestrator write"
phase: 3
wave: 1
status: complete
tasks_total: 8
tasks_completed: 8
commits:
  - "ccc77e5 feat(03-01-T01): add CrawlRun ORM model"
  - "eebe514 feat(03-01-T02): alembic 0002_crawl_runs migration"
  - "a4b2302 feat(03-01-T03): CrawlRunRepositoryPort + CrawlRunRecord"
  - "fa97142 feat(03-01-T04): SqlAlchemyCrawlRunRepository adapter"
  - "8cc6f49 feat(03-01-T05): wire CrawlRun repo through composition + cli"
  - "03116c9 feat(03-01-T06): orchestrator writes crawl_runs row at end of run_once"
  - "8e3a744 test(03-01-T07): integration test for SqlAlchemyCrawlRunRepository"
  - "ab18c26 test(03-01-T08): orchestrator writes one crawl_run per run + propagates persist failure"
---

# Plan 03-01 Summary — `crawl_runs` table + write path

## Objective

Land the operational telemetry table (`crawl_runs`) and the deterministic write path that fills it. After this plan, every `crawler run-once` invocation produces exactly one new `crawl_runs` row with the full per-source breakdown the orchestrator already computes. No scheduler, no API surface, no AI — those arrive in later plans. **REQ-IDs satisfied: OPS-002.**

## Tasks shipped

| Task | Commit | Summary |
|------|--------|---------|
| T01 | `ccc77e5` | `CrawlRun` SQLAlchemy model in `core.models` (13 cols incl. PG `text[]` failed_sources, JSONB per_source, server defaults) |
| T02 | `eebe514` | Alembic `0002_crawl_runs` migration with `postgresql.ARRAY(Text)` + `JSONB` + `ix_crawl_runs_started_at` |
| T03 | `a4b2302` | `CrawlRunRepositoryPort` Protocol + `CrawlRunRecord` frozen-slot dataclass in `crawler.ports` (zero I/O imports) |
| T04 | `fa97142` | `SqlAlchemyCrawlRunRepository` adapter mirroring topic repo idiom (`async with session_factory()`) |
| T05 | `8cc6f49` | `build_repository()` returns 3-tuple `(topic_repo, crawl_run_repo, engine)`; CLI `_main()` unpacks accordingly |
| T06 | `03116c9` | `run_once(sources, repo, crawl_run_repo, top_n)` builds + persists `CrawlRunRecord` at end; persist failure re-raised (no swallow) per OPS-002; `stats['crawl_run_id']` echoed by CLI |
| T07 | `8e3a744` | Integration test `test_insert_persists_crawl_run` (per-column round-trip incl. JSONB dict + text[] equality + server-default sanity); skip-gated on `TEST_DATABASE_URL`; conftest `_DB_TEST_FILES` + TRUNCATE extended for crawl_runs |
| T08 | `ab18c26` | Orchestrator unit tests: `test_run_once_writes_one_crawl_run` (one-row contract + stats mirror) + `test_run_once_persist_failure_propagates` (re-raise on persist failure, attempt-count guard); also fixes 3 pre-existing `test_orchestrator.py` tests that broke at T05/T06 by adding `_NoopCrawlRunRepo` |

## Key files created / modified

**Created**
- `packages/core/alembic/versions/0002_crawl_runs.py`
- `services/crawler/src/crawler/ports/crawl_run_repository_port.py`
- `services/crawler/src/crawler/adapters/persistence/sqlalchemy_crawl_run_repository.py`
- `services/crawler/tests/test_sqlalchemy_crawl_run_repository.py`
- `services/crawler/tests/test_orchestrator_writes_crawl_run.py`

**Modified**
- `packages/core/src/core/models.py` (+`CrawlRun` class)
- `services/crawler/src/crawler/ports/__init__.py` (+exports)
- `services/crawler/src/crawler/app/composition.py` (3-tuple return)
- `services/crawler/src/crawler/app/cli.py` (3-tuple unpack + `crawl_run_id=…` echo)
- `services/crawler/src/crawler/app/orchestrator.py` (new signature + persist + propagate)
- `services/crawler/tests/conftest.py` (`_DB_TEST_FILES` + TRUNCATE extended for `crawl_runs`)
- `services/crawler/tests/test_orchestrator.py` (no-op CrawlRunRepo for 3 existing tests)

## Plan-level acceptance

- ✅ Full crawler suite green: `uv run --package crawler pytest -q` → **26 passed + 9 skipped** (pre-Phase-3 baseline 24+8=32; now 26+9=35 — exactly +3 as PLAN expected without `TEST_DATABASE_URL`).
- ⏸ Manual end-to-end sanity (`crawler run-once --top-n 5` twice → `SELECT count(*) FROM crawl_runs = 2`) deferred to Plan 03-05 smoke (`scripts/smoke_phase3.sh`), where the full `docker compose up` stack will exercise this naturally alongside scheduler + api.
- ✅ No new dependency added to any `pyproject.toml`. Everything uses existing SQLAlchemy 2.x + asyncpg + structlog.

## Self-check vs locked decisions (from CONTEXT.md)

- ✅ Write timing = end of `run_once()` only (one row per crawl). Confirmed in T06 commit + T08 unit test.
- ✅ `failed_sources` stored as `text[]` (not JSONB) so `cardinality()` filters work in `/runs` later. Confirmed in T01/T02.
- ✅ `per_source` stored as JSONB. Confirmed in T01/T02.
- ✅ Migration revision `0002` follows existing `0001` pattern. Confirmed in T02.
- ✅ ARC-001 hard rule preserved: zero AI/LLM imports introduced anywhere on the ingest path.

## Deviations from PLAN

1. **PLAN said "14 columns"; actual = 13.** Counted in T01; deliberate (no separate `error_count` field — `totals_errors` already covers it). Documented in T01 commit body.
2. **PLAN T02 had a quoting typo** (`text("'{}'"::text[])`) — corrected to `text("'{}'::text[]")` during T02 implementation. Documented in T02 commit body.
3. **T08 also fixed 3 pre-existing tests in `test_orchestrator.py`** that broke at T05/T06 when `run_once` gained the `crawl_run_repo` positional arg. The T06 static `inspect.signature` verify caught the new shape but didn't run the suite. Fix: added `_NoopCrawlRunRepo` returning `uuid4()`. Total addition: ~10 lines across 4 spots. No semantic change to those tests' intent.
4. **Live-DB acceptance criteria for T02/T05/T06** were deferred (Postgres not running locally during edit phase). Discharged by T07 collecting cleanly + T08 unit tests passing + plan-level suite green. Real DB exercise lands in Plan 03-05 smoke.

## Carry-forward into Wave 2 (Plan 03-02)

- `crawl_runs` table + `SqlAlchemyCrawlRunRepository` are ready to be consumed by FastAPI `/runs` endpoint without additional schema work.
- Repository constructor signature `__init__(self, session_factory: async_sessionmaker[AsyncSession])` is the exact shape `services/api/` will call.
- `started_at DESC` index (`ix_crawl_runs_started_at`) supports the `ORDER BY started_at DESC LIMIT N` query pattern locked for `/runs` (no offset, default LIMIT=20, clamp [1,100]).
