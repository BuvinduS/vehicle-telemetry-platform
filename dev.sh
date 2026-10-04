#!/usr/bin/env bash
# dev.sh — launch the telemetry stack for local development
# Usage: ./dev.sh [--no-ingestor]

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_DIR="$ROOT/pi"
FRONTEND_DIR="$PI_DIR/dashboard/frontend"

if [[ -f "$PI_DIR/.env" ]]; then
  set -a
  source "$PI_DIR/.env"
  set +a
fi

RUN_INGESTOR=true
[[ "${1:-}" == "--no-ingestor" ]] && RUN_INGESTOR=false

# Ctrl+C (or any exit) stops everything this script started
cleanup() {
  trap '' INT TERM     # ignore repeat signals while shutting down
  trap - EXIT
  echo "[dev] shutting down..."
  kill 0 2>/dev/null   # signal the group (children included)
  wait                 # block until every child has actually exited
}
trap cleanup INT TERM EXIT

echo "[dev] starting FastAPI bridge (:8000)"
( cd "$PI_DIR" && exec .venv/bin/uvicorn dashboard.backend.main:app \
    --reload --host 0.0.0.0 --port 8000 ) &

echo "[dev] starting dashboard"
( cd "$FRONTEND_DIR" && exec npm run dev ) &

if $RUN_INGESTOR; then
  echo "[dev] starting ingestor"
  ( cd "$PI_DIR" && exec .venv/bin/python3 ingestor/ingestor.py ) &
else
  echo "[dev] ingestor skipped"
fi

wait