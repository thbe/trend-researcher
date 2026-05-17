#!/bin/bash
# =============================================================================
# pg-dump-rotate.sh - Atomic PG dump with rotation (trend-researcher)
# =============================================================================
# Strategy:
#   1. Dump to $DUMP_TMP (in-progress; not visible to restore)
#   2. Verify the dump is non-empty and pg_restore --list succeeds
#   3. Rotate: current DUMP_FILE -> DUMP_PREV, DUMP_TMP -> DUMP_FILE
#
# Variables (exported by docker-entrypoint.sh):
#   PG_DB        - database name
#   DUMP_FILE    - latest dump path (e.g. /app/data/trend_researcher.dump)
#   DUMP_PREV    - previous dump path
#   DUMP_TMP     - in-progress dump path
#
# Used by:
#   - docker-entrypoint.sh cleanup() on SIGTERM (final dump)
#   - FastAPI DumpDebouncer middleware (debounced post-write dumps)
#
# Concurrency: A file lock prevents overlapping dumps. The lock is non-blocking
# so concurrent invocations exit immediately (the in-flight dump covers them).
# =============================================================================
set -e

: "${PG_DB:?PG_DB not set}"
: "${DUMP_FILE:?DUMP_FILE not set}"
: "${DUMP_PREV:?DUMP_PREV not set}"
: "${DUMP_TMP:?DUMP_TMP not set}"

LOCK_FILE="${DUMP_FILE}.lock"

# Acquire non-blocking lock. If another dump is running, skip silently.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[pg-dump-rotate] Another dump is in progress, skipping"
  exit 0
fi

START_TS=$(date +%s)
echo "[pg-dump-rotate] Dumping $PG_DB -> $DUMP_TMP"

# Dump to staging path inside /tmp (postgres-writable), then move to mounted dir.
# This avoids any FUSE permission quirks during the long-running pg_dump.
STAGING="/tmp/pg-dump-$$.dump"
trap 'rm -f "$STAGING"' EXIT

if ! su - postgres -c "pg_dump -Fc -f $STAGING $PG_DB" 2>&1; then
  echo "[pg-dump-rotate] ERROR: pg_dump failed"
  exit 1
fi

# Verify the dump is valid before promoting it
if ! su - postgres -c "pg_restore --list $STAGING" > /dev/null 2>&1; then
  echo "[pg-dump-rotate] ERROR: dump verification failed (corrupt output)"
  exit 1
fi

# Move staging to bucket-mounted tmp path
cp "$STAGING" "$DUMP_TMP"

# Atomic rotation:
#   1. Promote current DUMP_FILE to DUMP_PREV (overwriting old prev)
#   2. Promote DUMP_TMP to DUMP_FILE
# On GCS FUSE, mv is atomic at the object level.
if [ -f "$DUMP_FILE" ]; then
  mv -f "$DUMP_FILE" "$DUMP_PREV"
fi
mv -f "$DUMP_TMP" "$DUMP_FILE"

ELAPSED=$(($(date +%s) - START_TS))
SIZE=$(stat -c%s "$DUMP_FILE" 2>/dev/null || echo "?")
echo "[pg-dump-rotate] Dump complete: ${SIZE} bytes in ${ELAPSED}s"
