# Session: 2026-05-28 — Phase 10 Plan 10-04 (Frontend Multi-Tenant SPA Shell) Complete

## Summary

Finished **Phase 10 Plan 10-04** — the frontend multi-tenant SPA shell. All
8 tasks (T01–T08) committed locally. **9 commits ahead of `origin/main`,
NOT yet pushed** — awaiting operator gate.

In the process of writing the T08 test suite, uncovered a real
pre-existing bug introduced by T04 (`63cfb10`): the prop name `case` is a
JS reserved word and Vue's SFC template compiler rejects
`{{ case.x }}` interpolations even though `vue-tsc` accepts them. `vite
build` was broken on `main`. Fix: rename `case` → `bcase` across all
framework cards and the TopicDetail call site, shipped as part of the
T08 commit.

Project progress: **31 / 32 plans (97 %)**. Only Plan **10-05**
(harmonization + closeout) remains.

## Picking up on another host

```bash
git fetch origin
git checkout main && git pull
cd web && npm ci
npm run typecheck && npm test && npm run build   # all should be green
```

Resume from `.planning/phases/10-multi-tenant-platform/10-05-PLAN.md`.

Operator gates still open from this session:

1. **Push?** 9 unpushed commits on `main` (10-04 T01–T08 + STATE/ROADMAP
   docs commit). Not pushed without explicit go-ahead.
2. **Backend bugs noted but not fixed** (carry to 10-05 or quick-fix):
   - `test_dashboard_counts_isolated` likely broken — `BusinessCase`
     insert missing `framework_id` after 10-03 schema changes.
   - `api/routes/assessment.py::_build_pipeline` reads
     `request_timeout_seconds` but the pipeline ctor does not accept it.

## Commits (this session, all on `main`, unpushed)

```
780fd8e docs(phase10): mark plan 10-04 complete (31/32 plans, 97%)
2fcc3fa test(web): add vitest harness + suite for session/switcher/swot (10-04 T08)
b71e19f feat(web): multi-tenant router guards + UI toast store (10-04 T07)
d7d95fd feat(web): rewire core views for multi-tenant context (10-04 T06)
f32ef64 feat(web): per-department settings views (10-04 T05)
63cfb10 feat(web): framework cards + picker for business case display (10-04 T04)
df61581 feat(web): shell components — AppBar, NavDrawer, DepartmentSwitcher (10-04 T03)
a315dc5 feat(web): add Pinia stores for session and frameworks (10-04 T02)
27d18b2 feat(web): pinia + openapi codegen tooling (plan 10-04 T01)
---- origin/main ----
f6d5fd9 docs(phase10): mark plan 10-03 complete
```

## Per-task breakdown

| Task | Commit | What landed |
|------|--------|-------------|
| T01  | `27d18b2` | Add `pinia`, `openapi-typescript`, codegen npm script. |
| T02  | `a315dc5` | `web/src/stores/session.ts` (RBAC matrix, hydrate liveness probe, `switchDepartment`), `frameworks.ts`, `web/src/lib/roles.ts`, `client.ts` auto-injection of `X-Active-Department`. |
| T03  | `df61581` | `strings.ts` (rename hook for G8 deferred rename), `AppBar`, `NavDrawer`, `DepartmentSwitcher`, restructured `App.vue`. |
| T04  | `63cfb10` | `VerdictCard`, `SwotCard`, `PestleCard`, `BusinessCaseCard` dispatcher, `FrameworkPicker`. **Shipped the `case` reserved-word bug — fixed in T08.** |
| T05  | `f32ef64` | Per-department settings views (DepartmentSettings, FrameworkSettings, SourceSubscriptions, Departments admin view). |
| T06  | `d7d95fd` | Rewired Dashboard, TopicList, TopicDetail, Assessment to consume dept-scoped APIs + framework dispatcher. |
| T07  | `b71e19f` | Router guards (auth + active-dept + role gates), UI toast store, login redirect-honouring. |
| T08  | `2fcc3fa` | Vitest harness, 26 tests, `case`→`bcase` rename fix. |

## T08 detail (where this session spent most of its time)

### Vitest harness added
- Dev deps: `vitest@^4.1.7 @vue/test-utils@^2.4.10 jsdom@^29.1.1 @vitest/coverage-v8@^4.1.7`.
- `web/package.json` scripts: `"test": "vitest run"`, `"test:watch": "vitest"`.
- `web/tsconfig.json` — added `"vitest/globals"` to `types`.
- `web/vitest.config.ts` — jsdom env, `src/**/*.spec.ts`, `[vue()]`, `@/` alias.

### New test files
- `web/src/stores/session.spec.ts` — 17 tests (applyLoginResponse, hydrate liveness probe, switchDepartment wiring, RBAC getters, clear, unauth state).
- `web/src/components/DepartmentSwitcher.spec.ts` — 4 tests (unauth render-nothing, multi-dept v-select, switch wiring, single-dept static label).
- `web/src/components/cards/SwotCard.spec.ts` — 5 tests (quadrant render, empty placeholder, importance/confidence chips, verdict chip colour, fallback to top-level BusinessCase fields, framework-name subtitle).

Result: **26 / 26 passing**, typecheck clean, `vite build` succeeds.

### The `case` reserved-word fix
Vue's SFC template compiler (`@vue/compiler-sfc`) is stricter than
`vue-tsc`: it rejects template interpolations referencing JS reserved
words. The T04 cards used `defineProps<{ case: BusinessCase }>()` and
templates like `{{ case.framework?.name }}`. `npm run typecheck`
accepted it, but `npm run build` failed and `main` was broken.

Rename `case` → `bcase` applied in:
- `web/src/components/BusinessCaseCard.vue` (prop, dispatcher `:bcase="bcase"`, fallback `{{ bcase.model_used }}`, added comment explaining the rename).
- `web/src/components/cards/VerdictCard.vue`
- `web/src/components/cards/SwotCard.vue`
- `web/src/components/cards/PestleCard.vue`
- `web/src/views/TopicDetail.vue` — both call sites (lines 237, 244).

### Other discoveries worth remembering
- vue-test-utils stub `template:` strings are compiled by the **runtime**
  template compiler which is plain JS — TS syntax like
  `($event.target as HTMLSelectElement).value` throws SyntaxError. Use
  plain JS in stubs.
- `Record<string, unknown>` is the wrong type for the `stubs` map in
  `mount()` options — use `Record<string, Component>`
  (`import type { Component } from 'vue'`).
- `vue-tsc` also chokes on inline type annotations inside template event
  handlers — use named functions in `<script setup>` and pass them as
  the handler.

## State updates committed

`.planning/STATE.md`
- progress: 30/32 (94 %) → **31/32 (97 %)**
- current position: Plan 10-03 → **Plan 10-04** complete; **10-05 next**.
- `last_activity`, `stopped_at`, `Resume file` all advanced to 10-05.

`.planning/ROADMAP.md`
- 10-04 line flipped `[ ]` → `[x]`.

## G-decisions still locked (unchanged, for context)

G1 global topics + per-dept assessments; G2 multi-dept users +
`X-Active-Department` + `is_superadmin`; G3 pluggable frameworks;
G4 `business_cases` dept + framework + `structured_output` + UNIQUE;
G5 `dept_sources` subscription; G6 Default dept; G7 harmonization in
10-05; G8 rename deferred (funnel through `web/src/lib/strings.ts`);
G9 audit deferred.

## Plan 10-04 architectural facts useful for 10-05

- Auth: `POST /api/login`, `POST /api/logout`, `GET /api/me` (only
  `{ok: true}`, cookie liveness probe). SPA caches the full
  `LoginResponse` in `localStorage['session']`.
- Active dept: client-side Pinia + `localStorage['activeDepartment']`.
  **No** `/api/auth/switch-department` endpoint. `client.ts` auto-injects
  `X-Active-Department` on every fetch.
- Superadmins receive the full system dept list with synthesised
  `role: dept_lead` so the picker stays uniform.
- Department-sources URL is **hyphenated**: `/api/department-sources`.
- `GET /api/ai-config` returns 404 with a hint when empty (not 200 with
  null body).
- Hardcoded framework UUIDs: VERDICT `…0010`, SWOT `…0011`,
  PESTLE `…0012`.

## Files changed this session (final tally)

```
web/package.json                            (test scripts + 4 devDeps)
web/package-lock.json
web/tsconfig.json                           (vitest/globals types)
web/vitest.config.ts                        (NEW)
web/src/stores/session.spec.ts              (NEW — 17 tests)
web/src/components/DepartmentSwitcher.spec.ts  (NEW — 4 tests)
web/src/components/cards/SwotCard.spec.ts   (NEW — 5 tests)
web/src/components/BusinessCaseCard.vue     (case→bcase)
web/src/components/cards/VerdictCard.vue    (case→bcase)
web/src/components/cards/SwotCard.vue       (case→bcase)
web/src/components/cards/PestleCard.vue     (case→bcase)
web/src/views/TopicDetail.vue               (case→bcase, lines 237 + 244)
.planning/STATE.md
.planning/ROADMAP.md
```

## Next session entry point

1. Operator decision on push (9 commits on `main`).
2. Open `.planning/phases/10-multi-tenant-platform/10-05-PLAN.md` and
   execute autonomously (task-by-task commits, `autonomous=true`).
3. Optional quick-fix detour for the two backend bugs above before
   starting 10-05 if operator prefers a clean baseline.
