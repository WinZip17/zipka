# Zipka / Зипка

Локальный саморазвивающийся агент на **Python + Ollama**.

## Возможности

1. Мягкая самоэволюция (характер, навыки, предпочтения)
2. Правки своего кода только после фразы `разрешаю правку кода`
3. Характер Зипки + чтение книг и исходников (txt/md/fb2/py/js/ts/…, zip/rar, папки)
4. Глаза (webcam) и уши (mic + faster-whisper)
5. Цели и рефлексия (псевдоразум)
6. Самообучение по сети (GET, allowlist)
7. CLI + web UI

## Быстрый старт

```bash
# если python в PATH:
python -m venv .venv
# на этой машине venv уже создан через локальный CPython 3.11

.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# в .env укажи модель из `ollama list` (сейчас по умолчанию my_qwen:latest)
python -m zipka.main status
python -m zipka.main chat
python -m zipka.main web
```

Web: http://127.0.0.1:8765

## Запуск ярлыком

1. Один раз создай ярлык на рабочий стол:
   ```bat
   powershell -ExecutionPolicy Bypass -File create_shortcut.ps1
   ```
2. Двойной клик по **Зипка** на рабочем столе → поднимается Web UI.

Файлы запуска в корне проекта:

| Файл | Что делает |
|------|------------|
| `start_zipka.bat` | Web UI (для ярлыка) |
| `start_zipka_chat.bat` | Чат в терминале |
| `create_shortcut.ps1` | Создаёт ярлык «Зипка» на Desktop |

## Как добавить книгу или код

1. **В чате по пути** (CLI или web):
   ```
   прочитай C:\Users\WinZip\Desktop\книга.fb2
   изучи D:\Project2\zipka\zipka\agent.py
   изучи D:\Project2\zipka\zipka
   прочитай D:\books\archive.zip внутри main.py
   что в архиве D:\books\archive.zip
   ```
2. **Загрузить файл в web**: кнопка `+`, блок «Книга / код» или drag-and-drop  
   (книги + исходники: `.py`, `.js`, `.ts`, `.tsx`, `.go`, `.rs`, …).
3. **CLI**:
   ```bash
   python -m zipka.main read PATH
   python -m zipka.main read PATH --list
   python -m zipka.main read PATH -m file.py
   ```

Для кода Зипка делает разбор: назначение, API, зависимости, паттерны (не копирует длинные куски).  
Папка: до 12 исходников (пропуская `node_modules`, `.venv`, `.git`…).  
Заметки кода пишутся в `notes.jsonl` с kind=`code`.

| Команда | Описание |
|--------|----------|
| `python -m zipka.main chat` | REPL-чат |
| `python -m zipka.main evolve "..."` | Мягкая эволюция |
| `python -m zipka.main read PATH` | Книга/код/папка/архив |
| `python -m zipka.main read PATH --list` | Список файлов в архиве |
| `python -m zipka.main read PATH -m file.py` | Файл внутри архива |
| `python -m zipka.main eyes on\|off\|snap` | Камера |
| `python -m zipka.main ears on\|off\|listen` | Микрофон |
| `python -m zipka.main reflect` | Рефлексия |
| `python -m zipka.main learn URL\|тема` | Сеть |
| `python -m zipka.main rollback ID` | Откат патча |
| `python -m zipka.main web` | Web UI |

## Где хранятся знания

Всё лежит в папке `data/`:

| Что | Файл |
|-----|------|
| Заметки из книг, кода, сети, глаз, рефлексии | `data/memory/notes.jsonl` |
| История чата | `data/memory/chat.jsonl` |
| Навыки | `data/memory/skills.json` |
| Предпочтения | `data/memory/preferences.json` |
| Лог эволюции | `data/memory/evolve_log.jsonl` |
| Характер | `data/persona/persona.yaml` |
| Цели / настроение / фокус | `data/mind/state.json` |
| Выжимки книг | `data/books/notes/*_digest.md` |
| Распакованные из zip/rar | `data/books/extracted/` |

Основное хранилище знаний — **`data/memory/notes.jsonl`**: саммари книг (`book`), кода (`code`), обучения по сети (`net_learn`), снимков (`eyes`) и рефлексий (`reflection`).

## Безопасность

- Hard-evolve правит только `zipka/` и `web/`
- Сеть: только GET по allowlist
- Камера и микрофон выключены по умолчанию
- Книги: в память идут выжимки, не полный текст в git

См. актуальную карту: [PROJECT_MAP.md](PROJECT_MAP.md)
