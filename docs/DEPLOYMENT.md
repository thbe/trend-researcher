# Deployment & Operations Runbook

## Overview

Trend Researcher runs as a **single Cloud Run service** with an embedded PostgreSQL 16 database. Data is persisted via pg_dump/restore to a GCS bucket mounted at `/app/data` using Cloud Run gen2 cloud-storage volumes (GCS-FUSE).

> Component-level architecture: [`ARCHITECTURE.md`](ARCHITECTURE.md). REST contract: [`API.md`](API.md).

| Property | Value |
|----------|-------|
| GCP Project | `thbe-private` |
| Region | `europe-west2` |
| Service name | `trend-researcher` |
| Artifact Registry | `europe-west2-docker.pkg.dev/thbe-private/trend-researcher-images` |
| Data bucket | `gs://trend-researcher-data` |
| Container resources | 2 vCPU, 2Gi RAM, 600s timeout |
| Scaling | min=0, max=1 |

---

## How to Deploy

Cloud Build is **manual** (not auto-triggered by push). Submit from the repo root:

```bash
gcloud builds submit \
  --config=cloudbuild.yaml \
  --region=europe-west2 \
  --substitutions=TAG_NAME=v0.6.0,COMMIT_SHA=$(git rev-parse --short HEAD)
```

The pipeline runs three steps:
1. **Build** — 3-stage Docker build (Node SPA + Python venv + Ubuntu runtime with embedded PG-16)
2. **Push** — Pushes `$COMMIT_SHA`, `$TAG_NAME`, and `latest` tags to Artifact Registry
3. **Deploy** — `gcloud run deploy` with all volume mounts, secrets, and env vars

---

## Container Startup Sequence

The entrypoint (`services/api/docker-entrypoint.sh`) does the following in order:

1. **Start embedded PostgreSQL 16** — `initdb` if fresh, then `pg_ctl start`
2. **Create user/database** — `trend_app` / `trend_researcher` (with SUPERUSER for restore operations)
3. **Restore from dump** — fallback chain: `$DUMP_FILE` -> `$DUMP_FILE.prev` -> fresh (empty schema)
4. **Run Alembic migrations** — `cd /app/packages/core && alembic upgrade head`
5. **Start uvicorn** — `uvicorn api.main:app --host 0.0.0.0 --port 8000`

### Graceful Shutdown (SIGTERM)

On shutdown the `cleanup` trap:
1. Sends SIGTERM to the uvicorn process
2. Runs `pg-dump-rotate.sh` for a final dump to GCS
3. Stops PostgreSQL with `pg_ctl stop -m fast`

---

## Embedded Postgres Architecture

```
┌─────────────────────────────────────────────┐
│  Cloud Run Container (gen2)                 │
│                                             │
│  PostgreSQL 16   ←→   /var/lib/postgresql/  │
│       ↕                (ephemeral tmpfs)    │
│  pg_dump/restore                            │
│       ↕                                     │
│  /app/data/      ←→   GCS Bucket           │
│   trend_researcher.dump                     │
│   trend_researcher.dump.prev                │
└─────────────────────────────────────────────┘
```

**Why not run PG directly on GCS-FUSE?** GCS-FUSE doesn't support `chown`/`chmod`, which PostgreSQL requires for its data directory. Instead, the dump/restore pattern is used:

- **Startup:** Restore from dump into ephemeral PG data dir
- **Runtime:** Debounced dumps every 30s after writes (via `DumpDebouncer` middleware calling `pg-dump-rotate.sh`)
- **Shutdown:** Final dump before container exits
- **Rotation:** `DUMP_TMP` -> verified -> `DUMP_FILE` (current promoted to `DUMP_PREV`)

Maximum data loss window: ~30 seconds (debounce interval).

---

## Secrets & Environment Variables

### Secrets (via Secret Manager)

| Secret | Binding | Purpose |
|--------|---------|---------|
| `trend-internal-pat` | `TREND_INTERNAL_PAT` | PAT token securing `POST /api/internal/crawl` |

### Environment Variables (set in Cloud Build deploy step)

| Variable | Value | Purpose |
|----------|-------|---------|
| `BUILD_VERSION` | `$TAG_NAME` | Version tag for healthz/debugging |
| `BUILD_COMMIT` | `$COMMIT_SHA` | Git SHA for tracing |
| `BUILD_TIME` | `$BUILD_ID` | Build identifier |
| `CRAWLER_TOP_N` | `100` | Items per source to crawl |
| `LOG_FORMAT` | `json` | Structured logging |
| `AUTH_SEED_USERNAME` | `admin` | Default admin user seeded on first boot |

### Internal (set by entrypoint/Dockerfile, not overridden)

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8000` | Uvicorn listen port |
| `PERSIST_DIR` | `/app/data` | GCS-FUSE mount point |
| `DB_DUMP_SCRIPT` | `/app/scripts/pg-dump-rotate.sh` | Dump rotation script |
| `DB_DUMP_DEBOUNCE_MS` | `30000` | Dump debounce interval (ms) |
| `PG_DATA` | `/var/lib/postgresql/data` | Embedded PG data dir |
| `PG_USER` | `trend_app` | Embedded PG user |
| `PG_DB` | `trend_researcher` | Embedded PG database name |
| `WEB_DIST_DIR` | `/app/web_dist` | SPA static files path |

### LLM Provider (configured in DB, not env)

Stage 2 assessment configuration lives in the `ai_config` table and is edited from the UI (`/ai-config`) or `PUT /api/ai-config`. The Cloud Run image does **not** bundle Ollama — in production `base_url` must point at a hosted endpoint:

| `base_url` contains | Adapter used | `api_token` required |
|---------------------|--------------|----------------------|
| `anthropic` | Anthropic | yes |
| `openai` (or any `api_token` set) | OpenAI-compatible | yes |
| anything else | Ollama (HTTP) | no |

Rotating an API key is a `PUT /api/ai-config` call — no redeploy needed.

---

## Monitoring

### Health Check

```
GET /api/healthz
```

- **200** `{"status": "ok", "db": "reachable"}` — PG responding to `SELECT 1`
- **503** `{"status": "degraded", "db": "unreachable"}` — PG not responding

This endpoint is unauthenticated (bypasses auth middleware).

### Cloud Scheduler

A Cloud Scheduler job POSTs to `/api/internal/crawl` every 12 hours with the `TREND_INTERNAL_PAT` header to trigger crawl runs. No separate scheduler service exists.

---

## Running One-Off Scripts Against Prod

Since the database is embedded inside the container, you cannot connect directly. Options:

### Option 1: Use the running container via Cloud Run exec (if available)

```bash
gcloud run services describe trend-researcher --region=europe-west2 --format='value(status.url)'
# Then hit an API endpoint that does what you need
```

### Option 2: Download the dump, run locally

```bash
# Pull latest dump from GCS
gcloud storage cp gs://trend-researcher-data/trend_researcher.dump ./

# Restore into local Postgres
pg_restore --clean --if-exists --no-owner -d trend_researcher ./trend_researcher.dump

# Run your script against localhost
DATABASE_URL=postgresql+asyncpg://... python your_script.py

# Dump back and upload (if you made changes)
pg_dump -Fc trend_researcher > trend_researcher.dump
gcloud storage cp ./trend_researcher.dump gs://trend-researcher-data/trend_researcher.dump
```

### Option 3: Trigger via internal API

The `/api/internal/crawl` endpoint accepts a PAT-authenticated POST. Custom one-off operations can be exposed as internal API routes.

---

## Rollback Procedure

### Rollback to a Previous Image

```bash
# List recent revisions
gcloud run revisions list --service=trend-researcher --region=europe-west2

# Deploy a previous image tag
gcloud run deploy trend-researcher \
  --image=europe-west2-docker.pkg.dev/thbe-private/trend-researcher-images/trend-researcher:v0.5.1 \
  --region=europe-west2
```

### Rollback Database

The dump rotation keeps a `.prev` file. If the latest dump is corrupt:

1. The entrypoint automatically falls back to `.prev` on startup
2. For manual intervention:

```bash
# Check what's in the bucket
gcloud storage ls gs://trend-researcher-data/

# Swap dumps manually if needed
gcloud storage cp gs://trend-researcher-data/trend_researcher.dump.prev gs://trend-researcher-data/trend_researcher.dump
```

### Emergency: Fresh Start

If both dumps are corrupt, the container starts with an empty schema (Alembic creates all tables). Data is lost but the service is operational.

---

## Local Development

Use `docker-compose.yml` which runs an external Postgres (no embedded PG):

```bash
docker compose up -d postgres
docker compose up api
# Crawler is one-shot:
docker compose run --rm crawler
```

The API connects to `postgresql+asyncpg://trend:trend@postgres:5432/trend_researcher` and the entrypoint detects `DATABASE_URL` is set, skipping embedded PG startup.

---

## Prerequisites (One-Time Setup)

```bash
# Enable APIs
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  cloudscheduler.googleapis.com

# Create Artifact Registry repo
gcloud artifacts repositories create trend-researcher-images \
  --repository-format=docker --location=europe-west2

# Create GCS bucket
gcloud storage buckets create gs://trend-researcher-data \
  --location=europe-west2 --uniform-bucket-level-access

# Create internal PAT secret
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' \
  | gcloud secrets create trend-internal-pat --data-file=-

# Grant Cloud Run SA access to bucket + secret (see CLOUD-RUN-DEPLOY.md for full IAM)
```
