#!/usr/bin/env bash
# Starts the FastAPI gateway and the ARQ worker together in one container.
# Both processes run in the foreground; if either exits, the container stops.
set -euo pipefail

echo "Starting PR Reviewer..."
echo "  → FastAPI gateway on :8000"
echo "  → ARQ worker"

# Start the ARQ worker in the background
arq prreviewer.queue.WorkerSettings &
ARQ_PID=$!

# Start uvicorn in the foreground (Fly health checks hit /healthz)
uvicorn prreviewer.app:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# If either process exits, kill the other and exit
trap 'kill $ARQ_PID $UVICORN_PID 2>/dev/null; exit 1' EXIT

wait -n $ARQ_PID $UVICORN_PID
