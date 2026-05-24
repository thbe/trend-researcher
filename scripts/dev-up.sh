#!/usr/bin/env bash
# dev-up.sh — start the local Compose stack with the right LLM backend for the host.
#
# Default (Linux et al.): starts postgres + api + crawler + the bundled `ollama`
#                          container at http://ollama:11434.
# macOS                  : skips the `ollama` container; the assessor talks to
#                          oMLX (https://omlx.ai/) running natively on the host
#                          at http://127.0.0.1:8000/v1 (OpenAI-compatible).
#
# Any extra args are forwarded to `docker compose up`, e.g.:
#   scripts/dev-up.sh -d
#   scripts/dev-up.sh --build
set -euo pipefail

cd "$(dirname "$0")/.."

uname_s="$(uname -s)"

case "$uname_s" in
    Darwin)
        echo "[dev-up] macOS detected — skipping Ollama container. Ensure oMLX is running at http://127.0.0.1:8000/v1."
        exec docker compose up postgres api crawler "$@"
        ;;
    Linux)
        echo "[dev-up] Linux detected — starting full stack with Ollama."
        exec docker compose up "$@"
        ;;
    *)
        echo "[dev-up] Host '$uname_s' — starting full stack with Ollama (override ai_config.base_url if you use a different endpoint)."
        exec docker compose up "$@"
        ;;
esac
