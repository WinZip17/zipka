# Локальные GGUF для Зипки

Роли (можно выбрать любой `*.gguf` из этой папки на каждую роль, в т.ч. одну и ту же):

| Роль | По умолчанию | Зачем |
|------|----------------|--------|
| **Чат** | `Pathfinder-RP-12B-RU.Q4_K_M.gguf` (~7.5 GB) | личность / живой русский |
| **Кодинг** | `Qwen2.5-7B-Instruct-Q5_K_M.gguf` (~5.4 GB) | патчи / инструкции / JSON |

Другие файлы в папке (например `Qwen3-8B-Q4_K_M.gguf`) тоже доступны в UI.

Legacy id для скачивания / CLI: `pathfinder`, `qwen25`.

## Скачать

Из корня проекта (venv активен):

```bat
python -m zipka.tools.download_chat_models --list
python -m zipka.tools.download_chat_models --id all
```

или:

```bat
python -m zipka.main models download --id all
python -m zipka.main models use pathfinder
```

Вручную:

- Pathfinder: https://huggingface.co/roleplaiapp/Pathfinder-RP-12B-RU-Q4_K_M-GGUF
- Qwen2.5: https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF (`Qwen2.5-7B-Instruct-Q5_K_M.gguf`)

Положи файлы сюда (`data/models/`).

## Переключение

- UI: **Настройки → Модели GGUF** (чат + кодинг отдельно)
- CLI: `python -m zipka.main models use pathfinder` (или имя файла `.gguf`) — меняет роль **чата**
- `.env`: `ZIPKA_CHAT_MODEL=pathfinder` (стартовое; `data/settings/runtime.json` перекрывает)
- Runtime: `chat_gguf` / `code_gguf` в `data/settings/runtime.json`

Compute (CPU / GPU / hybrid): настройки UI. Для Pathfinder на 8GB VRAM удобнее **hybrid** или одна модель на обе роли.

## Vision (глаза без Ollama)

Нужна пара файлов: text GGUF + `*mmproj*.gguf`.

```bat
python -m zipka.main models download --id moondream2
```

Файлы (~3.5 GB суммарно):

- `moondream2-text-model-f16_ct-vicuna.gguf`
- `moondream2-mmproj-f16-20250414.gguf`

Любая другая LLaVA/MiniCPM-V пара с mmproj в этой папке тоже подхватится автоматически.
