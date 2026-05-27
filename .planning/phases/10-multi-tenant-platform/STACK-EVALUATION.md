# Phase 10 — Tech Stack Evaluation for Multi-Tenant Scope

**Status:** advisory — read before greenlighting Phase 10 execution
**Question:** Is the current stack still the right choice once we go multi-department, multi-user, multi-framework?
**Short answer:** **Yes, keep the stack. Three targeted upgrades, one deferred risk.**

The current stack was chosen for a single-operator retail tool. Multi-tenancy
stresses three axes: **identity/RBAC**, **data isolation**, and **frontend
state**. The rest of the stack (FastAPI, SQLAlchemy 2.x async, Alembic,
pluggable LLMPort, Vuetify 3, monorepo+uv) scales to the Phase 10 scope without
modification.

---

## Verdict per layer

| Layer | Current | Multi-tenant fit | Recommendation |
|---|---|---|---|
| API framework | FastAPI + Pydantic v2 | ✅ excellent | **KEEP** |
| ORM / async | SQLAlchemy 2.x async | ✅ excellent | **KEEP** |
| Migrations | Alembic (single tree in `packages/core`) | ✅ ARC-003 holds | **KEEP** |
| DB engine | PostgreSQL | ✅ correct choice | **KEEP** |
| **DB deploy shape** | **Embedded Postgres in Cloud Run + GCS dump-sync** | ⚠️ **risk grows with tenants** | **KEEP for v1, plan exit** |
| LLM layer | Pluggable `LLMPort` (Ollama / OpenAI-compat / oMLX / Anthropic) | ✅ already per-config | **KEEP**, scope per dept (already in plan 10-02) |
| Background jobs | In-process `assessment_jobs` drain loop | ✅ sufficient at expected load | **KEEP**, revisit if >100 dept×framework backlog |
| Auth | bcrypt + signed cookie + seed user from env | ⚠️ **no SSO, no role claims, no password reset** | **UPGRADE in 10-01** (minimal: add roles to cookie; defer SSO) |
| Frontend framework | Vue 3 + Vuetify 3 + Vite | ✅ excellent | **KEEP** |
| **Frontend state** | **ad-hoc refs + composables, no store** | ⚠️ **breaks at dept switcher + role gates** | **ADD Pinia in 10-04** |
| Monorepo | uv workspaces (`packages/core` + `services/*` + `web/`) | ✅ excellent | **KEEP** |
| Tenant isolation strategy | (none yet — single-tenant) | — | **APPLICATION-LEVEL filter via `active_department` dependency** (already in plan 10-01). Postgres RLS deferred. |

---

## The three targeted upgrades (folded into existing plans, no new phase)

### 1. Auth — add role/dept claims to the signed cookie (plan 10-01)

**Why:** Today the cookie carries only `user_id`. Every request would otherwise
have to hit `user_departments` to know the active dept and role. That's a
join per request and a footgun for forgotten checks.

**Change:** cookie payload becomes
`{user_id, is_superadmin, active_department_id, role_in_active_dept}`.
`active_department_id` is set on login (default = user's first dept) and
switched via `POST /api/auth/switch-department`. Cookie shape stays signed +
HttpOnly; no library swap.

**What we are NOT doing in Phase 10:**
- SSO (OIDC/SAML) — deferred. Internal tool, env-seeded users is acceptable.
- Password reset flow — deferred.
- Per-resource ACLs — out of scope; role-per-dept is enough.

**Risk if skipped:** every route handler re-derives role from DB → easy to
forget → privilege escalation bug.

### 2. Frontend state — adopt Pinia (plan 10-04)

**Why:** The SPA needs to share `activeDepartment`, `availableDepartments`,
`roleInActiveDept`, and `frameworksEnabledForActiveDept` across **Dashboard,
TopicList, TopicDetail, AIConfig, Assessment, Departments, FrameworkSettings,
and DepartmentSwitcher**. Prop-drilling or per-view fetches will produce
inconsistent UI (e.g., switcher shows dept A while TopicDetail still queries
dept B).

**Change:** add `pinia` dependency, create `stores/session.ts` (user, super,
active dept, role) and `stores/frameworks.ts` (per-dept framework list).
All API calls read `activeDepartment` from the store and send it as a header
(`X-Active-Department-Id`) — matches the cookie claim, server validates.

**What we are NOT doing:** no SSR, no Nuxt migration, no rewrite of existing
views beyond wiring them to the store.

**Risk if skipped:** dept switcher bugs, role-gated nav flicker, double-fetch
on every route change.

### 3. Tenant isolation — application-level scoping via dependency (plan 10-01/10-02)

**Why:** Postgres RLS is the textbook answer, but it costs: every connection
needs `SET app.current_dept`, every test fixture changes, and superadmin
bypass becomes finicky. For our scale (single Postgres container, <100 depts
realistic) **application-level filtering through a FastAPI dependency** is
the better trade.

**Change:** new dependency `require_active_department()` returns
`(user, department, role)`. Every router that owns tenant data
(`ai_config`, `assessment`, `crawl_config`→`department_sources`,
`business_cases` reads, new `frameworks`, `harmonization` mutations) takes
this dep. Queries always filter by `department_id`. Superadmin can pass
`?department_id=` to override.

**What we are NOT doing:** Postgres RLS. Documented as a future upgrade if
we ever expose the DB to non-API clients.

**Risk:** forgetting the dependency on a new route = cross-tenant leak.
Mitigation: a single integration test (`test_tenant_isolation.py`) walks every
registered route and asserts non-global routes reject calls without an active
dept. Added in plan 10-01.

---

## The one deferred risk: embedded Postgres + GCS dump-sync

**Current shape (Phase 4 G9–G11):** Postgres runs *inside* the Cloud Run
container. On shutdown, `pg_dump` to GCS. On startup, `pg_restore` from GCS.
Brilliant for a single-operator tool — zero infra cost, survives restarts,
backups are free.

**Why it becomes risky under multi-tenant load:**

| Factor | Single-tenant impact | Multi-tenant impact |
|---|---|---|
| Cold-start restore time | ~seconds (small DB) | grows linearly with topics × depts × assessments |
| Concurrent writers | 1 operator | N analysts × M depts assessing in parallel |
| Cloud Run instance scaling | Fine (1 instance) | **Breaks** — multiple instances can't share embedded PG; you'd silently fork the DB |
| Dump cadence | Per-shutdown is fine | Per-shutdown loses any work done since last dump if instance is killed mid-assessment |
| Backup granularity | "the dump" | Need PITR for "undo this dept's bad framework run" |

**Recommendation for Phase 10:**
- **Do not change this in Phase 10.** Phase 10 already has 5 plans of work.
- **Pin Cloud Run to `max_instances=1`** if not already — prevents silent
  DB forking the moment a second instance spins up. (Verify in plan 10-00
  or a follow-up ops ticket.)
- **Add to ROADMAP as Phase 11 candidate: "Externalize Postgres to Cloud SQL
  or Neon."** Trigger condition: any of
  - >3 concurrent analysts observed
  - any single assessment job >30s (instance-kill risk window)
  - any request for horizontal scaling
- The migration path is clean: Alembic tree is unchanged, only the
  connection string + the dump/restore lifecycle code goes away.

**Do not block Phase 10 on this.** But the user should know it's the load-
bearing assumption that quietly stops working as tenants grow.

---

## Things explicitly considered and rejected

| Option | Why rejected for Phase 10 |
|---|---|
| Switch FastAPI → Litestar / Django | No multi-tenant feature we need is missing in FastAPI |
| Add Celery / RQ / Arq | `assessment_jobs` table + in-process drain is fine at projected load; adding a broker is infra cost we don't need |
| Postgres RLS | See above — wrong cost/benefit for our scale |
| OIDC / SSO (Keycloak, Authentik, WorkOS) | Internal tool, no external users; env-seeded + cookie is enough; revisit if user count >20 |
| Vue → React/Svelte | Vuetify investment is significant; no multi-tenant capability gained |
| Separate DB per tenant ("silo model") | Operationally awful for ≤100 depts; kills the global topic pool that ARC-001 depends on |
| Drop pluggable LLMPort, hardcode one provider | The per-dept AI config G4 requires it — keep |
| Add a feature-flag service (LaunchDarkly, Unleash) | Framework enablement is the only flag-like surface and it already lives in `department_frameworks` |

---

## Language split: keep Python backend, do not unify on Node/TS

**Question:** the SPA is TypeScript. Should the backend (`packages/core` +
`services/api` + `services/crawler` + `services/assessor`) be rewritten in
Node/TS so the whole stack is one language?

**Answer: No. Keep Python. Optionally close the type-sharing gap with
OpenAPI codegen later.**

### Why Python wins here

| Concern | Python today | Node/TS alternative | Winner |
|---|---|---|---|
| **Crawling ecosystem** | `feedparser`, `httpx`, `BeautifulSoup`, `praw` (Reddit), `snscrape`, `playwright-python`, mature parsers for every site we touch | `cheerio`, `got`, `rss-parser`, `snoowrap` (unmaintained), `playwright` — usable but thinner for niche sources (NYT, HN APIs, X) | **Python** |
| **Fuzzy dedup (ARC-001 critical)** | `rapidfuzz` — C++ under the hood, the reference implementation | `fastest-levenshtein`, `fuse.js` — slower, less battle-tested at scale | **Python** |
| **ORM + migrations** | SQLAlchemy 2.x async + Alembic — mature, handles complex Postgres types (JSONB, enums, partial indexes) cleanly | Prisma (great DX but weak on Postgres-specific features, awkward migrations), Drizzle (better SQL, younger), TypeORM (legacy) | **Python** |
| **LLM SDKs** | `openai`, `anthropic`, `ollama` Python clients are the canonical ones | Vercel AI SDK, `ai`, `langchain.js` — solid now, but every new provider ships Python first | **Python (slight)** |
| **Pydantic v2 vs Zod** | Pydantic v2 is Rust-backed, faster, deeply integrated with FastAPI for request/response validation + OpenAPI generation | Zod + tRPC is excellent, but you'd be rebuilding the FastAPI auto-OpenAPI surface | **Tie (different strengths)** |
| **End-to-end types (SPA ↔ API)** | Need codegen step (OpenAPI → TS client) | Native with tRPC or shared Zod schemas | **TS** |
| **Cognitive load (single operator)** | Two languages | One language | **TS** |
| **Rewrite cost** | 0 (already done — 9 phases shipped) | Massive — rewrite crawler + assessor + API + ORM + migrations | **Python by a mile** |

### The honest score

The only real wins for unifying on TS are:
1. **One language to maintain** — real benefit for a solo operator.
2. **End-to-end types** without a codegen step.

The losses are:
1. **Rewrite cost** — Phases 1–9 shipped in Python. Rewriting them buys zero
   new features and risks regressions on the parts that already work.
2. **Crawler ecosystem regression** — `rapidfuzz` and the Python parser
   ecosystem are materially better. ARC-001 (fuzzy dedup, deterministic
   ingest) is the load-bearing invariant of the whole product; we should not
   weaken it.
3. **ORM regression** — SQLAlchemy + Alembic is better than the TS options
   for the kind of schema evolution Phase 10 is about to do (5 new tables,
   composite uniques, JSONB columns).
4. **Multi-tenancy is a data/auth problem, not a language problem.**
   Switching languages solves zero Phase 10 requirements.

### Closing the one real gap: shared types

The "no shared types between API and SPA" gap is real but solvable **without
rewriting the backend**:

- FastAPI already auto-generates a complete OpenAPI spec at `/openapi.json`.
- Add `openapi-typescript` (or `orval`) to the `web/` build to generate a
  typed client from that spec.
- Result: SPA gets compile-time types matching the Pydantic models, with no
  hand-maintained DTO duplication.

**Recommendation:** add OpenAPI codegen to the SPA build in plan 10-04
(small, ~half a task) so the dept switcher, framework picker, and
harmonization view all have typed API calls. This captures the one TS-side
benefit without paying the Python rewrite cost.

### When we would reconsider

- If we ever need **SSR / edge rendering** (we don't — internal tool).
- If we ever need **real-time bidirectional sync** (we don't — polling is fine).
- If the operator changes and the new one is TS-only and refuses to maintain
  Python. (Not a current risk.)
- If Python LLM SDKs fall meaningfully behind TS ones. (Currently the
  opposite trend.)

### Verdict

**Keep Python for backend. Keep TS for SPA. Add OpenAPI → TS codegen in
plan 10-04 to close the type-sharing gap.** No rewrite.

---

## Summary for greenlight

**Greenlight Phase 10 as scoped.** The stack is sound. Three upgrades are
already absorbed into plans 10-01 / 10-02 / 10-04:

1. Cookie carries `is_superadmin + active_department_id + role`.
2. Pinia stores `session` + `frameworks` on the SPA.
3. `require_active_department()` dependency + tenant-isolation integration
   test.

**Issue A — RESOLVED.** Cloud Run pinned to `max_instances=1, min_instances=0`
following the proven football-assistant pattern (sister repo at
`../football-assistant/cloudbuild.yaml` + `docker-entrypoint.sh` +
`scripts/pg-dump-rotate.sh`). Durability comes from:

1. Embedded Postgres data dir lives on the container's ephemeral fs (NOT on
   the GCS volume — GCS FUSE can't satisfy PG's chown/chmod requirements).
2. A GCS bucket is mounted at `/app/data` via Cloud Run native volumes
   (`--add-volume=type=cloud-storage`).
3. On cold start, entrypoint restores from `/app/data/<service>.dump` with a
   `.dump → .dump.prev → fresh schema` fallback chain (atomic `mv`, verified
   via `pg_restore --list`).
4. The Node/Python app triggers debounced `pg_dump` rotations after writes
   (`DB_DUMP_DEBOUNCE_MS=30000`), and a `SIGTERM` handler runs a final dump
   inside the ~10s Cloud Run grace window.
5. `max_instances=1` guarantees a single writer — no divergent-DB risk —
   while `min_instances=0` keeps cold-start cost at zero for an internal
   tool that may sit idle for hours.

This is the same shape this project already plans to ship (CONTEXT.md
"Carrying forward" — Phase 4 G9–G11). Phase 10 inherits it unchanged.

**No remaining ops items blocking execution.**

**One item to add to ROADMAP for later:** externalize Postgres (Phase 11
candidate, not blocking).
