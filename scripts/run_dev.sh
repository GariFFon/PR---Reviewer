#!/usr/bin/env bash
# Starts Redis (if not already running), the FastAPI gateway, and the ARQ
# worker together for local development. Ctrl-C stops both the gateway and
# the worker.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! redis-cli ping >/dev/null 2>&1; then
  echo "Starting redis-server..."
  redis-server --daemonize yes
fi

trap 'kill 0' EXIT

uvicorn prreviewer.app:app --reload --port 8000 &
arq prreviewer.queue.WorkerSettings &

wait
