# syntax=docker/dockerfile:1.7
# Multi-stage build for trend-researcher api service.
# Builder uses uv to resolve the workspace; runtime is plain python:slim with
# the prebuilt /app/.venv copied over. Long-running container (uvicorn).

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Copy lockfile + root workspace manifest + every member pyproject so uv can
# resolve the workspace graph without pulling in source code yet (better cache).
COPY pyproject.toml uv.lock .python-version ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY services/crawler/pyproject.toml services/crawler/pyproject.toml
COPY services/api/pyproject.toml services/api/pyproject.toml
COPY services/assessor/pyproject.toml services/assessor/pyproject.toml

# Resolve dependencies for the api workspace member only (no project install).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --package api --no-dev

# Now copy the actual source for api + its workspace dependency (core).
COPY packages/core packages/core
COPY services/api services/api

# Install the api package itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package api --no-dev


FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /app /app

EXPOSE 8000

# uvicorn entrypoint; bind 0.0.0.0:8000 so the container is reachable from
# the compose network. No --reload, no --workers (single process is fine for
# the operator-internal MVP; horizontal scale is a Phase 4+ concern).
ENTRYPOINT ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
