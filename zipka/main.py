from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from zipka.agent import Zipka
from zipka.config import ensure_data_dirs, get_settings
from zipka.evolve.hard import APPROVE_PHRASE

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
    """Статус Зипки и Ollama."""
    z = _agent()
    s = z.status()
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"Имя: {s['name']}",
                    f"Ollama: {'OK' if s['ollama'] else 'offline'}",
                    f"Модель: {s['model']}",
                    f"Модели: {', '.join(s['models']) or '—'}",
                    f"Eyes: {'on' if s['eyes'] else 'off'}",
                    f"Ears: {'on' if s['ears'] else 'off'}",
                    f"Pending patch: {s['pending_patch']}",
                    f"Focus: {s['mind'].get('focus')}",
                    f"Mood: {s['mind'].get('mood')}",
                    f"Goals: {'; '.join(s['mind'].get('goals') or [])}",
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
    max_files: int = typer.Option(24, "--max-files", help="Лимит файлов в папке"),
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
    z = _agent()
    action = action.lower()
    if action == "on":
        console.print(z.eyes.on())
        return
    if action == "off":
        console.print(z.eyes.off())
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
    z = _agent()
    action = action.lower()
    if action == "on":
        console.print(z.ears.on())
    elif action == "off":
        console.print(z.ears.off())
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
