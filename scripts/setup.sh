#!/usr/bin/env bash
# Zargar one-time setup (macOS / Linux).
#   ./scripts/setup.sh
# Checks prerequisites, starts Postgres (Docker), installs backend + frontend,
# builds the UI, and writes backend/.env. After this, run ./scripts/start.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

say()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

# ── prerequisites ────────────────────────────────────────────────────────
command -v git >/dev/null || fail "git not found"
PY="$(command -v python3.12 || command -v python3.11 || command -v python3 || true)"
[ -n "$PY" ] || fail "Python 3.11+ not found — install from https://python.org"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
  || fail "Python 3.11+ required (found $("$PY" -V))"
command -v node >/dev/null || fail "Node.js 20+ not found — install from https://nodejs.org"
node -e 'process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)' \
  || fail "Node.js 20+ required (found $(node -v))"

# ── database ────────────────────────────────────────────────────────────
if [ "${SKIP_DOCKER:-0}" = "1" ]; then
  say "SKIP_DOCKER=1 — assuming Postgres is already running (set ZARGAR_DATABASE_URL)"
elif command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  say "Starting Postgres via Docker Compose"
  docker compose up -d
else
  fail "Docker is not running. Start Docker Desktop and re-run, or run your own
  Postgres 16 and re-run with:  SKIP_DOCKER=1 ./scripts/setup.sh"
fi

# ── backend ─────────────────────────────────────────────────────────────
say "Installing backend (Python)"
cd "$ROOT/backend"
if command -v uv >/dev/null; then
  uv venv --allow-existing .venv
  uv pip install -q -e ".[dev]" --python .venv/bin/python
else
  [ -d .venv ] || "$PY" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -e ".[dev]"
fi

if [ ! -f .env ]; then
  say "Writing backend/.env"
  cp "$ROOT/.env.example" .env
  # serve the built UI straight from the backend — one process, one URL
  sed -i.bak "s|^ZARGAR_FRONTEND_DIST=.*|ZARGAR_FRONTEND_DIST=$ROOT/frontend/dist|" .env && rm -f .env.bak
else
  say "backend/.env already exists — leaving it untouched"
fi

# ── frontend ─────────────────────────────────────────────────────────────
say "Installing + building frontend"
cd "$ROOT/frontend"
npm install --no-fund --no-audit
npm run build

say "Setup complete. Start the app with:  ./scripts/start.sh"
