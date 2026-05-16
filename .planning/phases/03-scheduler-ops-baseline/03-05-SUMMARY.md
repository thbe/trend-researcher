---
plan_id: 03-05
plan_title: scripts/smoke_phase3.sh + Phase 3 closeout
phase: 03-scheduler-ops-baseline
wave: 5
status: complete
autonomous: false
depends_on: [03-01, 03-02, 03-03, 03-04]
req_ids: [OPS-001, OPS-002, ING-001]
commits:
  - 4d39da4  # T01 scripts/smoke_phase3.sh
  - 700533e  # in-flight hot-fix: narrow uv workspace glob (skip services/scheduler)
  - ff4ede1  # T02 SMOKE-RESULTS.md (captures live 2026-05-16 smoke)
  - 57b8673  # T03 README — operator endpoints, scheduler cadence, smoke pointer
  - ed88f88  # T04 STATE + ROADMAP bumps
  - (this)   # SUMMARY commit
completed: 2026-05-16
---

## Objective

Close Phase 3 with a runnable end-to-end smoke that proves the new
operator surface — single `docker compose up` brings up the 4-service
stack (postgres + crawler + api + scheduler); a triggered crawl writes a
`crawl_runs` row; `/healthz` reports the DB; `/runs` lists the recent
crawls — and bookkeep the project state so Phase 4 can be discussed
without ambiguity about where the previous phase ended.

The phase-level 24h-unattended success criterion (#5 in ROADMAP.md) is
intentionally split: the smoke script proves the same code path runs
N times in a row (3 triggers); the long-tail observation against the
real `0 0,12 * * *` cron schedule is captured as an empty section in
`SMOKE-RESULTS.md` for the operator to fill in after the next two
scheduled tick windows. This was locked as CONTEXT.md decision D
during discuss-phase.

## Tasks

| # | Commit  | Title                                                          |
|---|---------|----------------------------------------------------------------|
| T01 | 4d39da4 | scripts/smoke_phase3.sh — 3-trigger E2E smoke (104 lines, +x)  |
| —   | 700533e | fix(03-05): narrow uv workspace glob to skip services/scheduler |
| T02 | ff4ede1 | docs(03-05-T02): capture Phase 3 smoke results (SMOKE-RESULTS.md, 144 lines) |
| T03 | 57b8673 | docs(03-05-T03): README — operator endpoints, scheduler cadence, smoke pointer |
| T04 | ed88f88 | chore(state): Phase 3 complete; Phase 4 ready to plan          |
| T05 | (gate)  | git push origin main — operator gate, no commit                |

T05 is the final non-autonomous gate. It produces no commit (the push
itself is what ships everything to the origin); SUMMARY commit count
for Plan 03-05 is therefore 5 — T01 + hot-fix + T02 + T03 + T04 + this
SUMMARY — matching the "5 task commits + 1 SUMMARY" cadence the
preceding 4 plans used.

## Key files

- `scripts/smoke_phase3.sh` (new, 104 lines, mode 0755): 17-step
  end-to-end smoke. Brings up postgres + api, applies `alembic upgrade
  head`, triggers `docker compose run --rm crawler run-once` three
  times via `--top-n 100`, asserts crawl_runs count progresses
  0→1→2→3, hits `/healthz` (expects 200 + `{status:ok,db:reachable}`),
  hits `/runs?limit=5` (expects 3 rows), counts topics with
  `observation_count >= 2`, brings up scheduler service detached and
  greps its logs for the crontab banner, prints a final summary block
  with the three `crawl_run_id`s, exits 0 on full pass. Mirrors the
  79-line `scripts/smoke_phase2.sh` pattern.
- `.planning/phases/03-scheduler-ops-baseline/SMOKE-RESULTS.md` (new,
  144 lines): TL;DR pass table, per-criterion verdict (5/5 ✓), per-
  trigger JSON (3 `crawl_run_id`s, per-source totals), `/healthz`
  body, `/runs?limit=5` body, summary table across the 3 runs,
  failed_sources table, notes section (workspace hot-fix story, the
  3 within-run Google News dupes, the 77 topics at observation_count
  >= 2, the manual CRAWLER_DISABLED_SOURCES sanity check), and an
  empty `## Post-close real-cron observation (T+24-48h)` heading the
  operator fills in after the first two scheduled tick windows.
- `README.md` (edited, +78/-10 lines):
    - Sources section: 7-row table reduced to 3-row (HN + NYT +
      Google News) reflecting the Phase 2 Reddit drop; intro updated;
      `failed_sources` description points at both the new
      `crawl_runs.failed_sources` column and the structlog field;
      pointer added to `02-multi-source-ingest/CONTEXT.md` "Reddit
      access reality". This also closes the deferred cleanup from
      Plan 03-03 T03 deviation #3 (stale Reddit content) — see
      Deviations below.
    - Quickstart restructured into a top-level Phase 3 compose-up-and-
      walk-away recipe + Operator endpoints subsection (curl examples
      for /healthz + /runs?limit=N plus a raw-SQL alternative) +
      Cadence subsection (cron line, 3-step how-to-change, pointers
      to `services/scheduler/README.md` for the docker-socket trust
      note and to `scripts/smoke_phase3.sh`). The crawler-only Phase
      2 quickstart is preserved under its own heading for operators
      who still run the crawler standalone.
- `pyproject.toml` (hot-fix 700533e): root workspace `members` glob
  `services/*` replaced with explicit list
  `["packages/core", "services/api", "services/assessor", "services/crawler"]`.
  `services/scheduler/` is alpine + crond + docker-cli only — no
  pyproject.toml — and the glob was tripping `uv lock` / `uv sync`
  during the first smoke run. uv.lock unchanged.
- `.planning/STATE.md`: frontmatter bumps (status `planning-complete`
  → `phase-complete`; completed_phases 2 → 3; completed_plans 9 →
  14; percent 38 → 58), Current Position + Session Continuity
  rewritten for the complete state. Same denominator convention
  (14/24) used through Phases 1–2.
- `.planning/ROADMAP.md`: Phase 3 checkbox ticked; Plans block
  expanded from `0/TBD` placeholder to the 5-plan list with wave
  annotations; "Phase 3 reality (post-execution)" paragraph added
  mirroring the Phase 2 convention; progress-table row updated to
  `5/5 | Complete | 2026-05-16`.

## Live smoke result (2026-05-16 10:42 UTC)

`scripts/smoke_phase3.sh` rc=0. Detailed numbers live in
`SMOKE-RESULTS.md`; the executive summary:

- **Trigger 1**: 77 inserted / 0 updated / 0 errors / failed_sources
  []. Per-source: HN 30/30, NYT 20/20, Google News 30/27 (3
  within-run dupes — title fuzzy-match).
- **Trigger 2**: 0 inserted / 77 updated / 0 errors / failed_sources [].
- **Trigger 3**: 0 inserted / 77 updated / 0 errors / failed_sources [].
- `crawl_runs` row count: 0 → 1 → 2 → 3 ✓
- `/healthz` → 200 `{"status":"ok","db":"reachable"}` ✓
- `/runs?limit=5` → 3 rows, newest-first ✓
- 77 topics at `observation_count >= 2` ✓
- `docker logs trend-scheduler` shows `[scheduler] starting crond.
  crontab:` + the loaded crontab line + `[scheduler] handing off to
  crond` ✓

## Self-check vs CONTEXT.md (Phase 3)

| Decision               | Locked in CONTEXT.md                                                             | Shipped?                                                  |
|------------------------|----------------------------------------------------------------------------------|-----------------------------------------------------------|
| A.1 cron-in-container  | alpine:3.20 + crond -f -l 8, mounted docker socket, anchored `0 0,12 * * *` UTC  | ✓ Plan 03-04                                              |
| A.2 FastAPI api shell  | /healthz + /runs?limit (default 20, ge=1 le=100, newest-first)                   | ✓ Plan 03-02                                              |
| B crawl_runs table     | One row per crawl, write at end of run_once, per_source JSONB, failed_sources text[] | ✓ Plan 03-01                                          |
| C source-disable env   | CRAWLER_DISABLED_SOURCES csv, case-insensitive, whitespace-tolerant, warn-on-unknown | ✓ Plan 03-03                                          |
| D smoke + 24h          | smoke_phase3.sh proves repeat-trigger; 24h real-cron observation = post-close PoC entry | ✓ smoke + SMOKE-RESULTS.md placeholder                |
| ARC-001 zero-AI ingest | No AI imports/calls in any Stage 1 path                                          | ✓ grep across services/crawler/ + packages/core/ clean    |

## Deviations

1. **Workspace hot-fix mid-plan (700533e).** The first smoke run died
   at step [4/17] (`docker compose build crawler`) because the root
   `pyproject.toml` `[tool.uv.workspace]` `members = ["services/*", "packages/*"]`
   was matching the new `services/scheduler/` directory (alpine + crond
   only, no pyproject.toml), and `uv lock` errored. This is a latent
   bug from Plan 03-04 that the smoke surfaced — fixed inline rather
   than dragged into a separate plan. Documented in the commit body
   and in SMOKE-RESULTS.md notes.
2. **Plan 03-03 T03 stale-Reddit deferral closed inside 03-05 T03.**
   Plan 03-03 T03 explicitly punted on rewriting the README's stale
   "7 sources" Sources block under scope discipline. The Plan 03-05
   T03 README work adds a Phase 3 operator section that would have
   directly contradicted the old intro, so the Sources block was
   updated in the same commit. Combined scope was the right call —
   shipping with the two sections out of sync for one more commit
   would have been worse than a slight scope expansion.
3. **24h-unattended observation deferred to operator post-fill.**
   Locked in CONTEXT.md decision D. SMOKE-RESULTS.md has an empty
   `## Post-close real-cron observation (T+24-48h)` section. The
   operator fills it in after the next two scheduled `0 0,12 * * *`
   tick windows (i.e. after observing at least two real cron-driven
   crawls executed by the scheduler container, not by the smoke
   script). This is a conscious split: the smoke script proves the
   code path; the long-tail proves the schedule actually fires.
4. **T05 push gate.** Per b4 workflow load: `git push origin main`
   is non-autonomous and produces no commit. The 33-commit ledger
   for Phase 3 is therefore: 28 task commits + 5 SUMMARYs = 33,
   matching the original phase budget.

## Phase 3 ledger

- Plans: 5/5 complete (03-01, 03-02, 03-03, 03-04, 03-05).
- Task commits: 28 (8 + 7 + 3 + 5 + 5).
- SUMMARY commits: 5.
- In-flight hot-fix commits: 1 (700533e).
- Plan-phase commit pre-existed on origin (8842772).
- Push status at SUMMARY-time: local main is 33 commits ahead of
  origin/main, awaiting operator-gated `git push origin main` (T05).