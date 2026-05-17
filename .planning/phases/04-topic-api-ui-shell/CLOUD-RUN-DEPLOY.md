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

## First-deploy smoke results

> Populated by Wave 6 T09 after the live deploy.

- **Build duration:** _TBD_
- **Image size (pushed):** _TBD_
- **First cold-start latency:** _TBD_
- **First crawl wall-clock:** _TBD_
- **Topics observed after first crawl:** _TBD_
- **Deviations from this runbook:** _TBD_
