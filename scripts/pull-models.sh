#!/usr/bin/env bash
# Pull pre-configured models into the local Ollama instance.
# Run after `docker compose up -d ollama` is healthy.
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

echo "Waiting for Ollama at $OLLAMA_HOST ..."
until curl -sf "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; do
  sleep 2
done
echo "Ollama is ready."

MODELS=(
  "kimi-k2.6:latest"
  "gemma4:e4b"
  "qwen3.5:latest"
)

for model in "${MODELS[@]}"; do
  echo "Pulling $model ..."
  curl -sf "$OLLAMA_HOST/api/pull" -d "{\"name\": \"$model\"}" | while read -r line; do
    status=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || true)
    [ -n "$status" ] && printf "\r  %s" "$status"
  done
  echo ""
  echo "  ✓ $model pulled"
done

echo "All models ready."
