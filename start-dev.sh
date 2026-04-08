#!/usr/bin/env bash
# start-dev.sh – development launcher for Local AI Assistant
# Starts FastAPI server, Vue dev server, and Electron, then cleans up on exit.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$REPO_ROOT/apps/frontend"
DESKTOP_DIR="$REPO_ROOT/apps/desktop"
SERVER_DIR="$REPO_ROOT/server"

FRONTEND_PORT=5173
BACKEND_PORT=8000

# PIDs we need to kill on exit
_PIDS=()

cleanup() {
  echo ""
  echo "[start-dev] Shutting down child processes…"
  for pid in "${_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
  echo "[start-dev] All done."
}
trap cleanup EXIT INT TERM

# ── Dependency check ──────────────────────────────────────────────────────────

install_if_needed() {
  local dir="$1"
  local label="$2"
  if [ ! -d "$dir/node_modules" ]; then
    echo "[start-dev] Installing $label dependencies…"
    (cd "$dir" && npm install)
  fi
}

install_if_needed "$FRONTEND_DIR" "frontend"
install_if_needed "$DESKTOP_DIR"  "desktop"

# ── FastAPI server ────────────────────────────────────────────────────────────

echo "[start-dev] Starting FastAPI server on port $BACKEND_PORT…"
(cd "$SERVER_DIR" && python main.py) &
SERVER_PID=$!
_PIDS+=("$SERVER_PID")
echo "[start-dev]   server PID: $SERVER_PID"

# ── Vue dev server ────────────────────────────────────────────────────────────

echo "[start-dev] Starting Vue dev server on port $FRONTEND_PORT…"
(cd "$FRONTEND_DIR" && npm run dev) &
VITE_PID=$!
_PIDS+=("$VITE_PID")
echo "[start-dev]   vite PID: $VITE_PID"

# ── Wait for both services to be ready ───────────────────────────────────────

wait_for_port() {
  local port="$1"
  local label="$2"
  local retries=30
  echo "[start-dev] Waiting for $label (port $port)…"
  while ! nc -z 127.0.0.1 "$port" 2>/dev/null; do
    retries=$((retries - 1))
    if [ "$retries" -le 0 ]; then
      echo "[start-dev] ERROR: $label did not become ready in time."
      exit 1
    fi
    sleep 1
  done
  echo "[start-dev]   $label is ready."
}

wait_for_port "$BACKEND_PORT"  "FastAPI server"
wait_for_port "$FRONTEND_PORT" "Vue dev server"

# ── Electron ──────────────────────────────────────────────────────────────────

echo "[start-dev] Launching Electron…"
(cd "$DESKTOP_DIR" && npx electron . --dev)
ELECTRON_EXIT=$?

echo "[start-dev] Electron exited with code $ELECTRON_EXIT."
exit $ELECTRON_EXIT
