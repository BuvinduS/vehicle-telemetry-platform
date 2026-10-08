#!/usr/bin/env bash
# dev.sh — launch the telemetry stack
# Usage: ./dev.sh [--no-ingestor] [--prod]
#   --prod  run the built dashboard (next start) and the bridge without --reload

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_DIR="$ROOT/pi"
FRONTEND_DIR="$PI_DIR/dashboard/frontend"

# Per-machine config (gitignored). Optional: without it, code defaults apply.
if [[ -f "$PI_DIR/.env" ]]; then
  set -a
  source "$PI_DIR/.env"
  set +a
fi

RUN_INGESTOR=true
PROD=false
for arg in "$@"; do
  case "$arg" in
    --no-ingestor) RUN_INGESTOR=false ;;
    --prod)        PROD=true ;;
    *) echo "usage: ./dev.sh [--no-ingestor] [--prod]" >&2; exit 2 ;;
  esac
done

if $PROD && [[ ! -f "$FRONTEND_DIR/.next/BUILD_ID" ]]; then
  echo "[dev] no production build — run: (cd $FRONTEND_DIR && npm run build)" >&2
  exit 1
fi

# Ctrl+C (or any exit) stops everything this script started
cleanup() {
  STOPPING=1
  trap '' INT TERM     # ignore repeat signals while shutting down
  trap - EXIT
  echo "[dev] shutting down..."
  kill 0 2>/dev/null   # signal the group (children included)
  wait                 # block until every child has actually exited
}
trap cleanup INT TERM EXIT

UVICORN_ARGS=(--host 0.0.0.0 --port 8000)
$PROD || UVICORN_ARGS+=(--reload)

echo "[dev] starting FastAPI bridge (:8000)"
( cd "$PI_DIR" && exec .venv/bin/uvicorn dashboard.backend.main:app "${UVICORN_ARGS[@]}" ) &

echo "[dev] starting dashboard"
if $PROD; then
  ( cd "$FRONTEND_DIR" && exec npm run start -- -p 3001 ) &
else
  ( cd "$FRONTEND_DIR" && exec npm run dev ) &
fi

if $RUN_INGESTOR; then
  echo "[dev] starting ingestor"
  ( cd "$PI_DIR" && exec .venv/bin/python3 ingestor/ingestor.py ) &
else
  echo "[dev] ingestor skipped"
fi

if $PROD; then
  # Supervised mode (systemd): if any service dies, stop the rest and exit
  # non-zero so Restart= brings the whole stack back up. This also covers
  # boot-time readiness: the bridge exits until Postgres accepts connections.
  wait -n
  if [[ -z "${STOPPING:-}" ]]; then
    echo "[dev] a service exited unexpectedly — stopping the stack" >&2
    exit 1
  fi
else
  wait
fi