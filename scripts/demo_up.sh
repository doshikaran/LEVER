#!/usr/bin/env bash
# Start Lever API + Vite frontend for a local judge demo.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Missing .venv — create it and install requirements first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

mkdir -p data

API_PORT="${LEVER_API_PORT:-8765}"
WEB_PORT="${LEVER_WEB_PORT:-5173}"

cleanup() {
  if [[ -n "${API_PID:-}" ]]; then kill "$API_PID" 2>/dev/null || true; fi
  if [[ -n "${WEB_PID:-}" ]]; then kill "$WEB_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

echo "Starting API on http://127.0.0.1:${API_PORT} …"
uvicorn interface.api:app --host 127.0.0.1 --port "$API_PORT" --reload &
API_PID=$!

echo "Starting frontend on http://127.0.0.1:${WEB_PORT} …"
(
  cd frontend
  VITE_LEVER_API_BASE="http://127.0.0.1:${API_PORT}" npm run dev -- --host 127.0.0.1 --port "$WEB_PORT"
) &
WEB_PID=$!

sleep 2
if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:${WEB_PORT}"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:${WEB_PORT}"
fi

echo
echo "Lever demo is up."
echo "  UI:  http://127.0.0.1:${WEB_PORT}"
echo "  API: http://127.0.0.1:${API_PORT}/health"
echo "Rehearse: docs/DEMO_SCRIPT.md"
echo "Ctrl+C to stop."

wait
