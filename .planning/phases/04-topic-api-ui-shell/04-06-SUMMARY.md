# Plan 04-06 — PAT-secured `/api/internal/crawl` + scheduler removal + first Cloud Run deploy — SUMMARY

**Wave:** 6 of 6 (Phase 4 — **final wave**)
**Status:** ✅ Complete — Phase 4 closed
**HEAD at closeout:** `dbd17eb`
**Deployed:** `https://trend-researcher-3g5goqptla-nw.a.run.app` (revision `00002`, image `v0.4.1`, commit `a33d8d3`) on 2026-05-17

## Task table

| #   | Task                                                        | Commit    | Autonomous | Notes |
| --- | ----------------------------------------------------------- | --------- | ---------- | ----- |
| T01 | `pat_auth.py` bearer-auth dependency                        | `bf73893` | yes        | `HTTPBearer` + `hmac.compare_digest`; 503 env-unset, 401 missing/wrong-scheme, 403 wrong-token |
| T02 | `routes/internal.py` + wire `POST /api/internal/crawl`      | `2e93846` | yes        | Initial impl used `BackgroundTasks`; isolated engine via `crawler.app.composition.build_repository`, dispose in finally |
| T02.fix | sync-execution rewrite (T09 mid-deploy discovery)        | `a33d8d3` | yes        | Replaced bg-task + 202 with synchronous await + 200 + stats body; rationale in code review section below |
| T03 | `services/api/pyproject.toml`: add `crawler` workspace dep + `structlog` | `63bc14e` | yes        | Plus `crawler = { workspace = true }` in `[tool.uv.sources]`; uv lock refreshed |
| T04 | 5 PAT bearer-auth tests (DB-free)                           | `176ca4b` | yes        | Status-code matrix: 503 unset, 401 missing, 401 wrong-scheme, 403 wrong-token, 200 happy |
| T05 | 3 `/api/internal/crawl` background-task tests + engine-leak fix | `789df48` | yes        | Caught real bug: `build_repository()` was outside try/finally; widened to `engine = None` initial + guard in `finally` |
| T06 | Delete `services/scheduler/` tree + scrub references        | `8eca7dc` | yes        | Removed Dockerfile, entrypoint.sh, crontab, README.md; removed `scheduler:` block from `docker-compose.yml`; scrubbed README + workspace comment; uv lock refreshed |
| T07 | `cloudbuild.yaml` + `.env.example` PAT placeholder          | `881981c` | yes        | 117 lines; 3 steps (build/push/deploy); gen2 + 2Gi/2vCPU + min=0 max=1; `--set-secrets=TREND_INTERNAL_PAT=trend-internal-pat:latest`; cloud-storage volume → `/app/data`; `--file=services/api/Dockerfile` |
| T07.fix | BuildKit env on Cloud Build docker step                  | `ef514cc` | yes        | `gcr.io/cloud-builders/docker` (legacy) doesn't enable BuildKit by default; our Dockerfile uses `RUN --mount=type=cache,target=/root/.cache/uv` |
| T08 | `CLOUD-RUN-DEPLOY.md` runbook (8 sections)                  | `71e65a7` | yes        | Prereqs, one-time setup, first deploy, Cloud Scheduler wiring, PAT rotation, smoke curls, rollback, cost notes; reserved smoke-results section for T09 |
| T09 | **OPERATOR GATE** — first Cloud Run deploy + Scheduler wiring + runbook closeout | `dbd17eb` | **no** | All GCP resources provisioned on `thbe-private`; 6/6 smoke PASS; Cloud Scheduler job ENABLED + manually triggered (3rd `/api/runs` row materialised); 6 deviations recorded in runbook |
| T10 | this SUMMARY + ROADMAP `[x]` + STATE flip                   | (this commit) | yes    | Phase 4 closed |

## Acceptance gates (Wave 6)

| Gate                                                                                  | Result |
| ------------------------------------------------------------------------------------- | ------ |
| `POST /api/internal/crawl` (no header) → 401                                          | PASS (test + live smoke #4) |
| `POST /api/internal/crawl` (wrong token) → 403                                        | PASS (test + live smoke #5) |
| `POST /api/internal/crawl` (env unset) → 503                                          | PASS (test only — env always set in prod) |
| `POST /api/internal/crawl` (PAT) → 200 + `{ status:ok, totals:{…} }` + DB row appended | PASS (live smoke #6 + `/api/runs?limit=5` showed 3 rows post-trigger) |
| `services/scheduler/` directory deleted                                               | PASS (`git ls-files services/scheduler/` returns empty) |
| `docker compose config` lists 2 services (api + postgres)                             | PASS (scheduler block gone) |
| Cloud Run deploy succeeds, embedded PG bootstraps, all 3 Alembic migrations run       | PASS (boot logs confirmed) |
| SPA opens at the public Cloud Run URL                                                 | PASS (200 + 400-byte index.html) |
| Cloud Scheduler job wired with PAT in `Authorization` header                          | PASS (manual trigger executed → run materialised) |
| Constant-time PAT compare (`hmac.compare_digest`)                                     | PASS (`grep` in `pat_auth.py`) |
| Fail-closed on missing PAT env (503, never 200)                                       | PASS (test + code review) |
| Build context uses `--file=services/api/Dockerfile`                                   | PASS (cloudbuild.yaml) |
| GCS-FUSE volume mounted at `/app/data` (gen2 execution env)                           | PASS (cloudbuild.yaml + boot logs show `/app/data` writable) |
| `--max-instances=1` (data-safety: one PG writer)                                      | PASS (cloudbuild.yaml) |
| `--memory=2Gi` (embedded PG headroom)                                                 | PASS (cloudbuild.yaml) |
| api pytest suite                                                                      | PASS — 8/8 in 0.21 s (5 PAT + 3 internal-crawl) |

## CONTEXT.md G9/G10/G11 closure

**G9 — Dump cadence + corruption tolerance**: implemented in Wave 5 (debouncer middleware + entrypoint trap + `pg-dump-rotate.sh` with `pg_restore --list` verify + 3-slot ring + `flock -n 9`). Verified live on Cloud Run: container boots from empty bucket, runs migrations, accepts writes, will dump on next quiescence + on SIGTERM. **Closed.**

**G10 — PAT secret source + rotation**: env var `TREND_INTERNAL_PAT`, Secret Manager secret `trend-internal-pat` (version 1), Cloud Run `--set-secrets=TREND_INTERNAL_PAT=trend-internal-pat:latest`, `hmac.compare_digest` constant-time compare, fail-closed 503 on missing env, format `secrets.token_urlsafe(32)` → 43-char URL-safe token. All six attributes verified in `pat_auth.py` + tests + runbook + live deploy. **Closed.**

**G11 — Scheduler service deletion**: `services/scheduler/` directory removed entirely (Dockerfile + entrypoint.sh + crontab + README.md). `docker-compose.yml` `scheduler:` block removed. Cloud Scheduler job `trend-researcher-crawl` created in `europe-west2`, schedule `0 */12 * * *` UTC, hits `${SERVICE_URL}/api/internal/crawl` with Bearer PAT, attempt deadline 9m30s, retry config defaults. Manual trigger verified → new `/api/runs` row. Local-trigger options preserved in README (`curl -H "Authorization: Bearer $PAT" -X POST http://localhost:8000/api/internal/crawl` OR `docker compose run --rm crawler run-once`). `crawl_runs` table + `GET /api/runs` telemetry independent of trigger shape (intentional from G11). **Closed.**

## Architecture pivot recap (Phase 4 amendment-level)

Phase 4 was originally 5 waves ending at the Vuetify SPA scaffold. The operator surfaced production-deployment shape during execute-phase kickoff (`food-assistant` sibling-repo pattern). Amendment grew the plan to 6 waves with two locked decisions:

- **Wave 5 rewrite**: 3-stage Dockerfile + embedded `postgresql-16` + GCS-FUSE-friendly entrypoint with restore chain + `pg_dump` rotation. This wave's container *is* the production artifact.
- **Wave 6 add (this plan)**: PAT-secured `/api/internal/crawl` replaces the docker-socket-mounting `services/scheduler/` cron container. Cloud Scheduler now triggers crawls over plain HTTP. Single trust boundary = the container; everything outside gates through Cloud Run + Secret Manager IAM.

This is **the** architectural decision of Phase 4 — read API + UI + production deploy all land in one phase, on a single container, with deterministic dump-sync persistence. Cost envelope: scale-to-zero, ≤ €1/month idle, ≤ €5/month under 2x-daily crawl.

## Test coverage delta

- **+5 PAT auth tests** (`test_pat_auth.py`): 503 unset / 401 missing / 401 wrong-scheme / 403 wrong-token / 200 happy (with monkeypatched `_run_crawl_isolated`).
- **+3 internal-crawl tests** (`test_internal_crawl.py`): 200 + stats body (monkeypatched runner), sync handler waits for completion (timing assertion 50 ms ≤ elapsed < 1 s), 500 on RuntimeError (propagates through HTTPException).
- All Phase 3 + 04-01 through 04-05 tests still green (regression gate green per-file; cross-file `test_static_mount.py` pollution carried as deferred-acceptance item 14).
- Test isolation: all 8 new tests are DB-free (no `TEST_DATABASE_URL` required). Total api pytest now 27 (was 19).

## Code review notes — sync vs background-task pivot

`/api/internal/crawl` ships as **synchronous** execution returning 200 + stats body, not 202 + `BackgroundTasks` as originally planned. Discovery + decision happened during T09 live deploy:

1. **What I thought I saw**: After PAT'd `POST` returned 202, waited 45 s, queried `/api/topics` → still empty. Concluded background task was killed by Cloud Run CPU throttling (CPU is only guaranteed during request handling under default scale-to-zero pricing).
2. **What actually happened**: The bg task DID complete — I just queried too early. The first run (17:28:24) inserted 156 rows; I checked at ~17:28:55.
3. **Why I shipped the sync fix anyway**:
   - **Observable contract**: 200 + stats lets Cloud Scheduler distinguish a successful crawl from a failure; 5xx triggers Scheduler's built-in retry. Fire-and-forget 202 is opaque to the trigger.
   - **Bounded latency**: observed crawl wall-clock is ~3 s, far below Cloud Run's 600 s timeout. No UX cost.
   - **Resilient to CPU-throttling timing variance**: even if bg tasks usually finish, "usually" isn't a contract Cloud Scheduler can rely on. Sync is.
   - **No alternative regressions**: didn't need `--no-cpu-throttling` (which would break scale-to-zero pricing).

Sync is the right shape; the original 202 + bg-task plan was a holdover from the in-process trigger pattern that doesn't translate to a serverless scale-to-zero target. Documented in `internal.py` docstring and `CLOUD-RUN-DEPLOY.md` deviation #4.

## Deploy results recap

- **Build wall-clock**: 2 m 37 s on `E2_HIGHCPU_8` (both v0.4.0 and v0.4.1; cache hit on builder stages after first build)
- **Image size**: 186 MB compressed in Artifact Registry (597 MB uncompressed locally)
- **Cold-start to `/api/healthz`**: 363 ms
- **Sync crawl wall-clock**: 3.58 s (curl total) / 2.97 s server-side
- **Topics in production DB**: 167 across 3 crawl runs
- **Cloud Scheduler**: ENABLED, schedule `0 */12 * * *` UTC, next run `2026-05-18T00:00:00Z`

Full smoke matrix in `CLOUD-RUN-DEPLOY.md` "First-deploy smoke results" section.

## Security posture

- **Trust boundary** = the Cloud Run container.
- **Outside boundary**: Cloud Scheduler (OIDC into Run optional, currently uses Bearer PAT header), gcloud operator CLI (Google account auth), operator browser (read-only public endpoints).
- **Inside boundary**: embedded PG, dump rotation, internal endpoint.
- **No docker socket**, **no host PID namespace**, **no privileged container** — all trust pivots Phase 3's scheduler-container had are gone.
- **PAT rotation**: 3-command runbook (`gcloud secrets versions add` → `gcloud run services update --update-secrets` → `gcloud scheduler jobs update http --update-headers`). Documented in CLOUD-RUN-DEPLOY.md §5.
- **Public read endpoints by design** (UI-001 baseline; v1 is single-operator internal tool with VPC-only ingress documented as alternative in runbook §3 & §7).

## Follow-ups (Phase 4.5 + deferred-acceptance)

- **(a) Phase 4.5 (queued, discuss next)** — topic descriptions are NULL across all 167 production rows. Both Google News RSS `<description>` and NYT homepage standfirst are already in fetched bytes but discarded by current parsers. Phase 4.5 will surface them without new HTTP fetches (ARC-001 preserved).
- **(b) Phase 4.5** — Google News URLs are base64 CBM tokens; need resolution to publisher URLs (HEAD redirect / CBM-token decode / fallback to publisher-name).
- **(c) Deferred-acceptance item 14** — `test_static_mount.py` (Wave 5) pollutes `sys.modules['api.main']` causing 6 false-failures in full-suite pytest run. Per-file invocation passes 8/8. Needs fixture-isolation refactor.
- **(d) PoC scale-out** — `--max-instances=1` is a data-safety constraint (one PG writer). Multi-instance requires external Cloud SQL OR leader-election dump model. Phase 5+ scope only if observed cardinality justifies it.
- **(e) Cloud Run access-log sink → Cloud Logging structured queries** — defer until operator needs it.
- **(f) Belt-and-braces**: flip Cloud Run to `--no-allow-unauthenticated` + IAP for SPA + OIDC for Scheduler. Documented in CLOUD-RUN-DEPLOY.md §7 as alternative; not implemented v1.
- **(g) GitHub Dependabot**: 2 moderate vulnerabilities reported on origin/main after first Wave 6 push. Triage as Phase 4.5 security-backlog item.

## Phase 4 closeout

- ROADMAP Phase 4 checkbox flipped `[x]`.
- All 4 Phase 4 success criteria checkboxes `[x]` (handled in same commit).
- Breadcrumb appended: "Deployed to Cloud Run `https://trend-researcher-3g5goqptla-nw.a.run.app` on 2026-05-17 via `cloudbuild.yaml` (v0.4.1, commit `a33d8d3`)."
- STATE.md status → `phase-complete`, last_commit → this commit, `completed_plans += 6` (20 → 20 was incorrect bookkeeping; reset to actual: Phases 1+2+3 = 14, Phase 4 = +6, total = 20).
- Code review depth=standard inline in this SUMMARY (sync-vs-bg-task section above + acceptance gates table).
- Inline gsd-verifier `04-VERIFICATION.md` to be written next as part of Phase 4 closeout (regression + schema-drift + code-review gates).
