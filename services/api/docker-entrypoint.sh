#!/bin/bash
set -eu

# =============================================================================
# Docker Entrypoint - Trend Researcher (api service)
# =============================================================================
# Starts embedded PostgreSQL 16 (when no external DATABASE_URL is provided)
# and then the FastAPI application via uvicorn.
#
# Environment variables:
#   DATABASE_URL  - If set (and not "embedded"), skip embedded PostgreSQL
#                   and assume an external Postgres is reachable.
#   PORT          - App port (default: 8000)
#   PERSIST_DIR   - Where dumps live (default: /app/data). Mount a volume here
#                   (e.g. GCS FUSE on Cloud Run) for durable storage.
#
# Persistence model (G9):
#   - On boot: restore from $DUMP_FILE -> $DUMP_PREV -> fresh-schema fallback
#   - During runtime: debounced post-write dumps via DumpDebouncer middleware
#   - On SIGTERM/SIGINT/SIGQUIT: best-effort final dump THEN pg_ctl stop
# =============================================================================

PG_DATA="${PG_DATA:-/var/lib/postgresql/data}"
PG_LOG="${PG_LOG:-/var/log/postgresql/startup.log}"
PG_USER="${PG_USER:-trend_app}"
PG_DB="${PG_DB:-trend_researcher}"
PG_PASS="trend_embedded_$(hostname)"

# ---------------------------------------------------------------------------
# Persistence via mounted volume (dump/restore strategy)
# ---------------------------------------------------------------------------
# GCS FUSE doesn't support chown/chmod, so PG can't run directly on it.
# Instead: restore from dump on startup, dump on shutdown + post-write debounced.
#
# Dump rotation:
#   $DUMP_FILE       - latest known-good dump
#   $DUMP_FILE.prev  - previous dump (fallback if latest is corrupt)
#   $DUMP_FILE.tmp   - in-progress dump (atomic write target)
PERSIST_DIR="${PERSIST_DIR:-/app/data}"
DUMP_FILE="$PERSIST_DIR/${PG_DB}.dump"
DUMP_PREV="$DUMP_FILE.prev"
DUMP_TMP="$DUMP_FILE.tmp"
HAS_PERSISTENCE=false

# Export for the dump helper script invoked by middleware
export PG_DB PG_DATA PERSIST_DIR DUMP_FILE DUMP_PREV DUMP_TMP

if [ -d "$PERSIST_DIR" ] && [ -w "$PERSIST_DIR" ]; then
  HAS_PERSISTENCE=true
  echo "[entrypoint] Persistent storage available at $PERSIST_DIR"
fi

# ---------------------------------------------------------------------------
# Start embedded PostgreSQL if no external DATABASE_URL
# ---------------------------------------------------------------------------
if [ -z "${DATABASE_URL:-}" ] || [ "${DATABASE_URL:-}" = "embedded" ]; then
  echo "[entrypoint] Starting embedded PostgreSQL 16..."

  # Ensure directories exist
  mkdir -p /var/log/postgresql
  chown postgres:postgres /var/log/postgresql

  # Initialize data directory if needed
  if [ ! -f "$PG_DATA/PG_VERSION" ]; then
    echo "[entrypoint] Initializing PostgreSQL data directory..."
    mkdir -p "$PG_DATA"
    chown -R postgres:postgres /var/lib/postgresql
    su - postgres -c "/usr/lib/postgresql/16/bin/initdb -D $PG_DATA --auth=trust --encoding=UTF8 --locale=C"
  fi

  # Configure PostgreSQL for local connections
  echo "local all all trust" > "$PG_DATA/pg_hba.conf"
  echo "host all all 127.0.0.1/32 md5" >> "$PG_DATA/pg_hba.conf"
  echo "host all all ::1/128 md5" >> "$PG_DATA/pg_hba.conf"

  # Start PostgreSQL
  su - postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D $PG_DATA -l $PG_LOG start -w -t 30"

  # Create user and database if they don't exist
  su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='$PG_USER'\" | grep -q 1" || \
    su - postgres -c "psql -c \"CREATE USER $PG_USER WITH PASSWORD '$PG_PASS'\""

  # Embedded single-tenant container: app role is also DB superuser so that
  # data-migration / restore tools can defer FK checks during bulk loads.
  # No multi-tenant exposure here.
  su - postgres -c "psql -c \"ALTER ROLE $PG_USER SUPERUSER\""

  su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='$PG_DB'\" | grep -q 1" || \
    su - postgres -c "psql -c \"CREATE DATABASE $PG_DB OWNER $PG_USER\""

  # Grant privileges
  su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE $PG_DB TO $PG_USER\""

  export DATABASE_URL="postgresql+asyncpg://$PG_USER:$PG_PASS@localhost:5432/$PG_DB"
  echo "[entrypoint] Embedded PostgreSQL ready"

  # -------------------------------------------------------------------------
  # Restore from dump with fallback chain: latest -> .prev -> fresh
  # -------------------------------------------------------------------------
  restore_from() {
    local src="$1"
    echo "[entrypoint] Restoring database from $src..."
    local staging="/tmp/restore.dump"
    cp "$src" "$staging" && chown postgres:postgres "$staging"
    if su - postgres -c "pg_restore --clean --if-exists --no-owner --no-privileges --single-transaction --disable-triggers -d $PG_DB $staging" 2>&1; then
      rm -f "$staging"
      echo "[entrypoint] Database restored from $src"
      return 0
    fi
    rm -f "$staging"
    return 1
  }

  if [ "$HAS_PERSISTENCE" = true ]; then
    RESTORED=false
    if [ -f "$DUMP_FILE" ] && [ -s "$DUMP_FILE" ]; then
      if restore_from "$DUMP_FILE"; then
        RESTORED=true
      else
        echo "[entrypoint] WARNING: latest dump appears corrupt, trying previous..."
      fi
    fi
    if [ "$RESTORED" = false ] && [ -f "$DUMP_PREV" ] && [ -s "$DUMP_PREV" ]; then
      if restore_from "$DUMP_PREV"; then
        RESTORED=true
        echo "[entrypoint] WARNING: restored from .prev dump (latest was corrupt)"
      else
        echo "[entrypoint] WARNING: previous dump also corrupt"
      fi
    fi
    if [ "$RESTORED" = false ]; then
      if [ -f "$DUMP_FILE" ] || [ -f "$DUMP_PREV" ]; then
        echo "[entrypoint] !!! ALL DUMPS FAILED TO RESTORE - starting with empty schema !!!"
      else
        echo "[entrypoint] No persistent dump found - starting fresh"
      fi
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Run Alembic migrations against whichever DATABASE_URL is now in effect
# ---------------------------------------------------------------------------
echo "[entrypoint] Running Alembic migrations..."
(cd /app/packages/core && /app/.venv/bin/alembic upgrade head)

# ---------------------------------------------------------------------------
# Set defaults for app and dump middleware
# ---------------------------------------------------------------------------
export PORT="${PORT:-8000}"
export PERSIST_DIR="${PERSIST_DIR:-/app/data}"
export DB_DUMP_SCRIPT="${DB_DUMP_SCRIPT:-/app/scripts/pg-dump-rotate.sh}"
export DB_DUMP_DEBOUNCE_MS="${DB_DUMP_DEBOUNCE_MS:-30000}"

echo "[entrypoint] Starting Trend Researcher API on port $PORT..."

# ---------------------------------------------------------------------------
# Graceful shutdown: final dump then stop PostgreSQL
# ---------------------------------------------------------------------------
# Ordering matters: dump BEFORE pg_ctl stop so the last writes are captured.
# Post-write debounced dumps already bound data loss to ~30s during runtime.
cleanup() {
  echo "[entrypoint] Shutting down..."
  if [ -n "${API_PID:-}" ] && kill -0 "$API_PID" 2>/dev/null; then
    echo "[entrypoint] Stopping API (PID $API_PID)..."
    kill -TERM "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  if [ -f "$PG_DATA/postmaster.pid" ]; then
    if [ "$HAS_PERSISTENCE" = true ] && [ -x "$DB_DUMP_SCRIPT" ]; then
      echo "[entrypoint] Final dump on shutdown..."
      "$DB_DUMP_SCRIPT" || echo "[entrypoint] Warning: final dump failed (recent debounced dump should still be on disk)"
    fi
    echo "[entrypoint] Stopping PostgreSQL..."
    su - postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D $PG_DATA stop -m fast -w -t 30" 2>/dev/null || true
    echo "[entrypoint] PostgreSQL stopped"
  fi
  exit 0
}
trap cleanup SIGTERM SIGINT SIGQUIT

# ---------------------------------------------------------------------------
# Start FastAPI application
# ---------------------------------------------------------------------------
/app/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port "$PORT" &
API_PID=$!
wait "$API_PID"
