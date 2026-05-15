#!/usr/bin/env bash
# Phase 2 multi-source live E2E smoke.
# Runs all registered sources (HN + NYT + Google News — Reddit dropped per
# Plan 02-04 CONTEXT.md "Reddit access reality") twice to prove dedup,
# captures per-source counts, cross-source overlap, and observation
# distribution. Hits the real internet — manual run only.
#
# Usage:
#   ./scripts/smoke_phase2.sh
#
# Exit code is non-zero if any docker / alembic / crawl step fails. Per-source
# fetch failures are NOT fatal here (the crawler logs them in failed_sources and
# continues); inspect output to decide whether the soft-pass criteria are met.
set -euo pipefail

# psql access via docker exec (no host psql required)
PSQL="docker compose exec -T postgres psql -U trend -d trend_researcher"

echo "==> [1/10] tearing down any prior compose state"
docker compose down -v

echo "==> [2/10] bringing up postgres"
docker compose up -d postgres

echo "==> [3/10] waiting for postgres healthy"
for i in {1..30}; do
  if docker compose ps postgres --format '{{.Status}}' | grep -q "healthy"; then
    echo "    postgres healthy after ${i}s"
    break
  fi
  sleep 1
done

echo "==> [4/10] (re)building crawler image to pick up Phase 2 source code"
docker compose build crawler

echo "==> [5/10] applying migrations from host"
uv run --package core alembic -c packages/core/alembic.ini upgrade head

echo "==> [6/10] FIRST CRAWL (--top-n 30 across all registered sources)"
docker compose run --rm crawler run-once --top-n 30

echo "==> [7/10] post-first-crawl inspection"
echo "--- per-source counts (S1) ---"
$PSQL -c "SELECT source_name, count(*) AS n FROM topic_sources GROUP BY source_name ORDER BY n DESC;"

echo "--- total topics + multi-observation distribution ---"
$PSQL -c "SELECT count(*) AS total_topics,
                 sum(CASE WHEN observation_count >= 2 THEN 1 ELSE 0 END) AS multi_observation
          FROM topics;"

echo "--- cross-source dedup spot check (top 10 stories present on >= 2 sources) ---"
$PSQL -c "SELECT t.title, count(DISTINCT ts.source_name) AS source_count
          FROM topics t JOIN topic_sources ts ON ts.topic_id = t.id
          GROUP BY t.id, t.title
          HAVING count(DISTINCT ts.source_name) >= 2
          ORDER BY source_count DESC, t.title
          LIMIT 10;"

echo "==> [8/10] SECOND CRAWL (dedup proof — counts should grow on topic_sources, not topics)"
docker compose run --rm crawler run-once --top-n 30

echo "==> [9/10] post-second-crawl inspection"
echo "--- per-source counts (S2 should be approx 2 * S1) ---"
$PSQL -c "SELECT source_name, count(*) AS n FROM topic_sources GROUP BY source_name ORDER BY n DESC;"

echo "--- total topics (should be ~stable; small delta from genuinely new headlines) ---"
$PSQL -c "SELECT count(*) AS total_topics FROM topics;"

echo "--- observation_count distribution (should skew toward 2 after the second pass) ---"
$PSQL -c "SELECT observation_count, count(*) AS topics_at_this_count
          FROM topics
          GROUP BY observation_count
          ORDER BY observation_count;"

echo "==> [10/10] teardown"
docker compose down

echo "==> done"
