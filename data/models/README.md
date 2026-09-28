# Локальные GGUF для чата Зипки

Два профиля под RTX 4060 Laptop 8GB:

| Профиль | Файл | Зачем |
|---------|------|--------|
| `pathfinder` | `Pathfinder-RP-12B-RU.Q4_K_M.gguf` (~7.5 GB) | личность / живой русский |
| `qwen25` | `Qwen2.5-7B-Instruct-Q5_K_M.gguf` (~5.4 GB) | запасной чат / инструкции |

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

Положи файлы сюда (`data/models/`), имена как в таблице (или с теми же токенами в имени).

## Переключение

- UI: **Настройки → Модель чата**
- CLI: `python -m zipka.main models use qwen25`
- `.env`: `ZIPKA_CHAT_MODEL=pathfinder` (стартовое значение; UI/runtime перекрывает)

Compute: для Pathfinder на 8GB удобнее **hybrid**.
