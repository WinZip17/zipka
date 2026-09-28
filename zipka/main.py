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
    list_members: bool = typer.Option(
        False, "--list", help="Показать книги внутри архива"
    ),
) -> None:
    """Прочитать книгу/код (txt/md/fb2/py/js/ts/… или zip/rar/папка)."""
    z = _agent()
    if list_members:
        books = z.books.list_archive_books(path)
        console.print(Panel("\n".join(books) or "(пусто)", title="archive"))
        return
    with console.status("Читаю..."):
        result = z.books.read(path, member=member, comment=comment)
    member_line = (
        f"Внутри архива: {result['archive_member']}\n"
        if result.get("archive_member")
        else ""
    )
    body = (
        f"Источник: {result['source']}\n"
        f"{member_line}"
        f"Фрагментов: {result['chunks']}\n"
        f"Digest: {result['digest_path']}\n\n"
        f"{result['digest'][:2000]}"
    )
    follow = z.proactive.study_followup(
        source=str(path),
        digest=result.get("digest") or "",
        kind=result.get("kind") or "book",
        comment=comment,
    )
    if follow:
        body = z.proactive.attach(body, follow)
    console.print(Panel(body, title="book"))


@app.command()
def eyes(
    action: str = typer.Argument(..., help="on|off|snap"),
) -> None:
    """Глаза: on / off / snap."""
    z = _agent()
    action = action.lower()
    if action == "on":
        console.print(z.eyes.on())
    elif action == "off":
        console.print(z.eyes.off())
    elif action == "snap":
        snap = z.eyes.snap()
        console.print(f"Кадр: {snap['path']}")
        with console.status("Смотрю..."):
            desc = z.describe_image(snap["image_b64"])
        console.print(Panel(desc, title="глаза"))
        z.memory.add_note("eyes", desc, meta={"path": snap["path"]})
        comment = z.comment_eyes(desc)
        if comment:
            console.print(Panel(Markdown(comment), title="Зипка · глаза"))
    else:
        raise typer.BadParameter("on|off|snap")


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
