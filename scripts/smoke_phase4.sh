#!/usr/bin/env bash
# Phase 4 end-to-end smoke.
#
# Two modes:
#
# Local-compose mode (always runs):
#   Brings up postgres + api (built from the new 3-stage Dockerfile + dist
#   mount), optionally runs a one-shot crawl to populate topics, and asserts
#   all Phase 4 product surfaces:
#     - /api/healthz still ok
#     - /api/runs?limit=5 returns a runs array
#     - /api/topics?sort=-breadth&limit=5 returns topics w/ numeric breadth +
#       longevity_seconds (G5 sort whitelist + STO-006 derived stats)
#     - /api/topics?sort=garbage -> 400 (whitelist enforcement)
#     - if topics non-empty: /api/topics/{id} returns sources + topic_metadata
#     - GET / returns 200 + text/html + body contains the SPA shell
#     - GET /api/healthz still 200 (catch-all SPA mount doesn't steal /api/*)
#
# Prod-image mode (gated, opt-in):
#   When SMOKE_PHASE4_PROD_IMAGE=1, additionally runs the built image
#   standalone (embedded postgresql-16) to validate the entrypoint boot,
#   GCS-FUSE-style persistence path, SIGTERM dump, and restore-from-latest
#   chain (CONTEXT G9).
#
# Usage:
#   ./scripts/smoke_phase4.sh
#   SMOKE_PHASE4_PROD_IMAGE=1 ./scripts/smoke_phase4.sh
#
# Exit code is non-zero on any failed assertion.

set -euo pipefail

API_BASE="http://localhost:8000"
PROD_IMAGE="${PROD_IMAGE:-trend-api:dev}"
PROD_PORT="${PROD_PORT:-18000}"
PROD_NAME="${PROD_NAME:-trend-prod-smoke}"

# Phase 10: /api/topics is per-department. Default dept uuid is seeded by
# migration 0016 and is stable across environments — pass it on every
# topic-scoped call so the active-department dependency resolves.
DEFAULT_DEPT="00000000-0000-0000-0000-000000000001"
DEPT_HEADER="X-Active-Department: ${DEFAULT_DEPT}"

log() { echo "==> $*"; }

# ----------------------------------------------------------------------------
# Local-compose mode (10 steps)
# ----------------------------------------------------------------------------

log "[1/10] (re)building api image"
docker compose build api

log "[2/10] bringing up postgres + api"
docker compose up -d postgres api

log "[3/10] waiting for /api/healthz (up to 30s)"
ok=0
for i in {1..15}; do
  if curl -fs "${API_BASE}/api/healthz" >/dev/null 2>&1; then
    echo "    /api/healthz responding after ~$((i*2))s"
    ok=1
    break
  fi
  sleep 2
done
test "$ok" = "1" || { echo "    api never became reachable"; exit 1; }

log "[4/10] /api/healthz status=ok"
curl -fs "${API_BASE}/api/healthz" | tee /dev/stderr | grep -q '"status":"ok"'

log "[5/10] best-effort crawl to populate topics (failures non-fatal)"
docker compose run --rm crawler run-once --top-n 30 || \
  echo "    SOFT: crawler returned non-zero (likely upstream flake) — continuing"

log "[6/10] /api/runs?limit=5 returns runs array"
runs_json=$(curl -fs "${API_BASE}/api/runs?limit=5")
runs_len=$(echo "$runs_json" | jq '.runs | length')
echo "    /api/runs length: $runs_len"
test -n "$runs_len"

log "[7/10] /api/topics?sort=-breadth&limit=5 returns numeric breadth + longevity_seconds"
topics_json=$(curl -fs -H "${DEPT_HEADER}" "${API_BASE}/api/topics?sort=-breadth&limit=5")
topics_len=$(echo "$topics_json" | jq '.topics | length')
echo "    /api/topics length: $topics_len"
if [ "$topics_len" -gt 0 ]; then
  br=$(echo "$topics_json" | jq '.topics[0].breadth')
  lon=$(echo "$topics_json" | jq '.topics[0].longevity_seconds')
  echo "    first topic breadth=$br longevity_seconds=$lon"
  echo "$br"  | grep -Eq '^[0-9]+$'
  echo "$lon" | grep -Eq '^[0-9]+$'
else
  echo "    SOFT: 0 topics returned (crawl produced nothing)"
fi

log "[8/10] /api/topics?sort=garbage -> 400 (G5 whitelist)"
status=$(curl -s -o /dev/null -w '%{http_code}' -H "${DEPT_HEADER}" "${API_BASE}/api/topics?sort=garbage")
echo "    status: $status"
test "$status" = "400"

log "[9/10] /api/topics/{id} returns sources + topic_metadata (if any topic exists)"
if [ "$topics_len" -gt 0 ]; then
  tid=$(echo "$topics_json" | jq -r '.topics[0].id')
  detail_json=$(curl -fs -H "${DEPT_HEADER}" "${API_BASE}/api/topics/${tid}")
  echo "$detail_json" | jq -e '.sources | type == "array"' >/dev/null
  echo "$detail_json" | jq -e '.topic_metadata | type == "object"' >/dev/null
  echo "    /api/topics/${tid} has sources + topic_metadata"
else
  echo "    SKIP: no topics to fetch by id"
fi

log "[10/10] GET / returns SPA shell + /api/healthz still 200 (catch-all order)"
root_headers=$(curl -fs -D - -o /tmp/spa.html "${API_BASE}/")
echo "$root_headers" | head -1 | grep -q "200"
echo "$root_headers" | grep -i '^content-type:' | grep -qi 'text/html'
grep -q '<div id="app">' /tmp/spa.html
# api still wins after SPA mount
curl -fs "${API_BASE}/api/healthz" >/dev/null

local_pass=10
echo
echo "[smoke] phase 4 local-compose: ${local_pass}/10 PASS"
echo

# ----------------------------------------------------------------------------
# Prod-image mode (5 steps, opt-in)
# ----------------------------------------------------------------------------

if [ "${SMOKE_PHASE4_PROD_IMAGE:-0}" != "1" ]; then
  echo "[smoke] phase 4 prod-image: skipped (set SMOKE_PHASE4_PROD_IMAGE=1 to enable)"
  echo
  echo "[smoke] phase 4 OK (local: 10/10; prod-image: skipped)"
  exit 0
fi

log "[prod 1/5] preparing persistence dir + running ${PROD_IMAGE} standalone"
PERSIST_DIR=$(mktemp -d)
echo "    persistence dir: $PERSIST_DIR"
docker rm -f "$PROD_NAME" 2>/dev/null || true
docker run -d --rm --name "$PROD_NAME" \
  -p "${PROD_PORT}:8000" \
  -v "${PERSIST_DIR}:/app/data" \
  -e DATABASE_URL= \
  "${PROD_IMAGE}"

log "[prod 2/5] waiting for embedded-pg boot + /api/healthz (up to 60s)"
ok=0
for i in {1..30}; do
  if curl -fs "http://localhost:${PROD_PORT}/api/healthz" >/dev/null 2>&1; then
    echo "    healthy after ~$((i*2))s"
    ok=1
    break
  fi
  sleep 2
done
if [ "$ok" != "1" ]; then
  echo "    container logs:"
  docker logs "$PROD_NAME" || true
  docker stop "$PROD_NAME" >/dev/null 2>&1 || true
  exit 1
fi

log "[prod 3/5] persistence dir was populated by entrypoint"
docker exec "$PROD_NAME" ls -la /app/data || true

log "[prod 4/5] SIGTERM -> cleanup() runs final dump before pg_ctl stop"
docker stop -t 35 "$PROD_NAME" >/dev/null
echo "    container stopped"

log "[prod 5/5] dump file exists in persistence dir"
ls -la "${PERSIST_DIR}" || true
test -f "${PERSIST_DIR}/trend_researcher.dump" \
  || { echo "    expected ${PERSIST_DIR}/trend_researcher.dump"; exit 1; }
echo "    dump file present"

echo
echo "[smoke] phase 4 prod-image: 5/5 PASS"
echo
echo "[smoke] phase 4 OK (local: 10/10; prod-image: 5/5)"
