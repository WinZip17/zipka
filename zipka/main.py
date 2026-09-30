from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from zipka.agent import Zipka
from zipka.books.reader import DEFAULT_MAX_FILES
from zipka.config import ensure_data_dirs, get_settings
from zipka.evolve.hard import APPROVE_PHRASE
from zipka.mind.goals import normalize_goals

app = typer.Typer(
    name="zipka",
    help="Зипка — локальный саморазвивающийся агент",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _agent() -> Zipka:
    ensure_data_dirs()
    return Zipka()


@app.command()
def status() -> None:
    """Статус Зипки и LLM."""
    z = _agent()
    s = z.status()
    llm = s.get("llm") or {}
    backend = llm.get("backend", "ollama")
    avail = llm.get("available", s.get("ollama"))
    backend_line = (
        f"LLM: {backend} — {'OK' if avail else 'offline'}"
        + (f" ({llm.get('model_path')})" if llm.get("model_path") else "")
    )
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Имя: {s['name']}",
                    backend_line,
                    f"Модель: {s['model']}",
                    f"Модели: {', '.join(s['models']) or '—'}",
                    f"Eyes: {'on' if s['eyes'] else 'off'}",
                    f"Ears: {'on' if s['ears'] else 'off'}",
                    f"Pending patch: {s['pending_patch']}",
                    f"Focus: {s['mind'].get('focus')}",
                    f"Mood: {s['mind'].get('mood')}",
                    f"Goals: {'; '.join(normalize_goals(s['mind'].get('goals') or []))}",
                    (
                        f"Собеседник: {((s.get('user') or {}).get('name') or '—')}"
                        f" · настроение {((s.get('user') or {}).get('mood') or '—')}"
                        f" · наблюдений {((s.get('user') or {}).get('evidence_count') or 0)}"
                    ),
                ]
            ),
            title="Zipka",
        )
    )


@app.command()
def chat(
    message: Optional[str] = typer.Argument(None, help="Одно сообщение; без него — REPL"),
) -> None:
    """Чат с Зипкой."""
    z = _agent()
    if message:
        console.print(Markdown(z.chat(message)))
        return
    hello = z.greet()
    if hello:
        console.print(Panel(Markdown(hello), title="Зипка"))
    console.print(
        "[bold]Зипка онлайн.[/bold] Команды: /quit, /status, /ping. "
        f"Approve патча: «{APPROVE_PHRASE}»"
    )
    while True:
        try:
            user = console.input("[bold cyan]ты>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nПока.")
            break
        if not user:
            # occasional rare ping when idle enter
            ping = z.rare_ping()
            if ping:
                console.print(Panel(Markdown(ping), title="Зипка · пинг"))
            continue
        if user in {"/quit", "/exit", "выход"}:
            console.print("Пока.")
            break
        if user == "/status":
            status()
            continue
        if user == "/ping":
            ping = z.rare_ping(force=True)
            console.print(Panel(Markdown(ping or "Лимит пингов на сегодня."), title="пинг"))
            continue
        reply = z.chat(user)
        console.print(Panel(Markdown(reply), title="Зипка"))


@app.command("evolve")
def evolve_cmd(
    request: str = typer.Argument(..., help="Что изменить в характере/навыках"),
) -> None:
    """Мягкая эволюция по запросу."""
    z = _agent()
    result = z.soft.apply_user_request(request)
    console.print(Panel(str(result), title="soft-evolve"))


@app.command()
def rollback(patch_id: str = typer.Argument(...)) -> None:
    """Откат hard-патча."""
    z = _agent()
    result = z.hard.rollback(patch_id)
    console.print(result)


@app.command()
def read(
    path: Path = typer.Argument(..., exists=True, readable=True),
    member: Optional[str] = typer.Option(
        None, "--member", "-m", help="Файл внутри zip/rar"
    ),
    comment: Optional[str] = typer.Option(
        None, "--comment", "-c", help="Комментарий/фокус при чтении"
    ),
    mode: Optional[str] = typer.Option(
        None, "--mode", help="auto|books|code — фильтр содержимого папки"
    ),
    max_files: int = typer.Option(
        DEFAULT_MAX_FILES, "--max-files", help="Лимит файлов в папке"
    ),
    edits: bool = typer.Option(
        False, "--edits", help="После изучения проекта предложить правки"
    ),
    list_members: bool = typer.Option(
        False, "--list", help="Показать книги внутри архива"
    ),
) -> None:
    """Прочитать книгу/код/папку (книги или проект)."""
    z = _agent()
    if list_members:
        books = z.books.list_archive_books(path)
        console.print(Panel("\n".join(books) or "(пусто)", title="archive"))
        return
    with console.status("Изучаю..."):
        result = z.books.read(
            path,
            member=member,
            comment=comment,
            mode=mode,
            max_files=max_files,
        )
    if path.is_dir() and result.get("is_project"):
        z.hard.remember_project(path)
    member_line = (
        f"Внутри архива: {result['archive_member']}\n"
        if result.get("archive_member")
        else ""
    )
    body = (
        f"Источник: {result['source']}\n"
        f"Тип: {result.get('kind')}\n"
        f"{member_line}"
        f"Фрагментов: {result['chunks']}\n"
        f"Digest: {result['digest_path']}\n\n"
        f"{(result.get('overview') or result.get('digest') or '')[:2500]}"
    )
    follow = z.proactive.study_followup(
        source=str(path),
        digest=result.get("digest") or "",
        kind=result.get("kind") or "book",
        comment=comment,
    )
    if follow:
        body = z.proactive.attach(body, follow)
    if edits and path.is_dir() and result.get("is_project"):
        pending = z.hard.propose(
            comment or f"Улучши проект {path}",
            project_root=path,
            context=result.get("digest") or "",
        )
        body = z.proactive.attach(body, z.hard.format_pending(pending))
    console.print(Panel(body, title="study"))


@app.command()
def eyes(
    action: str = typer.Argument(..., help="on|off|snap|screen|window"),
    monitor: int = typer.Option(
        1, "--monitor", help="Номер монитора для screen (1=основной, 0=все)"
    ),
) -> None:
    """Глаза: on/off, snap (камера), screen (монитор), window (активное окно)."""
    from zipka.sensors.feature import refuse_sensors, sensors_feature_enabled

    z = _agent()
    action = action.lower()
    if action == "off":
        console.print(z.eyes.off())
        return
    if not sensors_feature_enabled(z.settings):
        console.print(refuse_sensors("eyes" if action == "on" else "look"))
        raise typer.Exit(code=1)
    if action == "on":
        console.print(z.eyes.on())
        return

    capture = {
        "snap": z.eyes.snap,
        "camera": z.eyes.snap,
        "cam": z.eyes.snap,
        "screen": lambda: z.eyes.screen(monitor=monitor),
        "monitor": lambda: z.eyes.screen(monitor=monitor),
        "window": z.eyes.window,
        "win": z.eyes.window,
    }.get(action)
    if not capture:
        raise typer.BadParameter("on|off|snap|screen|window")

    snap = capture()
    console.print(f"Кадр ({snap.get('source', action)}): {snap['path']}")
    with console.status("Смотрю..."):
        desc = z.describe_image(snap["image_b64"])
    console.print(Panel(desc, title="глаза"))
    z.memory.add_note(
        "eyes",
        desc,
        meta={"path": snap["path"], "source": snap.get("source", action)},
    )
    comment = z.comment_eyes(desc)
    if comment:
        console.print(Panel(Markdown(comment), title="Зипка · глаза"))


@app.command()
def ears(
    action: str = typer.Argument(..., help="on|off|listen"),
    seconds: float = typer.Option(5.0, help="Длительность записи"),
) -> None:
    """Уши: on / off / listen."""
    from zipka.sensors.feature import refuse_sensors, sensors_feature_enabled

    z = _agent()
    action = action.lower()
    if action == "off":
        console.print(z.ears.off())
        return
    if not sensors_feature_enabled(z.settings):
        console.print(refuse_sensors("ears" if action == "on" else "listen"))
        raise typer.Exit(code=1)
    if action == "on":
        console.print(z.ears.on())
    elif action == "listen":
        console.print(f"Слушаю {seconds} сек...")
        text = z.ears.listen(seconds=seconds)
        console.print(Panel(text, title="уши"))
        comment = z.comment_ears(text)
        if comment:
            console.print(Panel(Markdown(comment), title="Зипка · уши"))
        reply = z.chat(text)
        console.print(Panel(Markdown(reply), title="Зипка"))
    else:
        raise typer.BadParameter("on|off|listen")


@app.command("reset-learning")
def reset_learning_cmd(
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Подтвердить сброс (без интерактива всё равно спросит фразу)",
    ),
) -> None:
    """Сброс всего обучения (очистка data/). Требует подтверждения."""
    from zipka.reset import CONFIRM_PHRASE

    z = _agent()
    console.print(
        "[bold red]Будет удалено:[/bold red] чат, заметки, цели, книги, "
        "снимки, патчи, живой persona.yaml."
    )
    if not yes:
        ok = typer.confirm("Точно сбросить обучение?", default=False)
        if not ok:
            console.print("Отменено.")
            raise typer.Exit(0)
    phrase = typer.prompt(f"Введи фразу подтверждения ({CONFIRM_PHRASE})")
    if phrase.strip().lower() != CONFIRM_PHRASE:
        console.print("Фраза не совпала — сброс отменён.")
        raise typer.Exit(1)
    result = z.reset_learning(confirm=True)
    console.print(Panel(str(result), title="reset"))


models_app = typer.Typer(help="Чатовые GGUF: Pathfinder + Qwen2.5")
app.add_typer(models_app, name="models")


@models_app.command("list")
def models_list() -> None:
    """Список чатовых профилей и наличие файлов."""
    from zipka.tools.download_chat_models import main as dl_main

    raise typer.Exit(dl_main(["--list"]))


@models_app.command("download")
def models_download(
    model_id: str = typer.Option(
        "all",
        "--id",
        help="pathfinder | qwen25 | moondream2 | vision | all",
    ),
    force: bool = typer.Option(False, "--force", help="Перекачать"),
) -> None:
    """Скачать GGUF (чат и/или vision Moondream2)."""
    from zipka.tools.download_chat_models import main as dl_main

    args = ["--id", model_id]
    if force:
        args.append("--force")
    raise typer.Exit(dl_main(args))


@models_app.command("use")
def models_use(
    model_id: str = typer.Argument(..., help="pathfinder | qwen25"),
) -> None:
    """Переключить активный чатовый профиль и перезагрузить LLM."""
    z = _agent()
    try:
        result = z.set_chat_model(model_id)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    llm = result.get("llm") or {}
    console.print(
        Panel(
            f"Профиль: {model_id}\n"
            f"Файл: {llm.get('model') or '—'}\n"
            f"Путь: {llm.get('model_path') or '—'}",
            title="chat model",
        )
    )


@app.command()
def reflect() -> None:
    """Принудительная рефлексия."""
    z = _agent()
    state = z.mind.reflect()
    console.print(Panel(str(state), title="mind"))


@app.command()
def learn(query: str = typer.Argument(..., help="URL или тема")) -> None:
    """Самообучение по сети (allowlist GET)."""
    z = _agent()
    with console.status("Учусь..."):
        result = z.net.learn(query)
    console.print(
        Panel(
            f"URL: {result['url']}\nChars: {result['chars']}\n\n{result['summary']}",
            title="learn",
        )
    )


@app.command("news")
def news_cmd(
    action: str = typer.Argument(
        "sources",
        help="sources|ingest|search",
    ),
    query: str = typer.Option("", "--query", "-q", help="Поиск"),
    days: int = typer.Option(7, help="Период поиска"),
    rss: str = typer.Option("", help="Добавить RSS URL"),
    telegram: str = typer.Option("", "--tg", help="Добавить Telegram @channel"),
) -> None:
    """Новости: источники RSS/Telegram, ingest, поиск."""
    z = _agent()
    action = action.lower().strip()
    if rss:
        z.news.add_rss(rss)
        console.print(f"RSS: {rss}")
    if telegram:
        z.news.add_telegram(telegram)
        console.print(f"TG: @{telegram.lstrip('@')}")
    if action == "sources":
        console.print(Panel(str(z.news.load_sources()), title="news sources"))
        return
    if action == "ingest":
        with console.status("Читаю новости..."):
            result = z.news.ingest()
        console.print(Panel(str(result), title="ingest"))
        return
    if action == "search":
        if not query:
            raise typer.BadParameter("Нужен --query")
        hits = z.news.search(query, days=days)
        console.print(Panel(str(hits), title=f"search «{query}» / {days}d"))
        return
    raise typer.BadParameter("sources|ingest|search")


@app.command("finetune")
def finetune_cmd(
    action: str = typer.Argument(
        "status",
        help="status|propose|start|abort|lineage",
    ),
    max_steps: int = typer.Option(60, help="Шагов LoRA"),
    lora_r: int = typer.Option(8, help="Rank LoRA"),
) -> None:
    """Дообучение чатовой модели на диалогах (LoRA → новый GGUF)."""
    z = _agent()
    action = action.lower().strip()
    if action == "status":
        st = z.finetune.refresh_job_status()
        console.print(Panel(str(st), title="finetune status"))
        return
    if action == "lineage":
        console.print(Panel(str(z.finetune.load_lineage()), title="lineage"))
        return
    if action == "propose":
        try:
            pending = z.finetune.propose(max_steps=max_steps, lora_r=lora_r)
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        console.print(Panel(z.finetune.format_pending(pending), title="propose"))
        return
    if action == "start":
        try:
            started = z.start_finetune_approved()
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        console.print(Panel(str(started), title="started"))
        return
    if action == "abort":
        try:
            out = z.finetune.abort_running(kill=True)
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        console.print(Panel(str(out), title="abort"))
        return
    raise typer.BadParameter("status|propose|start|abort|lineage")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765),
) -> None:
    """Запуск web UI."""
    import uvicorn

    console.print(f"Web UI: http://{host}:{port}")
    uvicorn.run("web.app:app", host=host, port=port, reload=False)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
