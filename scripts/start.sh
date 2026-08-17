#!/usr/bin/env bash
# Start Zargar (macOS / Linux):  ./scripts/start.sh
# Brings up Postgres (Docker), rebuilds the UI if sources changed, then runs
# the engine + API + UI as one process on http://127.0.0.1:8420
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ "${SKIP_DOCKER:-0}" != "1" ] && command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  docker compose up -d
  # wait for postgres to accept connections
  for _ in $(seq 1 30); do
    docker compose exec -T db pg_isready -U zargar >/dev/null 2>&1 && break
    sleep 1
  done
fi

# rebuild the UI only when sources are newer than the last build
if [ ! -d frontend/dist ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist -print -quit 2>/dev/null)" ]; then
  echo "▸ Rebuilding frontend"
  (cd frontend && npm run build)
fi

echo "▸ Zargar → http://127.0.0.1:8420"
cd backend
exec .venv/bin/python -m zargar.main
