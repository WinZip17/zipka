# PROJECT_MAP — Зипка

Актуальная карта репозитория. Обновляется на каждом шаге.

## Статус шагов

| Шаг | Модуль | Статус |
|-----|--------|--------|
| 0 | Скелет, конфиг, карта | done |
| 1 | Ollama + soft-evolve + chat | done |
| 2 | Hard-evolve + approve + rollback | done |
| 3 | Persona + book reader | done |
| 4 | Eyes / Ears | done |
| 5 | PseudoMind | done |
| 6 | Net learner | done |
| 7 | Web UI | done |

## Дерево

```
zipka/
  PROJECT_MAP.md
  README.md
  LICENSE            # MIT
  requirements.txt
  pyproject.toml
  .env.example
  .gitignore
  data/
    persona/persona.yaml
    memory/          # notes, skills, preferences, chat, evolve_log
    books/notes/
    snapshots/
    patches/
    mind/state.json  # создаётся при первом запуске
  zipka/
    __init__.py
    main.py          # CLI (typer)
    config.py
    agent.py         # оркестратор
    llm/ollama_client.py
    character/persona.py
    memory/store.py
    evolve/soft.py
    evolve/hard.py
    books/reader.py      # txt/md/fb2 + zip/rar
    sensors/eyes.py
    sensors/ears.py
    mind/goals.py
    mind/proactive.py    # приветствия, цели, уточнения, сенсоры, редкие пинги
    net/learner.py
    safety/policy.py
  web/
    app.py                 # FastAPI: /api/* + раздача React build
    frontend/              # React + Vite + @mui/material
      src/App.tsx
      src/components/
      dist/                # npm run build → сюда (gitignore)
```

## Запуск

```bash
pip install -r requirements.txt
copy .env.example .env
# модель: ollama list → ZIPKA/.env OLLAMA_MODEL=
python -m zipka.main status
python -m zipka.main chat
python -m zipka.main web
```

Ярлык: `create_shortcut.ps1` → Desktop **Зипка** → `start_zipka.bat` (Web UI).
Также: `start_zipka_chat.bat` для CLI-чата.

Книги/код: путь в чате (`прочитай` / `изучи`), upload в web, CLI `read`.  
Форматы кода: `.py` `.js` `.ts` `.tsx` `.go` `.rs` и др.; папки — до 12 файлов.

## Зависимости от железа / сервисов

- **Ollama** — обязательна для диалога, книг, learn, рефлексии
- **Webcam** — только для `eyes snap`
- **Microphone** — только для `ears listen` (+ загрузка модели whisper)

## Ключевые фразы

- Soft-evolve: работает всегда / `zipka evolve "..."`
- Hard-evolve approve: `разрешаю правку кода`
- Rollback: `python -m zipka.main rollback <id>`
