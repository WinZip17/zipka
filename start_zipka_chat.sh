#!/usr/bin/env bash
# Zipka — чат в терминале
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

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "[Zipka] Чат в терминале. Выход: /quit"
echo
exec "$PY" -m zipka.main chat
