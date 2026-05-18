# Trend Researcher

A two-stage internal tool that continuously crawls major news, social, and tech sites to surface trending/viral topics, then uses AI to evaluate which topics matter for a specific market (starting with retail) and drafts a rough business case for the ones that do.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Stage 1 — Ingest (deterministic, zero AI)                  │
│  Python crawlers pull top-N items from RSS/API sources       │
│  (NYT, Google News, Hacker News). Fuzzy dedup via           │
│  rapidfuzz. Store in PostgreSQL.                            │
├─────────────────────────────────────────────────────────────┤
│  Stage 2 — Assessment (AI, not yet implemented)             │
│  RAG layer filters topics for retail-market relevance,      │
│  generates business cases with importance scores.           │
├─────────────────────────────────────────────────────────────┤
│  Frontend — Vue 3 + Vuetify SPA                             │
│  View trends, configure crawl runs, read assessments.       │
└─────────────────────────────────────────────────────────────┘
```

**Deployment model:** Single container on Cloud Run with embedded PostgreSQL 16. Data persists via GCS-FUSE mounted volume with dump/restore lifecycle.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Ingest | Python 3.12, asyncio, httpx, feedparser, rapidfuzz |
| API | FastAPI, uvicorn, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 16 (embedded in container, persisted to GCS) |
| Frontend | Vue 3, Vuetify 3, Vite, TypeScript |
| Auth | bcrypt passwords, HMAC-SHA256 signed cookie sessions |
| Packaging | uv workspace (monorepo), hatchling |
| Deployment | Google Cloud Run (europe-west2), Cloud Build |

## Project Structure

```
trend-researcher/
├── packages/
│   └── core/              # Shared models, settings, Alembic migrations
│       ├── src/core/      # ORM models (Topic, CrawlRun, CrawlConfig, User)
│       └── alembic/       # 7 migration versions
├── services/
│   ├── api/               # FastAPI app + docker-entrypoint.sh + Dockerfile
│   │   └── src/api/       # Routes, auth middleware, dump-debouncer
│   ├── crawler/           # Typer CLI one-shot crawler
│   │   └── src/crawler/   # Sources, orchestrator, fuzzy dedup
│   └── assessor/          # Stage 2 AI assessment (placeholder)
├── web/                   # Vue 3 + Vuetify SPA
├── scripts/               # Utility scripts
├── docker-compose.yml     # Local dev: postgres + crawler + api
├── cloudbuild.yaml        # CI/CD pipeline
└── pyproject.toml         # uv workspace root
```

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 20+ and npm
- PostgreSQL 16 (or use docker-compose)
- Docker (for containerised runs)

## Local Development Setup

### 1. Clone and configure environment

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL to your local Postgres
```

### 2. Install Python dependencies

```bash
uv sync
```

### 3. Run database migrations

```bash
cd packages/core
uv run alembic upgrade head
```

### 4. Start the API server

```bash
uv run uvicorn api.main:app --reload --port 8000
```

### 5. Run the crawler (one-shot)

```bash
uv run crawler run-once --top-n 50
```

### 6. Start the frontend (dev mode)

```bash
cd web
npm install
npm run dev
```

### Using Docker Compose

```bash
docker compose up
```

This starts PostgreSQL, the API (port 8000 with SPA), and runs a one-shot crawl.

## API Endpoints

All routes are prefixed with `/api`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/healthz` | Liveness check + DB ping |
| POST | `/api/login` | Authenticate, set session cookie |
| POST | `/api/logout` | Clear session cookie |
| GET | `/api/me` | Current authenticated user |
| GET | `/api/topics` | Paginated topic list with stats |
| GET | `/api/runs` | Last N crawl runs (newest first) |
| GET | `/api/crawl-config` | Current crawl source configuration |
| PUT | `/api/crawl-config` | Update crawl source configuration |
| POST | `/api/internal/crawl` | Trigger a crawl run (internal/scheduler) |

**Auth:** All `/api/*` routes except `/api/login` and `/api/healthz` require an authenticated session cookie.

**Default credentials:** `admin` / `0nly4%Testing`

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Async PostgreSQL connection string | (required) |
| `CRAWLER_TOP_N` | Items per source per crawl | `100` |
| `LOG_FORMAT` | Log output format (`json` or `text`) | `json` |
| `AUTH_SECRET_KEY` | HMAC-SHA256 key for session cookies | (auto-generated) |
| `AUTH_SEED_USERNAME` | Initial admin username | `admin` |
| `AUTH_SEED_PASSWORD` | Initial admin password | `0nly4%Testing` |
| `TREND_INTERNAL_PAT` | Bearer token for internal endpoints | — |
| `WEB_DIST_DIR` | Path to built SPA assets | — |
| `DB_DUMP_SCRIPT` | Script path for post-write DB dumps | — |
| `PERSIST_DIR` | Data directory for embedded PG | `/app/data` |
| `PORT` | API listen port | `8000` |

### Crawl Configuration

The crawler reads source configuration from the `crawl_config` database table. If no config exists, it falls back to hardcoded defaults (NYT, Google News, Hacker News RSS feeds).

## Deployment

### Production (Cloud Run)

Manual deploy via Cloud Build:

```bash
gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions=COMMIT_SHA=$(git rev-parse --short HEAD),TAG_NAME=v0.6.0
```

**Target:** Cloud Run in `europe-west2`, single instance (0–1 scaling), 2 GiB RAM, 2 vCPU.

**Production URL:** https://trend-researcher-70197270850.europe-west2.run.app

### Container Architecture

The production container (Ubuntu 24.04) bundles:
- Embedded PostgreSQL 16 (data in GCS-FUSE volume at `/app/data`)
- Python venv with api + core + crawler packages
- Built Vue SPA served by FastAPI StaticFiles

Boot sequence: restore DB from dump → run Alembic migrations → start uvicorn.

Crawls are triggered on a 12-hour cadence via Cloud Scheduler POSTing to `/api/internal/crawl`.

## Testing

```bash
uv run pytest
```

## Database Migrations

Managed via Alembic in `packages/core/alembic/`:

```bash
# Create a new migration
cd packages/core
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head

# Rollback one step
uv run alembic downgrade -1
```

## Contributing

1. All domain models live in `packages/core` — shared across services
2. AI logic belongs **only** in Stage 2 (`services/assessor`) — Stage 1 ingest must remain fully deterministic
3. Dedup uses fuzzy string matching only (rapidfuzz) — no AI/embeddings in ingest
4. Run `uv sync` after adding dependencies to any workspace member
5. Frontend changes: `cd web && npm run build` to regenerate dist for container builds
