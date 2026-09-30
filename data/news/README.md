# Новости (runtime ignored by git)

| Файл | Назначение | В git? |
|------|------------|--------|
| `sources.json` | RSS / Telegram + интервалы | нет (локально) |
| `items.jsonl` | сохранённые выдержки | нет |
| `sources.example.json` | пустой шаблон | да |

При первом запуске, если нет `sources.json`, Зипка создаст пустой. Скопируй пример:

```bat
copy data\news\sources.example.json data\news\sources.json
```

Или в чате: «добавь телеграм @channel» / «добавь rss https://…/feed».
