# Zipka / Зипка

Проект создан исключительно с целью саморазвития и обучения. Сохранен в git что б не потерять. Автор не несет ответственности за возможные убытки или ошибки в работе программы.
Проект несет цель сделать эмулятор искусственного интеллекта из книги Александра Чубарьяна – "Хакеры. Полный Root", но с другим именем :)
Автор проекта осуждает действие хакеров, и против любых нарушений закона.

Локальный саморазвивающийся агент на **Python**. Модель — **файл GGUF в `data/models`** (без системной Ollama) или **Ollama**, если GGUF нет.

Лицензия: **MIT** — см. [`LICENSE`](LICENSE).

## Требования к компьютеру

Ориентиры под дефолтные GGUF (чат Pathfinder ~12B Q4 ≈7.5 ГБ на диске, кодинг Qwen2.5‑7B Q5 ≈5.4 ГБ) и типичный сценарий «чат + web UI». Дообучение и две модели сразу требуют заметно больше.

| | Минимально | Рекомендуется |
|--|------------|---------------|
| **ОС** | Windows 10/11 x64 (или Linux) | То же |
| **CPU** | 4 ядра / 8 потоков, современные x86‑64 | 8+ ядер / 16 потоков |
| **ОЗУ** | **16 ГБ** (только чат, режим CPU; без второго GGUF в памяти) | **32 ГБ** (чат + кодинг / hybrid; запас под книги, новости, vision) |
| **Диск** | **SSD**, свободно **≥25 ГБ** (venv + 1–2 GGUF) | **SSD NVMe**, свободно **≥80 ГБ** (обе модели + vision + finetune checkpoints) |
| **GPU** | Не обязателен (медленный CPU‑инференс) | **NVIDIA**, **≥8 ГБ VRAM** (CUDA‑сборка `llama-cpp-python`, hybrid/GPU) |
| **Python / Node** | Python **3.11+**, для UI — Node 18+ | То же |

**Кратко по сценариям**

- **Минимум:** одна чатовая GGUF, CPU или hybrid на слабой видеокарте, без дообучения и без локального vision — Зипка отвечает, но медленно.
- **Комфорт:** 32 ГБ RAM + GPU 8 ГБ, две роли моделей, глаза (Moondream ≈3.5 ГБ), уши (faster-whisper).
- **Дообучение (LoRA):** лучше GPU с CUDA + `bitsandbytes` (4‑bit); Qwen2.5‑7B / Qwen3‑8B. На CPU‑only для 7–8B почти всегда нехватка памяти. Merge‑checkpoint одного поколения — порядка **десятков ГБ** на диске.

На **8 ГБ VRAM** для Pathfinder удобнее **hybrid** или одна модель на чат и кодинг (см. [`data/models/README.md`](data/models/README.md)).

## Возможности

1. Мягкая самоэволюция (характер, навыки, предпочтения)
2. Правки своего кода только после фразы `разрешаю правку кода`
3. Характер Зипки + чтение книг, исходников и **чужих проектов** (txt/md/fb2/djvu/py/js/ts/…, zip/rar, папки)
4. Глаза (webcam) и уши (mic + faster-whisper)
5. Цели и рефлексия (псевдоразум)
6. Самообучение по сети (GET, allowlist) и чтение URL из чата (`прочитай https://…`)
7. Веб-поиск DDG/SearXNG (`найди информацию о…` → 2–3 источника + выжимка)
8. Профиль собеседника (имя, настроение, «свои», speaker-guard)
9. CLI + web UI (React + MUI)
10. Две роли GGUF: **чат** и **кодинг** (можно одна модель на обе)
11. Дообучение на своих диалогах (LoRA → новый GGUF) — альтернатива «сохранись»
12. Новости: RSS + публичные Telegram (`t.me/s`), выдержки и поиск по периоду

## Быстрый старт

Один раз настрой окружение (venv, pip, npm, сборка UI, `.env`):

```bash
# Linux / macOS
chmod +x setup_zipka.sh start_zipka.sh start_zipka_chat.sh
./setup_zipka.sh --with-llama

# Windows
setup_zipka.bat --with-llama
```

Опции setup: `--with-llama`, `--with-finetune`, `--with-rag`, `--skip-frontend`.

Дальше — запуск Web UI: `./start_zipka.sh` / `start_zipka.bat` или конфигурации IDE (см. ниже).

### Вариант A — без Ollama (файл модели)

```bash
# после setup_zipka.* :
# Linux
source .venv/bin/activate
# Windows
.\.venv\Scripts\activate

# рекомендуемые GGUF в data/models:
python -m zipka.tools.download_chat_models --id all
# или: python -m zipka.main models download --id all

python -m zipka.main status
python -m zipka.main web
```

Подробности: [`data/models/README.md`](data/models/README.md).

**По умолчанию (runtime):**

| Роль | Файл |
|------|------|
| Чат | `Pathfinder-RP-12B-RU.Q4_K_M.gguf` |
| Кодинг | `Qwen2.5-7B-Instruct-Q5_K_M.gguf` |

Любой `*.gguf` из `data/models` можно выбрать **для чата и для кодинга** (в т.ч. одну и ту же) в UI: **Настройки → Модели GGUF**.  
Compute: CPU / GPU / hybrid — там же. Состояние: `data/settings/runtime.json`.

Legacy в `.env`: `ZIPKA_CHAT_MODEL=pathfinder|qwen25` (стартовое имя чата; UI/runtime перекрывает).  
Опционально: `ZIPKA_GGUF_CTX=8192` (или `num_ctx` в UI).

### Вариант B — системная Ollama

```bash
./setup_zipka.sh          # Linux
# setup_zipka.bat         # Windows

# в .env: ZIPKA_LLM_BACKEND=ollama и модель из `ollama list` (по умолчанию my_qwen:latest)

python -m zipka.main status
python -m zipka.main chat
python -m zipka.main web
```

Web: http://127.0.0.1:8765

Разработка UI: в одном терминале `python -m zipka.main web`, в другом `cd web/frontend && npm run dev` (Vite на :5173, API проксируется). Либо IDE-конфиг **Zipka: Frontend Dev**.

**Приоритет (`ZIPKA_LLM_BACKEND=auto`):** если в `data/models` есть `*.gguf` → локальный llama.cpp; иначе Ollama.

**Глаза без Ollama:** нужен vision GGUF + `mmproj` (рекомендуется Moondream2 ≈3.5 GB):

```bash
python -m zipka.main models download --id moondream2
```

При снимке чатовая модель выгружается, кадр описывает vision, затем чат снова прогревается. Запасной путь — Ollama с `OLLAMA_VISION_MODEL`.

## Запуск: ярлык и JetBrains IDE

### Ярлык (Windows)

1. Один раз создай ярлык на рабочий стол:
   ```bat
   powershell -ExecutionPolicy Bypass -File create_shortcut.ps1
   ```
2. Двойной клик по **Зипка** на рабочем столе → поднимается Web UI.

### PyCharm / WebStorm

В репозитории лежат shared run-конфиги в [`.run/`](.run/) — после открытия проекта они появляются в списке **Run**.

1. Открой папку проекта как Project Root.
2. Один раз: **Run → Zipka: Setup (Linux|Windows)**  
   (или `./setup_zipka.sh` / `setup_zipka.bat` в терминале).
3. **PyCharm:** Settings → Python Interpreter → выбери `.venv`  
   (`…/bin/python` на Linux, `…\Scripts\python.exe` на Windows).  
   Затем **Zipka: Web UI** / **Zipka: Chat** (тип Python module).
4. **WebStorm** (и PyCharm без настройки SDK):  
   - Linux: **Zipka: Web UI (Linux)** / **Zipka: Chat (Linux)**  
   - Windows: **Zipka: Web UI (Windows)** или **Zipka: Web UI (Windows / WebStorm)**  
     (второй вариант через `cmd.exe` — если Batch-тип недоступен)
5. Опционально рядом: **Zipka: Frontend Dev** (`npm run dev` на :5173).

URL после старта: http://127.0.0.1:8765

### Скрипты в корне

| Файл | Что делает |
|------|------------|
| `setup_zipka.sh` / `setup_zipka.bat` | Проверка/установка Python venv, pip, npm, сборка UI, `.env` |
| `start_zipka.sh` / `start_zipka.bat` | Web UI |
| `start_zipka_chat.sh` / `start_zipka_chat.bat` | Чат в терминале |
| `create_shortcut.ps1` | Ярлык «Зипка» на Desktop (Windows) |
| `.run/*.run.xml` | Конфиги Run для PyCharm / WebStorm |

## Как добавить книгу или код

1. **В чате по пути** (CLI или web):
   ```
   прочитай C:\Users\WinZip\Desktop\книга.fb2
   прочитай https://habr.com/ru/articles/...
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

### RAG для книг (опционально)

По умолчанию длинная книга сжимается выборкой начало/середина/конец. С пакетом RAG:

```bash
pip install -e ".[rag]"
```

при «прочитай / изучи» книгу Зипка:

1. дробит текст на фрагменты и строит локальный индекс (`data/books/rag/…`);
2. достаёт релевантные куски (по комментарию или обзорным запросам);
3. пишет выжимку **по этим фрагментам** (в UI: «Индексирую книгу…» → «Изучаю…»).

Без `.[rag]` поведение прежнее (sample). Модель эмбеддингов: `intfloat/multilingual-e5-small` (скачается при первом индексе).

**Изучение чужого проекта (папка)** — по AI-приоритетам:

1. AI-контекст: `AGENTS.md`, `PROJECT_MAP.md`, `.cursorrules`, …
2. Манифесты: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, …
3. Документация: корневой `README`, `docs/`
4. Папки агентов: `.cursor/rules`, `.claude`, `agents/`, …

Если такой контекст есть — читается он (до лимита файлов). Если нет — тогда прочие исходники.  
Лимит по умолчанию: до 24 файлов; без `node_modules` / `.venv` / `.git`.

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
| `python -m zipka.main models list` | Профили / GGUF для скачивания |
| `python -m zipka.main models download --id all` | Скачать Pathfinder + Qwen2.5 |
| `python -m zipka.main models use pathfinder` | Сменить модель чата (legacy id или имя `.gguf`) |
| `python -m zipka.main eyes on\|off\|snap\|screen\|window` | Камера / экран / окно |
| `python -m zipka.main ears on\|off\|listen` | Микрофон |
| `python -m zipka.main reset-learning` | Сброс всего обучения (с подтверждением) |
| `python -m zipka.main learn URL\|тема` | Сеть (allowlist) |
| `python -m zipka.main search "…"` | Веб-поиск DDG/SearXNG |
| `python -m zipka.main rollback ID` | Откат патча |
| `python -m zipka.main finetune status\|propose\|start\|lineage` | LoRA → новый GGUF |
| `python -m zipka.main web` | Web UI |

## Дообучение (сохранение опыта в GGUF)

Альтернатива soft-памяти: мелкими шагами вшить диалоги в веса и получить новый `.gguf`.

```bash
pip install -e ".[finetune]"
# ВАЖНО: pip по умолчанию часто ставит torch+cpu. Для GPU (VRAM+RAM):
pip uninstall -y torch
pip install torch --index-url https://download.pytorch.org/whl/cu126
# проверка: python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# для экспорта GGUF: llama.cpp convert_hf_to_gguf.py + llama-quantize
# set ZIPKA_LLAMA_CONVERT=C:\path\to\llama.cpp\convert_hf_to_gguf.py
# set ZIPKA_LLAMA_QUANTIZE=C:\path\to\llama-quantize.exe
```

В чате: `дообучись` / `сохранись` → проверка → `разрешаю дообучение`.

Цикл:
1. Диалоги из `data/memory/chat.jsonl` → датасет
2. LoRA на HF-базе (Qwen2.5/Qwen3) или на прошлом `data/finetune/checkpoints/gen_N`
3. Merge → checkpoint gen_N+1
4. Экспорт → `data/models/zipka-self-genNNNN.*.gguf`, переключение chat GGUF
5. Следующий круг стартует с этого checkpoint

Обучение грузит модель через `device_map=auto`: слои на **VRAM**, остаток на **ОЗУ** (и при нехватке — disk offload). На RTX 4060 8GB для Qwen3-8B лучше 4-bit (`bitsandbytes`).

**Важно:** Pathfinder сейчас только как GGUF — для первого круга поставь чат на **Qwen2.5-7B** / **Qwen3-8B** (8GB VRAM ок с 4-bit) или укажи `override_hf_base` в `data/finetune/lineage.json`. Без CUDA-torch обучение идёт только на CPU/RAM и для 8B почти всегда OOM.

CLI: `python -m zipka.main finetune propose` → `… start` → `… status`.

## Веб-поиск (DDG / SearXNG)

В чате: «Найди информацию о технических характеристиках Omoda C5 1.5».

1. Зипка составляет поисковый запрос  
2. Ищет через **SearXNG** (если задан `ZIPKA_SEARXNG_URL`) или **DuckDuckGo HTML**  
3. Читает до 3 страниц (SSRF-защита; режим `ZIPKA_SEARCH_FETCH_MODE=open|allowlist`)  
4. Даёт краткий ответ и список первоисточников  

Надёжнее поднять свой SearXNG — DDG HTML иногда режет ботов. См. `.env.example`.

## Проактивность

Зипка может заговорить первой:

1. **Приветствие** — в CLI при старте; в web не спамит при открытии вкладки  
2. **Реплики по целям** — roughly каждые 5 реплик в сессии  
3. **Уточнения** — после изучения книги/кода (1–2 вопроса)  
4. **Комментарии глаз/ушей** — только если сочла наблюдение интересным  
5. **Редкие пинги** — после случайного простоя **30 мин – 3 ч**: перечитывает случайную заметку обучения (книга/код/сеть/новости) и пишет уточняющие вопросы; без материалов — молчит. Не больше **3 раз в день**. В панели: «Запустить пинг» (форс).

Состояние: `data/mind/proactive.json`. В CLI: `/ping` — форс-пинг (считается в дневной лимит).

Всё лежит в папке `data/`:

| Что | Файл |
|-----|------|
| Заметки из книг, кода, сети, глаз, рефлексии | `data/memory/notes.jsonl` |
| История чата | `data/memory/chat.jsonl` |
| Навыки | `data/memory/skills.json` |
| Предпочтения | `data/memory/preferences.json` |
| Профиль собеседника | `data/memory/user_profile.json` (gitignore) |
| Лог эволюции | `data/memory/evolve_log.jsonl` |
| Характер (живой, локально) | `data/persona/persona.yaml` (gitignore) |
| Seed характера | `data/persona/persona.example.yaml` |
| Цели / настроение / фокус | `data/mind/state.json` (gitignore) |
| Проактивность (пинги, приветствия) | `data/mind/proactive.json` (gitignore) |
| Compute + выбранные GGUF | `data/settings/runtime.json` (gitignore) |
| Выжимки книг | `data/books/notes/*_digest.md` |
| RAG-индекс книг | `data/books/rag/<book_id>/` (нужен `pip install -e ".[rag]"`) |
| Распакованные из zip/rar | `data/books/extracted/` |
| Локальные GGUF-модели | `data/models/*.gguf` (gitignore) |

Основное хранилище знаний — **`data/memory/notes.jsonl`**: саммари книг (`book`), кода (`code`), обучения по сети (`net_learn`), снимков (`eyes`) и рефлексий (`reflection`).

Все результаты обучения (`data/memory`, `data/mind`, `data/books`, живой `persona.yaml` и т.д.) в **`.gitignore`** — в репозитории остаётся чистый проект + `persona.example.yaml`.

## Безопасность

- Hard-evolve правит только `zipka/` и `web/`
- Сеть: GET; learn — allowlist; веб-поиск — DDG/SearXNG + SSRF-защита (`ZIPKA_SEARCH_FETCH_MODE`)
- Камера и микрофон выключены по умолчанию
- Книги: в память идут выжимки, не полный текст в git
- Сюжеты/фикшн (в т.ч. «взлом» в книге) не путаются с реальными вредоносными инструкциями

См. актуальную карту: [PROJECT_MAP.md](PROJECT_MAP.md) *(часть разделов карты может отставать — ориентир по дереву модулей)*.

## Лицензия

Проект распространяется под лицензией **MIT**. Полный текст — в файле [`LICENSE`](LICENSE).
