#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
APP_URL="http://127.0.0.1:${WEB_PORT}"
HEALTH_URL="http://127.0.0.1:${API_PORT}/api/health"
BROWSER="${WHEELDESK_BROWSER:-Google Chrome}"
DEV_COMMAND="${WHEELDESK_DEV_COMMAND:-$ROOT/scripts/dev.sh}"
READY_ATTEMPTS="${WHEELDESK_READY_ATTEMPTS:-80}"
READY_INTERVAL="${WHEELDESK_READY_INTERVAL:-0.25}"

if [[ -z "${WHEELDESK_DEV_COMMAND:-}" ]]; then
  if [[ ! -x "$ROOT/.venv/bin/uvicorn" || ! -d "$ROOT/frontend/node_modules" ]]; then
    echo "WheelDesk 依赖尚未安装。请先运行：make install" >&2
    exit 1
  fi
fi

echo "正在启动 WheelDesk..."
"$DEV_COMMAND" &
dev_pid=$!

cleanup() {
  if kill -0 "$dev_pid" 2>/dev/null; then
    kill "$dev_pid" 2>/dev/null || true
    wait "$dev_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

ready=false
for ((attempt = 1; attempt <= READY_ATTEMPTS; attempt++)); do
  if ! kill -0 "$dev_pid" 2>/dev/null; then
    wait "$dev_pid" || true
    echo "WheelDesk 启动失败，请检查上方日志。" >&2
    exit 1
  fi
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1 && curl -fsS "$APP_URL" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep "$READY_INTERVAL"
done

if [[ "$ready" != true ]]; then
  echo "WheelDesk 在等待时间内未就绪。" >&2
  exit 1
fi

echo "WheelDesk 已就绪：$APP_URL"
open -a "$BROWSER" "$APP_URL"
echo "已在 $BROWSER 中打开。按 Ctrl+C 停止服务。"

wait "$dev_pid"
