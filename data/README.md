# Runtime data (ignored by git)

На клоне папка заполняется при первом запуске Зипки.

| Путь | Назначение |
|------|------------|
| `persona/persona.yaml` | Живой характер (из `persona.example.yaml` при первом старте) |
| `memory/` | чат, заметки, навыки, эволюция, профиль собеседника |
| `mind/` | цели, проактивность |
| `books/` | uploads, extracted, digests |
| `snapshots/` | кадры камеры |
| `patches/` | hard-evolve бэкапы |
| `finetune/` | LoRA/adapters/checkpoints (тяжёлые, только локально) |
| `models/*.gguf` | локальные GGUF для чата |

В репозитории хранится только этот README, `persona/persona.example.yaml`, `models/README.md`, `finetune/README.md` и лёгкие конфиги (`news/sources.json`, `settings/runtime.json`).
