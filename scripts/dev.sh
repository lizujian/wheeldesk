#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

cd "$ROOT"
env -u SSLKEYLOGFILE .venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$API_PORT" &
api_pid=$!

cd "$ROOT/frontend"
pnpm dev --host 127.0.0.1 --port "$WEB_PORT" &
web_pid=$!

cleanup() {
  kill "$api_pid" "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
wait

