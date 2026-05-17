# syntax=docker/dockerfile:1.7
# 3-stage build for trend-researcher api service.
#
# Stage 1 (web-builder, node:20-alpine):
#   Builds the Vuetify SPA from web/. Produces /web/dist/ (index.html + assets/).
#
# Stage 2 (python-builder, uv on debian):
#   Resolves the uv workspace and installs the api package + workspace deps
#   (core + crawler — crawler is imported in 04-06 for /api/internal/crawl;
#   landed in 04-05 so the venv layer rebuild happens once for the phase).
#
# Stage 3 (runtime, ubuntu:24.04):
#   Ships embedded postgresql-16 + postgresql-client-16 + the python venv +
#   the SPA dist. ENTRYPOINT is docker-entrypoint.sh which toggles between
#   embedded-PG (empty DATABASE_URL — prod Cloud Run path) and external-PG
#   (DATABASE_URL set — local compose path).


# ---------------------------------------------------------------------------
# Stage 1: web-builder — build the Vuetify SPA
# ---------------------------------------------------------------------------
FROM node:20-alpine AS web-builder

WORKDIR /web

# Lockfile-first install for max cache hit on web/ source-only changes.
COPY web/package.json web/package-lock.json ./
RUN npm ci --prefer-offline --no-audit --no-fund

COPY web/ ./
RUN npm run build
# Produces /web/dist/{index.html, assets/...}


# ---------------------------------------------------------------------------
# Stage 2: python-builder — resolve uv workspace + install api package
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS python-builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

# Lockfile + every member pyproject first, so dependency resolution caches
# on source-only changes. Preserves the Phase 3 layer-cache pattern.
COPY pyproject.toml uv.lock .python-version ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY services/crawler/pyproject.toml services/crawler/pyproject.toml
COPY services/api/pyproject.toml services/api/pyproject.toml
COPY services/assessor/pyproject.toml services/assessor/pyproject.toml

# Resolve deps for api (workspace member) — no project install yet.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --package api --no-dev

# Source for api + its workspace deps. Crawler copied here (not in 04-06)
# so the venv layer rebuild happens once for the full phase — api will
# import crawler.app.orchestrator in 04-06 for the /api/internal/crawl
# endpoint.
COPY packages/core packages/core
COPY services/api services/api
COPY services/crawler services/crawler

# Install the api package itself (+ workspace deps in-place).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package api --no-dev


# ---------------------------------------------------------------------------
# Stage 3: runtime — ubuntu:24.04 + embedded PG-16 + SPA + venv
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        postgresql-16 \
        postgresql-client-16 \
        python3.12 \
        python3.12-venv \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python venv + workspace source from python-builder.
COPY --from=python-builder /build/.venv /app/.venv
COPY --from=python-builder /build/packages /app/packages
COPY --from=python-builder /build/services /app/services

# Built SPA from web-builder.
COPY --from=web-builder /web/dist /app/web_dist

# Entrypoint + dump-rotate script. chmod +x so they're executable in the
# runtime user context (root by default; entrypoint switches to postgres
# via `su -` for PG admin ops).
COPY services/api/docker-entrypoint.sh /app/docker-entrypoint.sh
COPY scripts/pg-dump-rotate.sh /app/scripts/pg-dump-rotate.sh
RUN chmod +x /app/docker-entrypoint.sh /app/scripts/pg-dump-rotate.sh

# Persistent data dir for embedded-PG dumps. Owned by postgres OS user so
# the cleanup() trap can write the final dump as that user without sudo.
RUN mkdir -p /app/data /var/log/postgresql \
    && chown -R postgres:postgres /var/lib/postgresql /var/log/postgresql /app/data

# Runtime env. WEB_DIST_DIR + DB_DUMP_SCRIPT activate the FastAPI
# StaticFiles mount + dump-debouncer middleware (both env-gated; pytest
# runs without these and skips them — see 04-05 T03 + T05).
ENV PATH="/app/.venv/bin:$PATH" \
    WEB_DIST_DIR=/app/web_dist \
    DB_DUMP_SCRIPT=/app/scripts/pg-dump-rotate.sh \
    DB_DUMP_DEBOUNCE_MS=30000 \
    PERSIST_DIR=/app/data \
    PG_DATA=/var/lib/postgresql/data \
    PG_LOG=/var/log/postgresql/startup.log \
    PG_USER=trend_app \
    PG_DB=trend_researcher \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
