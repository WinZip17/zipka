#!/usr/bin/env bash
# Shell-обёртка для JetBrains Run на Linux.
# В Flatpak (Bazzite / WebStorm из Flathub) выполняет скрипт на ХОСТЕ.
# Иначе — обычный /bin/bash.
set -euo pipefail

run_host() {
  local cwd="$1"
  shift
  flatpak-spawn --host bash -lc "cd $(printf %q "$cwd") && exec $(printf '%q ' "$@")"
}

cwd="$(pwd)"

if [[ -f /.flatpak-info ]] && command -v flatpak-spawn >/dev/null 2>&1; then
  if [[ $# -eq 0 ]]; then
    run_host "$cwd" bash -l
  fi
  # JetBrains передаёт: script_path [script_options...]
  run_host "$cwd" bash "$@"
fi

if [[ $# -eq 0 ]]; then
  exec /bin/bash -l
fi
exec /bin/bash "$@"
