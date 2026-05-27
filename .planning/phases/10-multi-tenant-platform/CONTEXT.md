# Phase 10 — Multi-Tenant Market Intelligence Platform: Context

**Status:** discussed (planning kickoff)
**Mode:** mvp
**Depends on:** Phase 8 (assessment UI shipped); Phase 9 superseded — single-tenant hardening folded into this phase
**REQ-IDs in scope:** TBD (will mint new MT-001..MT-0NN during plan execution; tracked in REQUIREMENTS.md update inside plan 10-00)

## Domain boundary

Phase 10 is the moment the system stops being a single-operator retail-only tool
and becomes a **multi-department market intelligence platform**: many users in
many departments, each pointing their own *lens* (sources, criteria, framework,
business context) at the **same global topic stream**, with a cross-department
harmonization view on top.

Three deliverables:

1. **Multi-tenant data model** — departments, per-(user,department) RBAC,
   per-department scoping of all configuration and assessment tables.
2. **Pluggable assessment frameworks** — SWOT, PESTLE, simple verdict (seed
   set), selectable per department, with structured JSON output schemas.
3. **Harmonization view** — cross-department side-by-side per topic, plus an
   admin-editable meta-assessment ("Net view: …") on each topic.

**Ingest stays global and AI-free** (ARC-001 invariant preserved). The crawler
pulls the union of all sources enabled by any department; topics remain a
single shared pool; dedup is still global. AI runs only in Stage 2, but Stage 2
is now **per (topic, department, framework)** instead of per topic.

## Carrying forward (NOT re-decided in this phase)

- **ARC-001** — Stage 1 / Stage 2 separation. No AI in ingest. Crawler does not
  read department config beyond "is this source enabled by anyone?".
- **ARC-003** — single Alembic migration tree owned by `packages/core`.
- **Embedded Postgres + GCS dump-sync + Cloud Run** deploy shape (Phase 4
  amendment G9–G11). No infra changes in Phase 10.
- **Pluggable `LLMPort`** + provider auto-detection (Phase 6 + commit `0eb4c71`).
  Phase 10 does NOT touch the LLM adapter layer.
- **Background `assessment_jobs` queue** (Phase 7, migration 0013). Phase 10
  extends the job row with `department_id` + `framework_id` but keeps the
  drain loop unchanged.
- **`crawl_runs` + `/api/runs` telemetry** — unchanged (operational, not
  tenant-scoped).
- **Auth model** (bcrypt + signed cookie, seed user from env) — kept; extended
  with role + department membership but the cookie shape is unchanged.

## Decisions locked

### G1 — Topics stay global; assessments become per-department

A topic is a world-fact, not a departmental opinion. The crawler produces one
global topic stream (dedup unchanged). What changes per department is the
**lens** applied to that stream:

- which sources the dept *cares about* (source subscription)
- what relevance / opportunity / risk criteria are used
- which framework structures the output (SWOT vs PESTLE vs verdict)
- the business context fed into the prompt
- the AI model / endpoint used

**Implication:** `topics`, `topic_sources`, `crawl_runs`, `v_topic_stats` are
untouched. All tenant-scoping lives downstream of them.

### G2 — Multi-department users (user_departments join table, per-pair role)

A user can belong to N departments with a different role in each. RBAC role is
keyed on `(user_id, department_id)`, not on user alone. System-wide admin is a
separate boolean (`users.is_superadmin`).

**Roles (per department):**
| role        | can read | can assess | can edit dept config | can harmonize | can manage members |
| ----------- | -------- | ---------- | -------------------- | ------------- | ------------------ |
| `viewer`    | ✓        | ✗          | ✗                    | ✗             | ✗                  |
| `analyst`   | ✓        | ✓          | ✗                    | ✗             | ✗                  |
| `dept_lead` | ✓        | ✓          | ✓                    | ✓             | ✓                  |

**System-wide (orthogonal):**
- `is_superadmin = true` → can create/delete departments, manage all users,
  override any dept role check.

**Active department concept:** the SPA picks ONE active department at a time
(persisted client-side). API calls carry it via `X-Active-Department` header
(set automatically by the SPA's API client). Every dept-scoped endpoint
resolves the active dept from the header + verifies `(current_user,
active_dept)` membership.

### G3 — Frameworks are pluggable; each department picks one (or many)

Three seeded frameworks in v1:
1. **`verdict`** — current schema (binary relevance + reason + importance +
   opportunity_or_risk + investment_band + confidence). This is the existing
   business_cases shape, preserved as a framework so existing assessments
   migrate cleanly into the new model (see G6).
2. **`swot`** — structured JSON: `{strengths: [], weaknesses: [],
   opportunities: [], threats: []}`, each cell `{point: str, rationale: str}`.
   Plus top-level `verdict`, `importance`, `confidence` for cross-framework
   sorting.
3. **`pestle`** — structured JSON: `{political, economic, social,
   technological, legal, environmental}`, each `{relevance: low|med|high,
   notes: str}`. Plus top-level `verdict`, `importance`, `confidence`.

Each framework owns:
- A JSON schema for its structured output (validated server-side post-LLM).
- A prompt template (Jinja-like, with `{{ business_context }}`,
  `{{ topic_title }}`, `{{ topic_description }}`, `{{ sources }}` slots).
- A display component name (the SPA maps `framework.display_component` →
  `<SwotCard />`, `<PestleCard />`, `<VerdictCard />`).

Department picks **N frameworks** (≥1) and marks **one as default**. When
running assessment, operator picks which framework to use from the dept's
enabled set (defaults to dept default). Same topic can be assessed under
multiple frameworks within one department — each produces its own
business_case row.

### G4 — Business cases gain (department_id, framework_id, structured_output)

```
business_cases
  + department_id  FK → departments(id)  NOT NULL
  + framework_id   FK → assessment_frameworks(id)  NOT NULL
  + structured_output  JSONB  NOT NULL  -- framework-specific shape
  UNIQUE (topic_id, department_id, framework_id, prompt_version, model_used)
```

The existing columns (`relevance_verdict`, `relevance_reason`,
`model_used`, `prompt_version`, `raw_response`, timestamps) all survive. They
hold the **denormalised top-level fields** (verdict, reason) extracted from
`structured_output` for cheap sorting/filtering in the list views. SWOT and
PESTLE rows populate these from their top-level `verdict` / `confidence`
slots; the framework-specific cells live in `structured_output`.

**No "old vs new" toggle:** existing rows migrate to `framework_id =
verdict.id`, `department_id = default_dept.id`, `structured_output = {…}` built
from existing columns. Plan 10-02 handles this in the same migration that adds
the columns.

### G5 — Per-department source subscription (NOT per-department crawls)

Crawler still runs once per cadence and pulls the **union of all sources
enabled by any department**. A topic that originates only from a source no
department subscribes to is simply… never seen by anyone (and the crawler
wouldn't fetch it). This is enforced by:

```
department_sources  (department_id, source_name, enabled)
                    PK (department_id, source_name)
```

When dept Retail enables `hackernews`, a row goes in. The crawler queries
`SELECT DISTINCT source_name FROM department_sources WHERE enabled = true`
to build its effective source list at run start (replaces the global
`crawl_config.enabled` check).

`crawl_config` itself **stays global** for the per-source operational tuning
(`top_n`, `capture_summary`, `verify_ssl`, `feed_url`) — these are technical
crawler settings, not departmental preferences. Only `enabled` moves to per-
department subscription. UI surfaces this as: global Sources page shows tech
config (superadmin only); each dept's Settings page shows which sources to
subscribe to.

### G6 — Default department for migration

On migration up:
1. Create `departments` row `{name: "Default", slug: "default"}`.
2. Insert a `user_departments` row for every existing user with role
   `dept_lead`.
3. Mark the seed user (`AUTH_SEED_USERNAME`) as `is_superadmin = true`.
4. Copy the existing global `ai_config` (key='default') into a new row keyed
   on `department_id = default.id` (table reshape — see plan 10-02).
5. Seed `assessment_frameworks` with `verdict`, `swot`, `pestle`. Mark
   `verdict` as default for the Default department.
6. Backfill `business_cases.department_id = default.id`,
   `framework_id = verdict.id`, build `structured_output` from existing
   columns.
7. Backfill `assessment_jobs.department_id = default.id`,
   `framework_id = verdict.id`.
8. Build `department_sources` rows by copying `crawl_config` enable-state into
   the Default department.

After migration: the system behaves identically for the existing user. Nothing
broken, nothing visibly different until they create a second department.

### G7 — Harmonization v1 = Option B (read-only side-by-side + admin annotation)

Topic detail page gains a new tab **"Cross-department views"** showing N cards
(one per `(department, framework)` pair that produced a business_case for this
topic), each rendering the framework-appropriate display component.

A separate **`topic_harmonizations`** table holds a single optional
admin/dept_lead-authored meta-assessment per topic:

```
topic_harmonizations
  topic_id        PK, FK → topics(id) ON DELETE CASCADE
  net_view        TEXT  NOT NULL      -- free-text "Net view: ..."
  authored_by     FK → users(id)
  authored_at     TIMESTAMP
  updated_at      TIMESTAMP
```

Edit-in-place from the harmonization tab (only `dept_lead` of any dept or
`is_superadmin` can write). No history, no workflow, no notifications — those
were Option C, explicitly deferred.

### G8 — Rename: deferred; new code stays rename-neutral

The rename ("Market360" / "Signal360" / "Panorama" / etc.) is deferred. To
keep the rename a future sed-and-redeploy:
- New tables, columns, env vars, route prefixes use **neutral** names
  (`departments`, `assessment_frameworks`, etc. — no "trend" or "retail" in
  any identifier).
- SPA strings (page titles, headers) are funnelled through a single
  `web/src/lib/strings.ts` constants file so the future rename touches one
  file.
- No new container/image/service names use "trend-researcher" except where
  the existing ones already do.

### G9 — Audit logging deferred

"Who changed what" audit logs (members added, frameworks switched, etc.) are
NOT in Phase 10. We rely on Postgres `updated_at` columns + git history for
v1. A dedicated `audit_log` table is a Phase 11 candidate if real multi-user
use exposes the need.

## Files expected to change

**Schema (`packages/core`):**
- `packages/core/alembic/versions/0016_departments_and_rbac.py` (new) — plan 10-01
- `packages/core/alembic/versions/0017_scope_existing_tables.py` (new) — plan 10-02
- `packages/core/alembic/versions/0018_assessment_frameworks.py` (new) — plan 10-03
- `packages/core/alembic/versions/0019_topic_harmonizations.py` (new) — plan 10-05
- `packages/core/src/core/models.py` — add `Department`, `UserDepartment`,
  `DepartmentSource`, `AssessmentFramework`, `DepartmentFramework`,
  `TopicHarmonization`; extend `User`, `BusinessCase`, `AssessmentJob`,
  `AIConfig`.
- `packages/core/src/core/seed.py` (new or extended) — seed frameworks
  (verdict/swot/pestle) on startup if missing.
- `packages/core/tests/test_departments_migration.py` (new)
- `packages/core/tests/test_frameworks_seed.py` (new)

**API service (`services/api`):**
- `services/api/src/api/routes/departments.py` (new) — CRUD for departments
  (superadmin only), member management, dept config endpoints.
- `services/api/src/api/routes/frameworks.py` (new) — list system frameworks,
  per-dept enable/disable, set default.
- `services/api/src/api/routes/harmonization.py` (new) — `GET /api/topics/{id}/
  harmonization` returns all business_cases + the meta-annotation; `PUT`
  upserts the annotation.
- `services/api/src/api/dependencies.py` — add `get_active_department()`
  dependency that reads `X-Active-Department` header, verifies membership,
  returns `(department, role)`.
- `services/api/src/api/routes/{ai_config,crawl_config,assessment,
  dashboard,topics}.py` — re-scope every endpoint that's currently global to
  use the active department dependency. Topics list endpoint filters by
  source subscription (G5).
- `services/api/src/api/routes/auth.py` — login response includes
  `departments: [{id, name, role}]` so SPA can populate the switcher.
- `services/api/tests/` — new test modules per route + a shared
  `conftest.py` fixture that seeds a default dept + a second dept + users.

**Frontend (`web/`):**
- `web/src/stores/activeDepartment.ts` (new) — pinia store (or composable)
  holding active dept, persisted to localStorage.
- `web/src/api/client.ts` — auto-inject `X-Active-Department` header.
- `web/src/components/DepartmentSwitcher.vue` (new) — dropdown in app bar.
- `web/src/views/Departments.vue` (new, superadmin only) — dept CRUD + member
  mgmt + per-dept settings entry point.
- `web/src/views/FrameworkSettings.vue` (new) — per-dept framework picker.
- `web/src/components/cards/{VerdictCard,SwotCard,PestleCard}.vue` (new) —
  framework-specific display components.
- `web/src/views/TopicDetail.vue` — add "Cross-department views" tab + meta
  annotation editor.
- `web/src/views/{AIConfig,CrawlConfig,Assessment,Dashboard}.vue` — re-scope
  to active department (mostly transparent — the API change does the work).
- `web/src/router/index.ts` — add `/departments`, `/departments/:id/settings`,
  guard routes by role.
- `web/src/lib/strings.ts` (new) — centralised UI strings (G8 rename hook).

**Crawler (`services/crawler`):**
- `services/crawler/src/crawler/app/orchestrator.py` — `run_once()` queries
  `department_sources` (union) instead of `crawl_config.enabled` to build the
  effective source list. Per-source `top_n` etc. still from `crawl_config`.

**Assessor (`services/assessor`):**
- `services/assessor/src/assessor/domain/prompts.py` — refactor into
  framework-aware template lookup. Each framework's prompt template lives in
  `services/assessor/src/assessor/domain/frameworks/{verdict,swot,pestle}.py`
  with a `build_prompt(topic, ai_config) -> str` + `parse_output(raw) -> dict`
  + `JSON_SCHEMA` (for validation).
- `services/assessor/src/assessor/domain/pipeline.py` — looks up framework by
  id, calls its `build_prompt` + `parse_output` + validates against schema.

**Planning / docs:**
- `.planning/ROADMAP.md` — mark 6/7/8 complete; drop or fold Phase 9; add
  Phase 10. (plan 10-00)
- `.planning/STATE.md` — sync to reality. (plan 10-00)
- `.planning/REQUIREMENTS.md` — add MT-001..MT-0NN requirements. (plan 10-00)
- `docs/ARCHITECTURE.md` — refresh for multi-tenant model. (plan 10-05 wrap)

## Out of scope (explicit)

- **Per-tenant data isolation** beyond row-level `department_id` scoping (no
  RLS, no schema-per-tenant). Single Postgres, single app instance.
- **External auth** (SSO, OIDC, SAML) — internal seed-user auth stays as-is.
- **Rate limiting / per-tenant quotas** — single-operator-per-dept usage scale.
- **Audit log table** (G9 defer).
- **Consensus / merge workflow** for harmonization (Option C deferred).
- **Notifications** (email, slack, in-app) on new assessments / harmonizations.
- **Custom framework authoring UI** — the three seeded frameworks are
  hardcoded definitions in `services/assessor/src/assessor/domain/frameworks/`.
  Adding a fourth requires a code change + a `seed.py` row. UI-driven
  framework authoring is a Phase 11+ candidate.
- **The rename itself** (G8 defer).
- **Cross-department source-cost analytics** (which dept is "responsible" for
  which fetches) — not a v1 question.
- **Migration backout** beyond Alembic `downgrade` — once a second department
  is created in prod, downgrading to single-tenant is operator's manual
  problem.

## Success criteria (mapped from goals)

1. ✅ Two or more departments can coexist with distinct sources, AI configs,
   frameworks, and assessment results — verified by integration test seeding
   2 depts with different settings and asserting isolation.
2. ✅ A user with `(retail, dept_lead) + (procurement, viewer)` membership
   sees retail's assess buttons but only read access to procurement — verified
   by route-level test.
3. ✅ A topic assessed by retail (SWOT) and procurement (PESTLE) renders both
   cards on the topic's harmonization tab; an admin can write a "Net view"
   annotation that persists and is visible to all members of any dept the
   topic touches.
4. ✅ Existing single-tenant data (current production) migrates cleanly:
   pre-migration topics, business_cases, ai_config, crawl_config all visible
   under the "Default" department after migration with zero data loss.
5. ✅ Crawler still runs as a single one-shot job; the effective source list
   is the union of all departments' subscriptions; `crawl_runs` rows still
   reflect a single global run.
6. ✅ ARC-001 preserved — no AI code path in crawler or in any
   `department_sources` resolution; verified by grep.

## Plan shape (target)

6 plans, executed sequentially (each gates the next; no parallel waves
because the data model evolves monotonically):

1. **10-00** — Sync `ROADMAP.md` + `STATE.md` to reality (mark 6/7/8 done,
   add Phase 10 entry, mint MT-* requirement ids in `REQUIREMENTS.md`).
   *autonomous=true*, ~30 min.
2. **10-01** — `departments`, `users.is_superadmin`, `user_departments`
   migration + ORM + RBAC dependency + departments CRUD endpoints + seed
   Default dept + assign existing users + tests.
   *autonomous=false* (operator gate before production migration).
3. **10-02** — `department_sources`, scope `ai_config` /
   `business_cases` / `assessment_jobs` per dept (add FKs, backfill,
   constraints), crawler orchestrator union-of-dept-sources, tests.
   *autonomous=false* (operator gate, biggest data model change).
4. **10-03** — `assessment_frameworks`, `department_frameworks`,
   refactor assessor to framework-aware prompt/parse/validate, seed
   verdict/swot/pestle, structured_output column on business_cases, tests.
   *autonomous=false* (operator gate, assessor refactor).
5. **10-04** — Frontend: dept switcher, role-gated nav, `X-Active-Department`
   header, departments admin view, framework settings view, framework display
   components, all existing views re-scoped via API.
   *autonomous=true*.
6. **10-05** — Harmonization: `topic_harmonizations` table + endpoints +
   topic detail "Cross-department views" tab + Net view editor + final
   ARCHITECTURE.md refresh + closeout SUMMARY.
   *autonomous=true*.

## Open / deferred to planning step

- Whether `verdict` framework's prompt template should be the *current*
  production prompt verbatim (1:1 migration) or already cleaned up — decide
  in 10-03 PLAN. Recommendation: verbatim, so behaviour is identical on day 1.
- Whether to gate harmonization read access on dept membership too (must be
  member of at least one of the depts that assessed the topic) or expose to
  any logged-in user — decide in 10-05 PLAN. Leaning: any logged-in user can
  *read*, only `dept_lead`+ can *write* the Net view.
- Whether `crawl_config.enabled` column survives after `department_sources`
  takes over — leaning **drop it** in 10-02 (single source of truth) but
  needs verification that no crawler code path still reads it.
- SPA framework display component file structure (one file per framework vs.
  one generic component switching on `framework.key`) — decide in 10-04 PLAN.
