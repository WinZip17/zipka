#!/usr/bin/env bash
# Zipka — Web UI (Linux / macOS / Git Bash)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -x .venv/bin/python ]]; then
  PY=".venv/bin/python"
elif [[ -f .venv/Scripts/python.exe ]]; then
  PY=".venv/Scripts/python.exe"
else
  echo "[Zipka] Нет .venv — сначала: ./setup_zipka.sh"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[Zipka] npm не найден — нужен Node.js для React UI"
  exit 1
fi

if [[ ! -f web/frontend/dist/index.html ]]; then
  echo "[Zipka] Сборка React UI…"
  (cd web/frontend && npm install && npm run build)
fi

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "[Zipka] Запуск Web UI…"
echo "Открой в браузере: http://127.0.0.1:8765"
echo "Ctrl+C — остановить сервер."
echo
exec "$PY" -m zipka.main web
