# Zipka / Зипка

Локальный саморазвивающийся агент на **Python**. Модель — **файл GGUF в `data/models`** (без системной Ollama) или **Ollama**, если GGUF нет.

## Возможности

1. Мягкая самоэволюция (характер, навыки, предпочтения)
2. Правки своего кода только после фразы `разрешаю правку кода`
3. Характер Зипки + чтение книг и исходников (txt/md/fb2/djvu/py/js/ts/…, zip/rar, папки)
4. Глаза (webcam) и уши (mic + faster-whisper)
5. Цели и рефлексия (псевдоразум)
6. Самообучение по сети (GET, allowlist)
7. CLI + web UI (React + MUI)

## Быстрый старт

### Вариант A — без Ollama (файл модели)

```bash
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install llama-cpp-python --only-binary=:all: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
copy .env.example .env

# положи *.gguf в data/models (например qwen2.5-7b-instruct-q4_k_m.gguf)
# ZIPKA_LLM_BACKEND=auto подхватит его сама

python -m zipka.main status
python -m zipka.main web
```

Каталог моделей: https://huggingface.co/models?library=gguf  
Опционально в `.env`: `ZIPKA_GGUF_MODEL=имя_файла.gguf`, `ZIPKA_GGUF_CTX=8192`, `ZIPKA_GGUF_GPU_LAYERS=0`.

### Вариант B — системная Ollama

```bash
# если python в PATH:
python -m venv .venv
# на этой машине venv уже создан через локальный CPython 3.11

.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# в .env: ZIPKA_LLM_BACKEND=ollama и модель из `ollama list` (по умолчанию my_qwen:latest)

# web UI (React + @mui/material) — один раз собрать:
cd web\frontend
npm install
npm run build
cd ..\..

python -m zipka.main status
python -m zipka.main chat
python -m zipka.main web
```

Web: http://127.0.0.1:8765

Разработка UI: в одном терминале `python -m zipka.main web`, в другом `cd web/frontend && npm run dev` (Vite на :5173, API проксируется).

**Приоритет (`ZIPKA_LLM_BACKEND=auto`):** если в `data/models` есть `*.gguf` → локальный llama.cpp; иначе Ollama. Глаза/vision пока только через Ollama.

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
   изучи D:\Project2\zipka\zipka\agent.py комментарий: разбери soft-evolve
   изучи папку D:\Project2\zipka\zipka
   изучи папку D:\Books режим: books
   изучи папку D:\myapp режим: code предложи правки комментарий: упростить API
   прочитай D:\books\archive.zip внутри main.py комментарий: только API
   что в архиве D:\books\archive.zip
   ```
2. **Загрузить файл в web** (как в мессенджере): кнопка `+` или drag-drop → чип с именем файла над полем ввода → напиши сообщение (это и есть комментарий к файлу) → **Отправить**.  
   Можно отправить только файл без текста.
3. **CLI**:
   ```bash
   python -m zipka.main read PATH -c "разбери ошибки" --mode code --max-files 30
   python -m zipka.main read PROJECT_DIR --edits -c "добавь логирование"
   ```

Для кода Зипка делает разбор: назначение, API, зависимости, паттерны (не копирует длинные куски).  
Папка: до 24 файлов по умолчанию (книги и/или код; без `node_modules` / `.venv` / `.git`).  
После изучения проекта можно сказать «предложи правки» — патч только с `разрешаю правку кода`.  
DJVU: читается через встроенный пакет **`djvu-rs`** (не нужен системный DjVuLibre).  
Сканы без текстового слоя (без OCR) прочитать нельзя — нужен файл с уже распознанным текстом.  
Опционально: если установлен DjVuLibre (`djvutxt`), он используется как запасной путь.

| Команда | Описание |
|--------|----------|
| `python -m zipka.main chat` | REPL-чат |
| `python -m zipka.main evolve "..."` | Мягкая эволюция |
| `python -m zipka.main read PATH` | Книга/код/папка/архив |
| `python -m zipka.main read PATH --list` | Список файлов в архиве |
| `python -m zipka.main read PATH -m file.py` | Файл внутри архива |
| `python -m zipka.main eyes on\|off\|snap\|screen\|window` | Камера / экран / окно |
| `python -m zipka.main ears on\|off\|listen` | Микрофон |
| `python -m zipka.main reset-learning` | Сброс всего обучения (с подтверждением) |
| `python -m zipka.main learn URL\|тема` | Сеть |
| `python -m zipka.main rollback ID` | Откат патча |
| `python -m zipka.main web` | Web UI |

## Проактивность

Зипка может заговорить первой:

1. **Приветствие** — один раз при первом контакте за день (web/CLI); повторные открытия в тот же день — без нового «привет»  
2. **Реплики по целям** — roughly каждые 5 реплик в сессии  
3. **Уточнения** — после изучения книги/кода (1–2 вопроса)  
4. **Комментарии глаз/ушей** — только если сочла наблюдение интересным  
5. **Редкие пинги** — не больше **3 раз в день**, с паузой ≥3 часа (web опрашивает ~раз в 12 мин)

Состояние: `data/mind/proactive.json`. В CLI: `/ping` — форс-пинг (считается в дневной лимит).

Всё лежит в папке `data/`:

| Что | Файл |
|-----|------|
| Заметки из книг, кода, сети, глаз, рефлексии | `data/memory/notes.jsonl` |
| История чата | `data/memory/chat.jsonl` |
| Навыки | `data/memory/skills.json` |
| Предпочтения | `data/memory/preferences.json` |
| Лог эволюции | `data/memory/evolve_log.jsonl` |
| Характер (живой, локально) | `data/persona/persona.yaml` (gitignore) |
| Seed характера | `data/persona/persona.example.yaml` |
| Цели / настроение / фокус | `data/mind/state.json` (gitignore) |
| Проактивность (пинги, приветствия) | `data/mind/proactive.json` (gitignore) |
| Выжимки книг | `data/books/notes/*_digest.md` |
| Распакованные из zip/rar | `data/books/extracted/` |
| Локальные GGUF-модели | `data/models/*.gguf` (gitignore) |

Основное хранилище знаний — **`data/memory/notes.jsonl`**: саммари книг (`book`), кода (`code`), обучения по сети (`net_learn`), снимков (`eyes`) и рефлексий (`reflection`).

Все результаты обучения (`data/memory`, `data/mind`, `data/books`, живой `persona.yaml` и т.д.) в **`.gitignore`** — в репозитории остаётся чистый проект + `persona.example.yaml`.

## Безопасность

- Hard-evolve правит только `zipka/` и `web/`
- Сеть: только GET по allowlist
- Камера и микрофон выключены по умолчанию
- Книги: в память идут выжимки, не полный текст в git

См. актуальную карту: [PROJECT_MAP.md](PROJECT_MAP.md)
