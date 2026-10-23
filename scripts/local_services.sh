#!/usr/bin/env bash
# Manage the user-space PostgreSQL and Redis instances used for local development.
#
# This is useful on machines where Docker is unavailable and Homebrew's prefix
# is not writable. It expects PostgreSQL/Redis installed with:
#
#   conda create -p "$HOME/.local/share/compliance-services" \
#     -c conda-forge postgresql=16 redis-server
#
# Override any path with the corresponding environment variable.
set -euo pipefail

SERVICES_PREFIX="${COMPLIANCE_SERVICES_PREFIX:-$HOME/.local/share/compliance-services}"
PGDATA="${COMPLIANCE_PGDATA:-$HOME/.local/share/compliance-pgdata}"
PGLOG="${COMPLIANCE_PGLOG:-$HOME/.local/share/compliance-pg.log}"
REDIS_DIR="${COMPLIANCE_REDIS_DIR:-$HOME/.local/share/compliance-redis}"
PGPORT="${PGPORT:-5432}"
REDIS_PORT="${REDIS_PORT:-6379}"

PG_CTL="$SERVICES_PREFIX/bin/pg_ctl"
INITDB="$SERVICES_PREFIX/bin/initdb"
PSQL="$SERVICES_PREFIX/bin/psql"
CREATEDB="$SERVICES_PREFIX/bin/createdb"
REDIS_SERVER="$SERVICES_PREFIX/bin/redis-server"
REDIS_CLI="$SERVICES_PREFIX/bin/redis-cli"

require_binaries() {
  local missing=()
  for binary in "$PG_CTL" "$INITDB" "$PSQL" "$CREATEDB" "$REDIS_SERVER" "$REDIS_CLI"; do
    [[ -x "$binary" ]] || missing+=("$binary")
  done
  if ((${#missing[@]})); then
    echo "Missing local service binaries:" >&2
    printf '  %s\n' "${missing[@]}" >&2
    echo "Install them into $SERVICES_PREFIX or set COMPLIANCE_SERVICES_PREFIX." >&2
    exit 1
  fi
}

pg_running() {
  "$PG_CTL" -D "$PGDATA" status >/dev/null 2>&1
}

redis_running() {
  "$REDIS_CLI" -p "$REDIS_PORT" ping >/dev/null 2>&1
}

start() {
  require_binaries
  mkdir -p "$PGDATA" "$REDIS_DIR"

  if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
    echo "Initialising PostgreSQL cluster in $PGDATA"
    "$INITDB" -D "$PGDATA" -U compliance --auth=trust --encoding=UTF8 --locale=C >/dev/null
  fi

  if pg_running; then
    echo "PostgreSQL already running on port $PGPORT"
  else
    echo "Starting PostgreSQL on port $PGPORT"
    "$PG_CTL" -D "$PGDATA" -l "$PGLOG" -o "-p $PGPORT -k /tmp" start
  fi

  if ! "$PSQL" -h localhost -p "$PGPORT" -U compliance -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = 'compliance'" | grep -q 1; then
    echo "Creating database 'compliance'"
    "$CREATEDB" -h localhost -p "$PGPORT" -U compliance compliance
  fi

  if redis_running; then
    echo "Redis already running on port $REDIS_PORT"
  else
    echo "Starting Redis on port $REDIS_PORT"
    "$REDIS_SERVER" --port "$REDIS_PORT" --bind 127.0.0.1 --daemonize yes \
      --dir "$REDIS_DIR" --appendonly yes \
      --logfile "$REDIS_DIR/redis.log" --pidfile "$REDIS_DIR/redis.pid"
  fi

  status
}

stop() {
  require_binaries
  if pg_running; then
    echo "Stopping PostgreSQL"
    "$PG_CTL" -D "$PGDATA" stop -m fast >/dev/null
  else
    echo "PostgreSQL is not running"
  fi

  if redis_running; then
    echo "Stopping Redis"
    "$REDIS_CLI" -p "$REDIS_PORT" shutdown >/dev/null 2>&1 || true
  else
    echo "Redis is not running"
  fi
}

status() {
  require_binaries
  if pg_running; then
    echo "PostgreSQL: running (port $PGPORT)"
  else
    echo "PostgreSQL: stopped"
  fi

  if redis_running; then
    echo "Redis:      running (port $REDIS_PORT)"
  else
    echo "Redis:      stopped"
  fi
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}" >&2
    exit 2
    ;;
esac
