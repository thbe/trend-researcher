---
plan_id: "03-03"
title: "CRAWLER_DISABLED_SOURCES env filter"
wave: 3
status: complete
commits:
  - "f1f4188  feat(03-03-T01): build_sources filters by CRAWLER_DISABLED_SOURCES env"
  - "a84d4aa  test(03-03-T02): CRAWLER_DISABLED_SOURCES filter — 8 unit tests"
  - "a6e377a  docs(03-03-T03): README — how to disable a source via env var"
---

# Plan 03-03 Summary — Source-disable via `CRAWLER_DISABLED_SOURCES` env

## Objective

Give the operator a no-rebuild, no-redeploy escape hatch for skipping a source at the next 12h tick by listing its name in a `CRAWLER_DISABLED_SOURCES` env variable. Satisfies **OPS-003**. Phase 5's UI-driven `crawl_config` table remains the proper long-term mechanism; this is the ops escape hatch alongside it.

## Tasks

| Task    | Commit    | Description                                         |
| ------- | --------- | --------------------------------------------------- |
| **T01** | `f1f4188` | Env-driven filter in `build_sources()`              |
| **T02** | `a84d4aa` | 8 unit tests (PLAN spec'd 7; shipped 8 — see below) |
| **T03** | `a6e377a` | README operator subsection                          |

## Files changed

- `services/crawler/src/crawler/app/composition.py` — module-level structlog logger, `_parse_disabled_sources()` helper, filter block in `build_sources()`, docstring updated.
- `services/crawler/tests/test_composition_disabled_sources.py` (new) — 8 pure-unit tests.
- `README.md` — new "### Disabling a source at runtime" subsection under Sources.

## Self-check vs. Phase 3 CONTEXT.md decision C

- ✅ Var name `CRAWLER_DISABLED_SOURCES` matches the `CRAWLER_*` prefix convention.
- ✅ Csv format, whitespace-trimmed, case-insensitive vs `source.name`.
- ✅ Empty / unset value ⇒ no filter applied.
- ✅ Unknown names log `crawler.disabled_sources.unknown` warning, do **not** raise (operator typos stay visible without breaking unattended cadence).
- ✅ All-disabled returns `[]`; orchestrator runs to completion and writes a zero-totals `crawl_runs` row with `failed_sources=[]`.
- ✅ ARC-001 preserved — zero AI/LLM in the ingest path.
- ✅ Phase 5 owns `crawl_config` table (not pulled forward).

## Deviations

1. **Test count: 8 instead of 7.** PLAN listed 7 tests in T02 spec; shipped 8 by keeping `test_empty_string_treated_as_unset` (PLAN T02 body mentions empty-string handling in the locked decisions section, so adding the test is in-scope; commit subject explicitly says "8 unit tests" rather than the PLAN's "7"). Justification documented in T02 commit body.
2. **structlog testing harness chosen over `caplog`.** PLAN T02 spec said "use `caplog` (or structlog testing harness)". Picked `structlog.testing.capture_logs()` because structlog isn't configured to bridge to stdlib `logging` in the crawler app, so `caplog` would have caught nothing. First structlog assertion in the suite — established the pattern here.
3. **README stale Reddit content not fixed.** Lines 19 + 24–27 of `README.md` still reference the 4 Reddit sources dropped in Plan 02-04, and the "7 sources" count is wrong (actual is 3). T03 scope was strictly "add a new subsection per PLAN"; widening to a doc-hygiene sweep would have crossed plan boundaries. Filing as a Phase 2 closeout follow-up rather than carrying it inside Phase 3.
4. **Live manual sanity deferred.** `CRAWLER_DISABLED_SOURCES=hackernews,google_news docker compose run --rm crawler run-once --top-n 5` (verifying a real `crawl_runs` row with only `nyt_homepage` in `per_source`) is deferred to Plan 03-05 smoke, per established Phase 3 pattern (03-01 and 03-02 followed the same).

## Plan-level acceptance

- ✅ `uv run --package crawler pytest -q` → **34 passed, 9 skipped** (was 26+9 pre-plan; +8 from T02). No regression.
- ✅ T01 import-time smoke: `build_sources()` with env unset returns 3 sources; with `CRAWLER_DISABLED_SOURCES='HackerNews, google_news, reddit'` returns only `nyt_homepage`, warns on `reddit`, logs applied set.
- ✅ T03 `grep -c "CRAWLER_DISABLED_SOURCES" README.md` ⇒ 3 (≥ 2).
- ⏸ Live `docker compose run` manual verification deferred to 03-05 smoke.

## Notes

- This plan touched only the crawler service. The api service (Plan 03-02) does not currently report the active disabled set on `/healthz` or expose it on `/runs`; that's the acknowledged CONTEXT-decision-C gap and belongs to Phase 5.
- The filter is applied in `build_sources()` rather than the orchestrator so the orchestrator sees a list that already reflects operator intent — no orchestrator awareness of the env var, smaller blast radius.
