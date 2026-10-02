#!/usr/bin/env bash
# Zipka — Web UI (Linux / macOS / Git Bash)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
if [[ -f "$ROOT/setup_zipka.sh" ]]; then
  # переиспользуем resolve через вызов функций нельзя без source —
  # дублируем лёгкий PATH bootstrap
  export PATH="${HOME}/.local/bin:${HOME}/.npm-global/bin:${PATH:-/usr/bin}"
  if [[ -x /home/linuxbrew/.linuxbrew/bin/brew ]]; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)" 2>/dev/null || true
  fi
  if [[ -s "${HOME}/.nvm/nvm.sh" ]]; then
    export NVM_DIR="${HOME}/.nvm"
    # shellcheck disable=SC1091
    . "${NVM_DIR}/nvm.sh" 2>/dev/null || true
  fi
  if command -v fnm >/dev/null 2>&1; then
    eval "$(fnm env)" 2>/dev/null || true
  fi
fi

if [[ -x .venv/bin/python ]]; then
  PY=".venv/bin/python"
elif [[ -f .venv/Scripts/python.exe ]]; then
  PY=".venv/Scripts/python.exe"
else
  echo "[Zipka] Нет .venv — сначала: ./setup_zipka.sh  (без sudo)"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[Zipka] npm не найден — нужен Node.js для React UI (запусти без sudo)"
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
