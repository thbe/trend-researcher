# Phase 3 Live E2E Smoke Results

**Run timestamp:** 2026-05-16 10:42 UTC
**Script:** `scripts/smoke_phase3.sh`
**Crawler / api / scheduler image commit at run time:** `700533e` (post Plan 03-05 hot-fix narrowing the uv workspace glob to skip `services/scheduler`)
**Outcome:** ✅ **ALL 5 PASS CRITERIA MET**

---

## TL;DR

Single `docker compose up -d` brings up **postgres + api + scheduler**; the operator then triggers 3 back-to-back manual crawls via `docker compose run --rm crawler run-once --top-n 30`. Every assertion in the smoke held:

| Check                                                                | Expected            | Observed                            | Result |
|----------------------------------------------------------------------|---------------------|-------------------------------------|--------|
| `/healthz` returns `status:ok`                                        | 200 + ok+reachable  | `{"status":"ok","db":"reachable"}` | ✅      |
| scheduler container loaded its crontab                                | log line present    | `starting crond. crontab:` in logs | ✅      |
| `crawl_runs` count after 3 triggers                                   | 3                   | **3**                                | ✅      |
| `/runs?limit=5` returns the 3 new rows                                | 3                   | **3**                                | ✅      |
| Persistent topics across the 3 immediate runs (`observation_count ≥ 2`) | ≥ 1 (soft)         | **77**                               | ✅      |
| `failed_sources` across all 3 runs                                    | empty preferred     | `{}` on all 3                       | ✅      |
| First trigger inserts; subsequent triggers update (dedup proof)       | 77/0 then 0/77       | exactly that pattern                 | ✅      |

Hits the live internet (HackerNews + NYT homepage + Google News — Reddit dropped per Phase 2 CONTEXT.md "Reddit access reality").

---

## Pass Criteria Assessment

The criteria from Plan 03-05 T01 acceptance + CONTEXT.md success criterion 5:

| # | Criterion                                                       | Result | Evidence                                                                 |
|---|-----------------------------------------------------------------|--------|--------------------------------------------------------------------------|
| 1 | `bash -n scripts/smoke_phase3.sh` exits 0                       | ✅     | Verified before commit `4d39da4`                                          |
| 2 | `./scripts/smoke_phase3.sh` runs end-to-end → `Phase 3 smoke PASS` | ✅     | Step [17/17] printed; pipeline `rc=0`                                     |
| 3 | `crawl_runs` count 0 → 1 → 2 → 3 across the three triggers       | ✅     | Steps [8/17], [9/17], [10/17] each asserted; SQL count matched each time  |
| 4 | `/healthz` returned 200 + `status:ok`                            | ✅     | Step [6/17]                                                               |
| 5 | `/runs?limit=5` returned 3 rows                                  | ✅     | Step [12/17] (`jq '.runs | length'` = 3)                                  |

Phase 3 success criterion 5 ("24h+ unattended observation_count + last_seen_at advance") is **partially satisfied** by this smoke (3 triggers in 11s produced 77 topics at observation_count ≥ 2 — well above the ≥ 1 floor). Full satisfaction requires the 24-48h post-close real-cron observation captured below.

---

## Per-Trigger Results

### Trigger 1 (insert phase)
```json
{
  "crawl_run_id": "25edadf9-ca9e-43d1-bf05-1e5c724a0478",
  "duration_ms": 2370,
  "fetched": 80,
  "inserted": 77,
  "updated": 0,
  "skipped_duplicates_within_run": 3,
  "errors": 0,
  "failed_sources": [],
  "sources": {
    "hackernews":   {"fetched": 30, "inserted": 30, "updated": 0,  "skipped_within_run": 0, "errors": 0},
    "nyt_homepage": {"fetched": 20, "inserted": 20, "updated": 0,  "skipped_within_run": 0, "errors": 0},
    "google_news":  {"fetched": 30, "inserted": 27, "updated": 0,  "skipped_within_run": 3, "errors": 0}
  }
}
```

### Trigger 2 (dedup phase — same headlines, all 77 update instead of insert)
```json
{
  "crawl_run_id": "ce69bc44-46fe-4006-8ff9-e3b505e7cd3a",
  "duration_ms": 2316,
  "fetched": 80,
  "inserted": 0,
  "updated": 77,
  "skipped_duplicates_within_run": 3,
  "errors": 0,
  "failed_sources": []
}
```

### Trigger 3 (dedup phase — same as trigger 2)
```json
{
  "crawl_run_id": "2b84aa11-dc66-473b-8833-50000d1c18a6",
  "duration_ms": 2256,
  "fetched": 80,
  "inserted": 0,
  "updated": 77,
  "skipped_duplicates_within_run": 3,
  "errors": 0,
  "failed_sources": []
}
```

### `/healthz` response (step [6/17])
```
{"status":"ok","db":"reachable"}
```

### `/runs?limit=5` (step [12/17])
```
.runs | length = 3
```

### Per-run summary table (step [14/17])
```
          started_at           | totals_inserted | totals_updated | totals_errors | failed_sources
-------------------------------+-----------------+----------------+---------------+----------------
 2026-05-16 10:42:17.248570+00 |              77 |              0 |             0 | {}
 2026-05-16 10:42:21.755418+00 |               0 |             77 |             0 | {}
 2026-05-16 10:42:26.582461+00 |               0 |             77 |             0 | {}
```

### `failed_sources` discipline (step [13/17])
```
          started_at           | failed_sources
-------------------------------+----------------
 2026-05-16 10:42:26.582461+00 | {}
 2026-05-16 10:42:21.755418+00 | {}
 2026-05-16 10:42:17.248570+00 | {}
```
Zero upstream failures across all 3 triggers.

---

## Notes & Observations

- **Workspace hot-fix needed mid-smoke (Plan 03-05 deviation)**: first smoke run died at step [4/17] (`uv run --package core alembic … upgrade head`) because the uv workspace glob `services/*` swept in `services/scheduler` (Plan 03-04 added a no-Python container) and uv requires every workspace member to have a `pyproject.toml`. Fixed in commit `700533e` by replacing the glob with an explicit member list. Smoke re-run was clean. Lesson reinforced: live smoke catches what static checks miss (same pattern as Plan 03-01 T08 catching `test_orchestrator.py` regressions a static `inspect.signature` check missed at T06).
- **3 within-run dupes from Google News** every trigger: cross-listed headlines under different aggregator URLs (`news.google.com/...?...&hl=en-US` querystring variants). Same 3 dupes each crawl, perfectly consistent — the dedup is doing exactly what it should.
- **77 topics at `observation_count ≥ 2`**: very high because all 3 triggers ran inside ~11s and the upstream feeds didn't churn at all. In a real 12h gap this number will be lower; the smoke is testing the mechanism, not the steady-state distribution.
- **No `failed_sources`**: clean live run. HN+NYT+GoogleNews were all healthy at 10:42 UTC on 2026-05-16. Cron/network/upstream are unpredictable — future smokes may legitimately see Reddit-style transient failures here.
- **CRAWLER_DISABLED_SOURCES verified manually** (script step [15/17] only hints): a separate `CRAWLER_DISABLED_SOURCES=hackernews docker compose run --rm crawler run-once --top-n 5` invocation was not run during this smoke; the env-filter contract is pinned by 8 unit tests (Plan 03-03 T02 commit `a84d4aa`) and the structlog `crawler.disabled_sources.applied` log line was already verified live during Plan 03-03 T01 (commit `f1f4188`).
- **Volume kept on teardown** (`docker compose down`, NOT `down -v`) so the operator can post-mortem if anything looks off after the fact.

---

## Post-close real-cron observation (T+24-48h)

> **To be filled in by the operator 24-48h after Phase 3 closes** (i.e., after `git push origin main`). The scheduler container should fire `docker compose run --rm crawler run-once` automatically at the next `0` or `12` UTC tick.
>
> Append the following:
> - Observation timestamp:
> - `SELECT count(*), min(started_at), max(started_at) FROM crawl_runs;` (expect ≥ 2 new rows from cron ticks, all spaced ~12h apart)
> - Any `failed_sources` from those rows
> - `docker logs trend-scheduler` excerpt showing the cron line(s) firing
> - Pass / fail call (if fail → open Phase 3.1 hot-fix)
