# 04-01 SUMMARY — `v_topic_stats` Postgres VIEW

**Plan:** 04-01
**Wave:** 1 of 6
**Status:** code complete; acceptance DEFERRED (postgres not running locally)
**REQ-IDs covered:** STO-006
**Commits:** `e2219ab` (T01 migration) + `bc19d5d` (T02 tests + core test scaffolding)

## What landed

- `packages/core/alembic/versions/0003_topic_stats_view.py` — Alembic
  revision 0003 (down_revision 0002). Creates read-only Postgres VIEW
  `v_topic_stats` exposing `(topic_id, breadth, longevity_seconds)` via
  `COUNT(DISTINCT topic_sources.source_name)` + `EXTRACT(EPOCH FROM
  (last_seen_at - first_seen_at))::bigint` over `topics LEFT JOIN
  topic_sources GROUP BY t.id`. COALESCE guards EXTRACT against any
  future NULL-relaxation of the timestamp columns. Downgrade `DROP VIEW
  IF EXISTS v_topic_stats;`.
- `packages/core/tests/__init__.py` (empty package marker).
- `packages/core/tests/conftest.py` — first test-fixture file inside
  `packages/core/` (Phase 1/2/3 colocated tests in consuming services).
  Mirrors `services/crawler/tests/conftest.py` verbatim: `TEST_DATABASE_URL`
  env-gating + cheap TCP probe skip, session-scoped NullPool engine,
  autouse `clean_tables` fixture. Schema bootstrap = `Base.metadata.
  create_all` + dynamic import of `0003_topic_stats_view.py` → exec
  its `_CREATE_VIEW_SQL` constant. **Single-sources the view DDL**: any
  future formula edit lands in the migration only, automatically
  exercised by these tests.
- `packages/core/tests/test_topic_stats_view.py` — 4 integration tests
  pinning the view's SQL semantics:
  1. `test_breadth_counts_distinct_source_names` — repeats don't inflate
  2. `test_breadth_is_zero_for_orphan_topic` — LEFT JOIN keeps the row
  3. `test_longevity_seconds_matches_timestamp_delta` — 90-second window
  4. `test_longevity_seconds_is_bigint_not_float` — `::bigint` cast guard

## STO-006 closure

- `topics` table schema is **unchanged**. Zero new columns. Breadth +
  longevity are derived at query time via the view, never stored.
- After this plan, `SELECT breadth, longevity_seconds FROM v_topic_stats
  WHERE topic_id = ?` is the **single SQL source of truth** for both
  numbers. 04-02 list + 04-03 detail endpoints + future Phase 5 / 8
  callers must JOIN this view; inline `func.count(distinct)` re-derivation
  in routes is rejected by code-review when 04-02 / 04-03 land.

## Acceptance status

| Acceptance criterion | Status | Notes |
|---|---|---|
| `0003_topic_stats_view.py` exists | ✅ done | committed `e2219ab` |
| `alembic upgrade head` succeeds + `\dv` lists `v_topic_stats` | ⏸ deferred | needs `docker compose up -d postgres` |
| `alembic downgrade -1` drops the view | ⏸ deferred | needs postgres |
| Re-upgrade is idempotent | ⏸ deferred | needs postgres |
| Docstring names STO-006 | ✅ done | first paragraph of module docstring |
| `test_topic_stats_view.py` exists with 4 named tests | ✅ done | committed `bc19d5d` |
| All 4 tests pass with `TEST_DATABASE_URL` set | ⏸ deferred | needs postgres + TEST_DATABASE_URL |
| Module skips cleanly when `TEST_DATABASE_URL` unset | ✅ design-verified | `pytestmark = pytest.mark.skipif(not db_available(), ...)` mirrors crawler pattern proven in Phase 1/2/3 |

## Batch operator step (to close acceptance)

```bash
docker compose up -d postgres
# wait ~2s for postgres to be ready
export TEST_DATABASE_URL="postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test"
createdb -h localhost -U trend trend_researcher_test  # one-time
uv run --package core alembic upgrade head
psql "postgresql://trend:trend@localhost:5432/trend_researcher" -c "\dv"
uv run --package core alembic downgrade -1
uv run --package core alembic upgrade head  # idempotency
uv run --package core pytest -v packages/core/tests/test_topic_stats_view.py
```

Expected: alembic exits 0 on each invocation; `\dv` shows `v_topic_stats`;
all 4 pytest cases pass (0 skips when DB reachable).

## Wave / dependency posture

- Wave 1 → Wave 2 boundary: 04-02 (list endpoint + `/api/*` re-prefix)
  consumes this view via raw `select(literal_column(...))` (decided in
  CONTEXT G4 "Open / deferred to planning" — raw `text()` preferred
  over ORM read-entity for fewer files).
- Wave 3 (04-03 detail) also consumes via the same shape.
- Waves 4–6 do not touch the view directly.

## Follow-ups / out-of-scope (carried forward)

- MATERIALIZED VIEW promotion if v_topic_stats becomes a hot path
  (CONTEXT G4 — swap is a follow-up migration with zero callsite changes).
- Phase 2 `find_candidates(limit=5000)` hot-fix still parked (Phase 2
  carry-over, unrelated to STO-006).
- Index strategy on `topic_sources(topic_id, source_name)` — Phase 1
  unique constraint already covers; no new index in this plan.
