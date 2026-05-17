# Deferred Items — Phase 4.5

Issues discovered during Plan 04.5-01 execution that are out of scope and
deferred to a later phase per the executor's scope-boundary rule.

## Pre-existing test failures

### test_cross_source_dedup.py — `run_once()` signature mismatch

**File:** `services/crawler/tests/test_cross_source_dedup.py:115` (and similar
sibling calls in the file).

**Error:** `TypeError: run_once() missing 1 required positional argument: 'crawl_run_repo'`

**Root cause:** Phase 3 (commit `9a2ccc8` and later) added a required
`crawl_run_repo` argument to `crawler.app.orchestrator.run_once`. The
Phase 2 cross-source dedup test file was not updated to pass it.

**Verification this is pre-existing, NOT caused by 04.5-01:** Ran
`git stash && pytest tests/test_cross_source_dedup.py` on commit `d3ad185`
(before T04) — same failure. Plan 04.5-01 only touches:
- `RawItem` (additive optional field — backward compatible)
- `SqlAlchemyTopicRepository.insert_new` / `update_existing` / `_bump_topic`
- The new `google_news_url` adapter

None of those are exercised by the failing dedup test's failure point (the
test fails inside `run_once(...)` before reaching the repository methods).

**Why deferred:** Out of 04.5-01 scope per the executor's scope-boundary
rule ("only auto-fix issues DIRECTLY caused by the current task's changes").
Fix is a 3-line test patch: update each `run_once(...)` call site in the
file to also pass a `crawl_run_repo` (likely a fake or the
`SqlAlchemyCrawlRunRepository` from the same fixture).

**Recommended follow-up:** A small `chore(tests): update cross-source-dedup
test for Phase 3 run_once signature` patch in Phase 5 or as a one-off
maintenance commit.
