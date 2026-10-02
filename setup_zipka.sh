#!/usr/bin/env bash
# Zipka — установка / проверка зависимостей (Linux, macOS, Git Bash на Windows)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

WITH_LLAMA=0
WITH_FINETUNE=0
WITH_RAG=0
SKIP_FRONTEND=0

usage() {
  cat <<'EOF'
Usage: ./setup_zipka.sh [options]

  --with-llama      поставить llama-cpp-python (CPU wheel / pip)
  --with-finetune   pip install -e ".[finetune]"
  --with-rag        pip install -e ".[rag]"
  --skip-frontend   не трогать npm / сборку UI
  -h, --help        эта справка

Не запускай через sudo — Node/npm из user PATH пропадут.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --with-llama) WITH_LLAMA=1 ;;
    --with-finetune) WITH_FINETUNE=1 ;;
    --with-rag) WITH_RAG=1 ;;
    --skip-frontend) SKIP_FRONTEND=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg"; usage; exit 1 ;;
  esac
done

log() { printf '[Zipka setup] %s\n' "$*"; }
die() { printf '[Zipka setup] ERROR: %s\n' "$*" >&2; exit 1; }

# --- не root ---
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  die "Не запускай от root/sudo. Выйди из sudo и запусти: ./setup_zipka.sh
(под sudo нет твоего user PATH — npm/node «пропадают», хотя в обычном терминале есть)."
fi

# --- подтянуть user PATH (nvm/fnm/brew) в non-interactive shell ---
load_user_node_path() {
  export PATH="${HOME}/.local/bin:${HOME}/.npm-global/bin:${PATH:-/usr/bin}"

  if [[ -x /home/linuxbrew/.linuxbrew/bin/brew ]]; then
    # shellcheck disable=SC1091
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
  elif [[ -x "${HOME}/.linuxbrew/bin/brew" ]]; then
    # shellcheck disable=SC1091
    eval "$("${HOME}/.linuxbrew/bin/brew" shellenv)"
  fi

  if [[ -s "${HOME}/.nvm/nvm.sh" ]]; then
    # shellcheck disable=SC1091
    export NVM_DIR="${HOME}/.nvm"
    # shellcheck disable=SC1091
    . "${NVM_DIR}/nvm.sh"
  fi

  if [[ -s "${HOME}/.fnm/fnm" ]] || command -v fnm >/dev/null 2>&1; then
    if command -v fnm >/dev/null 2>&1; then
      eval "$(fnm env)"
    elif [[ -x "${HOME}/.fnm/fnm" ]]; then
      eval "$("${HOME}/.fnm/fnm" env)"
    fi
  fi

  if [[ -s "${HOME}/.volta/bin/volta" ]]; then
    export VOLTA_HOME="${HOME}/.volta"
    export PATH="${VOLTA_HOME}/bin:${PATH}"
  fi

  # asdf
  if [[ -s "${HOME}/.asdf/asdf.sh" ]]; then
    # shellcheck disable=SC1091
    . "${HOME}/.asdf/asdf.sh"
  fi
}

resolve_npm() {
  load_user_node_path
  if command -v npm >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
    return 0
  fi
  local cand
  if [[ -d "${HOME}/.nvm/versions/node" ]]; then
    for cand in "${HOME}/.nvm/versions/node"/*/bin; do
      if [[ -x "${cand}/npm" && -x "${cand}/node" ]]; then
        export PATH="${cand}:${PATH}"
        return 0
      fi
    done
  fi
  for cand in \
    "${HOME}/.local/share/fnm/aliases/default/bin" \
    /home/linuxbrew/.linuxbrew/bin \
    "${HOME}/.linuxbrew/bin" \
    /usr/local/bin
  do
    if [[ -x "${cand}/npm" && -x "${cand}/node" ]]; then
      export PATH="${cand}:${PATH}"
      return 0
    fi
  done
  return 1
}

# --- Python ---
PY_SYS=""
for cand in python3.12 python3.11 python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver="$("$cand" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
    major="${ver%%.*}"
    minor="${ver#*.}"
    if [[ -n "$major" && "$major" -gt 3 ]] || [[ "$major" -eq 3 && "$minor" -ge 11 ]]; then
      PY_SYS="$cand"
      break
    fi
  fi
done
[[ -n "$PY_SYS" ]] || die "Нужен Python 3.11+ (python3 в PATH)"

log "Python: $($PY_SYS --version 2>&1)"

if [[ ! -d .venv ]]; then
  log "Создаю .venv …"
  "$PY_SYS" -m venv .venv
fi

if [[ -x .venv/bin/python ]]; then
  PY=".venv/bin/python"
  PIP=".venv/bin/pip"
elif [[ -f .venv/Scripts/python.exe ]]; then
  PY=".venv/Scripts/python.exe"
  PIP=".venv/Scripts/pip.exe"
else
  die "venv создан, но python внутри не найден"
fi

log "Обновляю pip …"
"$PY" -m pip install -U pip setuptools wheel >/dev/null

log "Ставлю requirements.txt …"
"$PIP" install -r requirements.txt

log "Ставлю пакет zipka (editable) …"
"$PIP" install -e .

if [[ "$WITH_FINETUNE" -eq 1 ]]; then
  log "Ставлю extras [finetune] …"
  "$PIP" install -e ".[finetune]"
fi
if [[ "$WITH_RAG" -eq 1 ]]; then
  log "Ставлю extras [rag] …"
  "$PIP" install -e ".[rag]"
fi

if [[ "$WITH_LLAMA" -eq 1 ]]; then
  log "Ставлю llama-cpp-python …"
  if [[ "$(uname -s)" == "Linux" ]]; then
    "$PIP" install "llama-cpp-python>=0.3.0" || \
      log "WARN: llama-cpp-python не установился (нужен компилятор/CUDA). GGUF будет недоступен."
  else
    "$PIP" install llama-cpp-python --only-binary=:all: \
      --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu || \
      log "WARN: CPU-wheel llama-cpp-python не поставился."
  fi
elif ! "$PY" -c "import llama_cpp" 2>/dev/null; then
  log "llama-cpp-python не найден (ок для Ollama). Позже: ./setup_zipka.sh --with-llama"
fi

# --- .env ---
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    log "Создан .env из .env.example"
  else
    log "WARN: нет .env.example — пропусти .env"
  fi
else
  log ".env уже есть"
fi

# --- Node / frontend ---
if [[ "$SKIP_FRONTEND" -eq 0 ]]; then
  if ! resolve_npm; then
    die "npm/node не найдены в PATH.
В обычном терминале они есть, а здесь — нет (часто nvm/fnm не подхватывается).
Проверь: command -v npm; which node
Запуск: БЕЗ sudo, из каталога проекта:
  chmod +x setup_zipka.sh start_zipka.sh start_zipka_chat.sh tools/ide_host_shell.sh
  ./setup_zipka.sh"
  fi
  log "Node: $(node --version 2>&1), npm: $(npm --version 2>&1) @ $(command -v npm)"
  pushd web/frontend >/dev/null
  if [[ ! -d node_modules ]]; then
    log "npm install …"
    npm install
  else
    log "node_modules есть — npm install (докачка при необходимости) …"
    npm install
  fi
  if [[ ! -f dist/index.html ]]; then
    log "npm run build …"
    npm run build
  else
    log "web/frontend/dist уже собран"
  fi
  popd >/dev/null
else
  log "Frontend пропущен (--skip-frontend)"
fi

mkdir -p data/models data/settings data/memory data/mind

log "Готово."
log "Запуск Web UI:  ./start_zipka.sh"
log "Чат в терминале: ./start_zipka_chat.sh"
log "IDE: Run → Zipka: Web UI (Linux)"
log "URL: http://127.0.0.1:8765"
