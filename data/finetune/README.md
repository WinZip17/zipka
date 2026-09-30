# Finetune runtime (ignored by git)

Локальные артефакты дообучения. После клона папка создаётся при первом `дообучись`.

| Путь | Назначение | В git? |
|------|------------|--------|
| `lineage.json` | поколение, active checkpoint/GGUF | нет |
| `pending.json` / `status.json` | предложение и статус job | нет |
| `jobs/` | job json + логи | нет |
| `datasets/` | jsonl для LoRA | нет |
| `adapters/gen_N/` | LoRA (~сотни МБ) | нет |
| `checkpoints/gen_N/` | HF после merge (~15 ГБ на 8B) | нет |

Экспорт GGUF лежит в `data/models/` (тоже игнорируется).
