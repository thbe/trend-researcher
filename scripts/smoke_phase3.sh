#!/usr/bin/env bash
# Phase 3 end-to-end smoke.
#
# Brings up the full Phase 3 stack (postgres + api + scheduler), triggers 3
# manual crawls back-to-back (we deliberately do NOT wait 12h for a real cron
# tick — the post-close 24-48h real-cron observation is recorded separately in
# .planning/phases/03-scheduler-ops-baseline/SMOKE-RESULTS.md), then asserts:
#
#   - 3 new rows in crawl_runs (one per trigger)
#   - /api/healthz returns "status":"ok"
#   - scheduler container loaded its crontab
#   - /api/runs?limit=5 returns the 3 rows
#
# Hits the real internet (HN + NYT + Google News). Manual run only.
#
# Usage:
#   ./scripts/smoke_phase3.sh
#
# Exit code is non-zero if any step fails (set -e). Per-source fetch failures
# inside a crawl are NOT fatal here (the crawler logs them in failed_sources
# on the crawl_runs row); inspect output and crawl_runs.failed_sources to
# decide whether the soft-pass criteria are met.
set -euo pipefail

# psql access via docker exec (no host psql required)
PSQL="docker compose exec -T postgres psql -U trend -d trend_researcher -t -A"

echo "==> [1/17] tearing down any prior compose state"
docker compose down -v

echo "==> [2/17] (re)building crawler + api + scheduler images for Phase 3"
docker compose build crawler api scheduler

echo "==> [3/17] bringing up postgres"
docker compose up -d postgres
for i in {1..30}; do
  if docker compose ps postgres --format '{{.Status}}' | grep -q "healthy"; then
    echo "    postgres healthy after ${i}s"
    break
  fi
  sleep 1
done

echo "==> [4/17] applying migrations from host (0001 + 0002)"
uv run --package core alembic -c packages/core/alembic.ini upgrade head

echo "==> [5/17] bringing up api + scheduler"
docker compose up -d api scheduler
sleep 5

echo "==> [6/17] /api/healthz sanity"
curl -fs localhost:8000/api/healthz | tee /dev/stderr | grep -q '"status":"ok"'

echo "==> [7/17] scheduler crontab loaded"
docker logs trend-scheduler 2>&1 | grep -q "starting crond"

echo "==> [8/17] FIRST trigger: docker compose run --rm crawler run-once --top-n 30"
docker compose run --rm crawler run-once --top-n 30
n1=$($PSQL -c "SELECT count(*) FROM crawl_runs;")
echo "    crawl_runs count after trigger 1: $n1"
test "$n1" = "1"

echo "==> [9/17] SECOND trigger"
docker compose run --rm crawler run-once --top-n 30
n2=$($PSQL -c "SELECT count(*) FROM crawl_runs;")
echo "    crawl_runs count after trigger 2: $n2"
test "$n2" = "2"

echo "==> [10/17] THIRD trigger"
docker compose run --rm crawler run-once --top-n 30
n3=$($PSQL -c "SELECT count(*) FROM crawl_runs;")
echo "    crawl_runs count after trigger 3: $n3"
test "$n3" = "3"

echo "==> [11/17] observation_count advance check (soft: expect >= 1 topic at obs>=2)"
multi=$($PSQL -c "SELECT count(*) FROM topics WHERE observation_count >= 2;")
echo "    topics with observation_count >= 2: $multi"
if [ "$multi" -lt 1 ]; then
  echo "    SOFT WARN: no topic was observed on >=2 of the 3 immediate runs (upstream front-page churn?)"
fi

echo "==> [12/17] /api/runs?limit=5 returns 3 rows newest-first"
runs_len=$(curl -fs "localhost:8000/api/runs?limit=5" | jq '.runs | length')
echo "    /api/runs returned: $runs_len rows"
test "$runs_len" = "3"

echo "==> [13/17] failed_sources discipline (printed for inspection — not asserted)"
docker compose exec -T postgres psql -U trend -d trend_researcher \
  -c "SELECT started_at, failed_sources FROM crawl_runs ORDER BY started_at DESC LIMIT 3;"

echo "==> [14/17] per-run summary table"
docker compose exec -T postgres psql -U trend -d trend_researcher \
  -c "SELECT started_at, totals_inserted, totals_updated, totals_errors, failed_sources
      FROM crawl_runs
      ORDER BY started_at;"

echo "==> [15/17] disabled-source verification hint (not run by this script)"
echo "    To verify CRAWLER_DISABLED_SOURCES, run:"
echo "      CRAWLER_DISABLED_SOURCES=hackernews docker compose run --rm crawler run-once --top-n 5"

echo "==> [16/17] teardown (keep volume so operator can post-mortem)"
docker compose down

echo "==> [17/17] Phase 3 smoke PASS"
