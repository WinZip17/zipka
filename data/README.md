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
| `news/` | источники и выдержки новостей |
| `models/*.gguf` | локальные GGUF для чата |
| `settings/runtime.json` | compute / выбранные модели |

В репозитории: этот README, `persona/persona.example.yaml`, `models/README.md`, `finetune/README.md`, `news/README.md`, `news/sources.example.json`, `settings/runtime.example.json`.
