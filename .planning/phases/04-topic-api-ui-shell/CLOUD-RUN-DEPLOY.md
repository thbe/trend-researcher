# Cloud Run Deploy — Trend Researcher

> Runbook for deploying Trend Researcher to Google Cloud Run (`europe-west2`)
> on project **`thbe-private`**. Owned by the single operator (Thomas).
> Cross-references: `cloudbuild.yaml` (pipeline), `services/api/Dockerfile`
> (image), `services/api/docker-entrypoint.sh` (boot + dump rotation),
> Plan `04-06-PLAN.md` (gates G10/G11).

---

## 1. Prerequisites

You need:

- `gcloud` CLI installed and authenticated as a project owner / editor on
  `thbe-private`:
  ```
  gcloud auth login
  gcloud config set project thbe-private
  gcloud config set run/region europe-west2
  ```
- Billing enabled on `thbe-private`.
- A local checkout of `trend-researcher` at the tag you want to deploy.

Verify:
```
gcloud config list
gcloud projects describe thbe-private --format='value(projectNumber)'
```

---

## 2. One-time setup

Run these **once** per GCP project. They are idempotent (re-running is safe;
existing resources will report `ALREADY_EXISTS` and the script continues).

### 2.1 Enable APIs

```
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  cloudscheduler.googleapis.com
```

### 2.2 Create Artifact Registry

```
gcloud artifacts repositories create trend-researcher-images \
  --repository-format=docker \
  --location=europe-west2 \
  --description="Trend Researcher container images"
```

### 2.3 Create GCS bucket for persistent data

This bucket backs `/app/data` (Postgres data dir + nightly `pg_dump` rotation).

```
gcloud storage buckets create gs://trend-researcher-data \
  --location=europe-west2 \
  --uniform-bucket-level-access
```

### 2.4 Generate + seed the internal PAT in Secret Manager

```
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' \
  | gcloud secrets create trend-internal-pat \
      --data-file=- \
      --replication-policy=automatic
```

Verify (without printing the value):
```
gcloud secrets versions list trend-internal-pat
```

### 2.5 Grant IAM bindings

Cloud Run runtime SA needs to read the secret and read/write the bucket.
Cloud Build SA needs to deploy to Cloud Run.

```
PROJECT_NUMBER=$(gcloud projects describe thbe-private --format='value(projectNumber)')
RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
BUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

# Cloud Run runtime: read the PAT secret
gcloud secrets add-iam-policy-binding trend-internal-pat \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/secretmanager.secretAccessor"

# Cloud Run runtime: read/write the data bucket
gcloud storage buckets add-iam-policy-binding gs://trend-researcher-data \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/storage.objectAdmin"

# Cloud Build: deploy to Cloud Run + act as runtime SA
# NOTE: --condition=None is required if the project IAM policy already contains
# any conditional bindings (gcloud refuses non-interactive writes otherwise).
gcloud projects add-iam-policy-binding thbe-private \
  --member="serviceAccount:${BUILD_SA}" \
  --role="roles/run.admin" \
  --condition=None
gcloud projects add-iam-policy-binding thbe-private \
  --member="serviceAccount:${BUILD_SA}" \
  --role="roles/iam.serviceAccountUser" \
  --condition=None
```

---

## 3. First deploy

From a clean checkout at the tag you want to ship (e.g. `v0.4.0`):

```
git tag v0.4.0
COMMIT=$(git rev-parse --short HEAD)

gcloud builds submit \
  --config=cloudbuild.yaml \
  --region=europe-west2 \
  --substitutions=TAG_NAME=v0.4.0,COMMIT_SHA=${COMMIT}
```

Watch the build stream (build/push/deploy). Expected wall-clock on
`E2_HIGHCPU_8`: ~6–10 min for the first build, ~3–5 min for cached rebuilds.

When deploy completes, capture the service URL:
```
SERVICE_URL=$(gcloud run services describe trend-researcher \
  --region=europe-west2 --format='value(status.url)')
echo "${SERVICE_URL}"
```

### 3.1 Grant public ingress (allUsers → roles/run.invoker)

> ⚠️ **Required step.** Even with `--allow-unauthenticated` in
> `cloudbuild.yaml` the first revision is sometimes created with an empty
> IAM policy (`etag: ACAB`) and all requests return Google-Front-End 403.
> Verified gotcha during Wave 6 T09 first deploy on `thbe-private`.

```
gcloud run services add-iam-policy-binding trend-researcher \
  --region=europe-west2 \
  --member=allUsers \
  --role=roles/run.invoker
```

Verify with:
```
gcloud run services get-iam-policy trend-researcher --region=europe-west2
# Expect: bindings.members: [allUsers], bindings.role: roles/run.invoker
```

This grant is idempotent on subsequent deploys — only required once.

---

## 4. Cloud Scheduler wiring

Cloud Scheduler invokes `POST /api/internal/crawl` every 12 hours with the
PAT in the `Authorization` header.

### 4.1 Fetch the PAT for header construction

```
PAT=$(gcloud secrets versions access latest --secret=trend-internal-pat)
```

> The PAT only needs to leave Secret Manager once — to be embedded in the
> Scheduler job's HTTP headers. After creating the job, drop `PAT` from
> your shell history (`unset PAT && history -d $(history 1)`).

### 4.2 Create the scheduler job

```
gcloud scheduler jobs create http trend-researcher-crawl \
  --location=europe-west2 \
  --schedule="0 */12 * * *" \
  --time-zone="UTC" \
  --uri="${SERVICE_URL}/api/internal/crawl" \
  --http-method=POST \
  --headers="Authorization=Bearer ${PAT}" \
  --attempt-deadline=60s \
  --description="Trigger a crawl every 12h (G10: PAT-secured internal endpoint)"
```

### 4.3 Smoke-trigger immediately

```
gcloud scheduler jobs run trend-researcher-crawl --location=europe-west2
```

Expected: HTTP 202 in the Cloud Run logs; a new row in `crawl_runs`;
topics in `/api/topics` start showing the latest observation timestamps.

---

## 5. PAT rotation

Rotate the secret without redeploying — the new version is picked up on
the next Cloud Run cold start. Rotate the Scheduler header in lockstep.

```
NEW_PAT=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')

# Add new version to Secret Manager
echo -n "${NEW_PAT}" | gcloud secrets versions add trend-internal-pat --data-file=-

# Force a new Cloud Run revision so :latest secret resolves to the new version
gcloud run services update trend-researcher --region=europe-west2 \
  --update-env-vars=PAT_ROTATED_AT=$(date -u +%Y%m%dT%H%M%SZ)

# Update Scheduler header
gcloud scheduler jobs update http trend-researcher-crawl --location=europe-west2 \
  --update-headers="Authorization=Bearer ${NEW_PAT}"

unset NEW_PAT
```

Then disable the previous secret version:
```
gcloud secrets versions list trend-internal-pat
gcloud secrets versions disable <OLD_VERSION_NUMBER> --secret=trend-internal-pat
```

---

## 6. Smoke-checking the deployment

Six curls. Replace `${SERVICE_URL}` and `${PAT}` first.

```bash
# 1. Liveness
curl -fsS "${SERVICE_URL}/api/healthz"
#   -> {"status":"ok",...}

# 2. SPA shell
curl -fsS -o /dev/null -w "%{http_code}\n" "${SERVICE_URL}/"
#   -> 200

# 3. Topics list (may be empty pre-first-crawl)
curl -fsS "${SERVICE_URL}/api/topics?limit=5"
#   -> {"items":[...],"total":N,...}

# 4. Internal endpoint, no token -> 401
curl -sS -o /dev/null -w "%{http_code}\n" -X POST "${SERVICE_URL}/api/internal/crawl"
#   -> 401

# 5. Internal endpoint, wrong token -> 403
curl -sS -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Authorization: Bearer wrong-token" \
  "${SERVICE_URL}/api/internal/crawl"
#   -> 403

# 6. Internal endpoint, correct token -> 202 (queued)
curl -fsS -X POST \
  -H "Authorization: Bearer ${PAT}" \
  "${SERVICE_URL}/api/internal/crawl"
#   -> {"status":"queued"}
```

Then wait ~30s and re-query `/api/topics` — count should increase, and
`/api/runs` should show the new `crawl_run`.

---

## 7. Rollback

Cloud Run keeps prior revisions. To roll back without rebuilding:

```
# List revisions, newest first
gcloud run revisions list --service=trend-researcher --region=europe-west2

# Route 100% of traffic to the previous revision
gcloud run services update-traffic trend-researcher --region=europe-west2 \
  --to-revisions=<PREVIOUS_REVISION_NAME>=100
```

If a rebuild is needed (e.g. a bad image in Artifact Registry):
```
gcloud run services update trend-researcher --region=europe-west2 \
  --image=europe-west2-docker.pkg.dev/thbe-private/trend-researcher-images/trend-researcher:<KNOWN_GOOD_SHA>
```

Postgres data persists in GCS regardless of which revision is serving;
the on-disk format is stable across revisions that share the same
`postgresql-16` major version.

---

## 8. Cost notes

Single-operator footprint. Expected monthly cost on idle + ~60 crawls/month:

| Resource           | Configuration                              | Approx. monthly |
| ------------------ | ------------------------------------------ | --------------- |
| Cloud Run          | gen2, 2Gi/2vCPU, min=0 max=1, scale-to-0   | < $5            |
| Artifact Registry  | ~1.5 GB image storage                      | < $1            |
| GCS (data bucket)  | < 1 GB (PG data + 7-day dump rotation)     | < $1            |
| Secret Manager     | 1 secret, <100 access/month                | < $0.10         |
| Cloud Scheduler    | 1 job, 60 invocations/month                | < $0.10         |
| Cloud Build        | ~10 builds/month × ~8 min E2_HIGHCPU_8     | < $2            |
| **Total**          |                                            | **< $10/mo**    |

Watch-outs:
- `min-instances=0` is **required** to stay near zero cost — never set it
  to 1 without revisiting the budget. Cold-start adds ~3–5s for the first
  request after idle (acceptable for an internal tool).
- GCS-FUSE volumes round up reads/writes to 4 KiB; the embedded Postgres
  workload is small enough that this is not a cost driver in v1.

---

## First-deploy smoke results — 2026-05-17

Recorded after Wave 6 T09 first live deploy on `thbe-private`.

**Versions deployed:**
- v0.4.0 (commit `ef514cc`) — first deploy, BackgroundTask trigger pattern
- v0.4.1 (commit `a33d8d3`) — sync trigger pattern (current production)

**Build:**
- Wall-clock: **2m 37s** on `E2_HIGHCPU_8` (both v0.4.0 and v0.4.1; cache hit on builder stages)
- Image size pushed to Artifact Registry: **186 MB** compressed (597 MB uncompressed locally)
- Build ID v0.4.1: `80770dce-335e-4837-86c9-8b170f144a9a`

**Service:**
- URL: `https://trend-researcher-3g5goqptla-nw.a.run.app`
- Revision: `trend-researcher-00002-…` (v0.4.1)
- Cold-start latency to `/api/healthz`: **363 ms** (post-allUsers IAM grant)

**6-curl smoke matrix (post v0.4.1 deploy, all PASS):**

| # | Endpoint                                  | Expected             | Actual                                           |
|---|-------------------------------------------|----------------------|--------------------------------------------------|
| 1 | `GET /api/healthz`                        | 200 + `db:reachable` | ✅ 200 + `{"status":"ok","db":"reachable"}`      |
| 2 | `GET /`                                   | 200 + SPA HTML       | ✅ 200, 400-byte `index.html`                     |
| 3 | `GET /api/topics?limit=5`                 | 200 + list           | ✅ 200, real headlines after first crawl         |
| 4 | `POST /api/internal/crawl` (no token)     | 401                  | ✅ 401                                           |
| 5 | `POST /api/internal/crawl` (wrong token)  | 403                  | ✅ 403                                           |
| 6 | `POST /api/internal/crawl` (PAT)          | 200 + stats          | ✅ 200, fetched=159 inserted=11 updated=145 in 2.97 s |

**First crawl (sync trigger):**
- Wall-clock: **3.58 s** (curl total) / **2.97 s** server-side
- Totals: fetched=159, inserted=11, updated=145, skipped=3, errors=0
- Per source: hackernews 6 ins / 94 upd, nyt_homepage 0 ins / 20 upd, google_news 5 ins / 31 upd

**Cloud Scheduler verification:**
- Job `trend-researcher-crawl` created, schedule `0 */12 * * *` UTC
- Manual trigger executed `17:48:26` — succeeded, materialised 3rd `/api/runs` row (inserted=6 updated=150)
- `lastAttemptTime: 2026-05-17T17:48:26Z`, `status: {}`, `state: ENABLED`

**Topics in production DB after deploy:** 167 unique topics across 3 crawl runs.

**Deviations from this runbook:**

1. **BuildKit must be enabled on Cloud Build's docker step.**
   First build (v0.4.0 attempt #1, build `026b69a9`) failed at step
   17/36 with `the --mount option requires BuildKit`. Root cause: the
   `gcr.io/cloud-builders/docker` legacy builder does not enable BuildKit
   by default, but our Dockerfile uses `RUN --mount=type=cache,target=...`
   for uv sync. Fixed by adding `env: ['DOCKER_BUILDKIT=1']` to step 1 in
   `cloudbuild.yaml` (commit `ef514cc`). Now documented in the cloudbuild
   file itself.

2. **`gcloud add-iam-policy-binding` requires `--condition=None`** when the
   project has any conditional IAM bindings. Plain bindings fail with
   `non-interactive mode + conditional bindings present`. Documented in
   §2.5 of this runbook.

3. **`--allow-unauthenticated` in cloudbuild deploy args was silently
   dropped** on first revision. Required manual `add-iam-policy-binding
   --member=allUsers --role=roles/run.invoker` (now documented as §3.1
   above). Verified org policy `iam.allowedPolicyMemberDomains` was empty,
   so root cause is likely a default-deny on first-revision IAM. The
   binding survives subsequent deploys.

4. **`/api/internal/crawl` returns 200 (sync), not 202 (background task).**
   The original Wave 6 plan used `BackgroundTasks` returning 202 immediately.
   Switched to synchronous execution returning 200 + stats body in commit
   `a33d8d3` because:
   - Cloud Run throttles CPU after the response is sent under scale-to-zero,
     making background-task completion timing unpredictable.
   - Sync execution gives Cloud Scheduler a meaningful retry signal (5xx vs
     2xx); fire-and-forget 202 cannot communicate crawl failure.
   - Crawl is bounded (~3 s observed) — far below the 600 s Cloud Run
     timeout, so there is no UX cost to making it sync.

5. **Topic `description` field is `null` for all 167 topics.** The crawler
   does not yet capture descriptions — Phase 4.5 (queued) will surface
   them from already-fetched Google News RSS `<description>` and NYT
   home-page standfirst.

6. **Google News URLs are base64 CBM tokens** (e.g.
   `CBMixgFBVV95cUxQOG…`), not resolved publisher URLs. Phase 4.5 (queued)
   will resolve them.
