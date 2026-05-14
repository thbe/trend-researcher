# syntax=docker/dockerfile:1.7
# Multi-stage build for trend-researcher crawler service.
# Builder uses uv to resolve the workspace; runtime is plain python:slim with
# the prebuilt /app/.venv copied over. One-shot container (no restart policy).

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

# Resolve dependencies for the crawler workspace member only (no project install).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --package crawler

# Now copy the actual source for crawler + its workspace dependency (core).
COPY packages/core packages/core
COPY services/crawler services/crawler

# Install the crawler package itself (registers the `crawler` entrypoint script).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package crawler


FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /app /app

ENTRYPOINT ["crawler"]
CMD ["run-once"]
