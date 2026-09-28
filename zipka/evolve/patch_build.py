from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable


def number_lines(text: str, *, max_chars: int = 14_000) -> str:
    lines = text.splitlines()
    out: list[str] = []
    size = 0
    for i, line in enumerate(lines, start=1):
        row = f"{i}|{line}"
        size += len(row) + 1
        if size > max_chars:
            out.append(f"... ({len(lines) - i + 1} строк обрезано)")
            break
        out.append(row)
    return "\n".join(out)


def apply_edits(original: str, edits: list[dict[str, Any]]) -> str:
    content = original
    for i, edit in enumerate(edits, start=1):
        old = edit.get("old")
        if old is None:
            old = edit.get("search")
        new = edit.get("new")
        if new is None:
            new = edit.get("replace")
        if not isinstance(old, str) or not old:
            raise RuntimeError(f"edit #{i}: пустой old")
        if not isinstance(new, str):
            raise RuntimeError(f"edit #{i}: new должен быть строкой")
        count = content.count(old)
        if count == 0:
            preview = old.replace("\n", "\\n")[:120]
            raise RuntimeError(f"edit #{i}: фрагмент old не найден: «{preview}»")
        if count > 1:
            raise RuntimeError(
                f"edit #{i}: фрагмент old встречается {count} раз — сделай длиннее"
            )
        content = content.replace(old, new, 1)
    return content


def basic_syntax_problems(rel: str, content: str, original: str | None) -> str | None:
    problems: list[str] = []
    if re.search(r"\b[A-Za-z_][\w]*\s*:=", content):
        problems.append("найден := (синтаксическая опечатка)")
    for open_c, close_c, name in (("(", ")", "()"), ("[", "]", "[]"), ("{", "}", "{}")):
        if content.count(open_c) != content.count(close_c):
            problems.append(f"несбалансированы скобки {name}")
    if original and ("Composer" in rel or "composer" in rel.lower()):
        for marker in ("onKeyDown", "FILE_ACCEPT", "export function", "disabled={disabled}"):
            if marker in original and marker not in content:
                problems.append(f"пропал важный фрагмент «{marker}»")
    return "; ".join(problems) if problems else None


def materialize_patch(
    data: dict[str, Any],
    *,
    base: Path,
    originals: dict[str, str],
    blocked_names: set[str],
    is_allowed: Callable[[Path], bool],
    style_check: Callable[[str, str], str | None],
    extract_json: Callable[[str], dict[str, Any] | None] | None = None,
    raw: str | None = None,
) -> list[dict[str, str]]:
    if raw is not None and extract_json is not None:
        data = extract_json(raw) or {"files": []}
    files: list[dict[str, str]] = []
    for item in data.get("files") or []:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path", "")).replace("\\", "/").lstrip("/")
        if not rel or Path(rel).name.lower() in blocked_names:
            continue
        abs_path = (base / rel).resolve()
        if not is_allowed(abs_path):
            continue
        try:
            store_rel = abs_path.relative_to(base).as_posix()
        except ValueError:
            continue

        edits = item.get("edits")
        content: str | None = None
        if isinstance(edits, list) and edits:
            original = originals.get(store_rel)
            if original is None and abs_path.is_file():
                original = abs_path.read_text(encoding="utf-8", errors="ignore")
            if original is None:
                raise RuntimeError(
                    f"{store_rel}: edits для несуществующего файла — укажи content"
                )
            content = apply_edits(original, edits)
        elif item.get("content") is not None:
            content = str(item.get("content"))
            if store_rel in originals and not item.get("rewrite"):
                if abs(len(content) - len(originals[store_rel])) > max(
                    400, int(len(originals[store_rel]) * 0.35)
                ):
                    raise RuntimeError(
                        f"{store_rel}: слишком большой rewrite. "
                        "Используй edits old→new, не переписывай файл целиком."
                    )
        else:
            continue

        assert content is not None
        bad = style_check(store_rel, content)
        if bad:
            raise RuntimeError(f"{store_rel}: {bad}")
        syn = basic_syntax_problems(store_rel, content, originals.get(store_rel))
        if syn:
            raise RuntimeError(f"{store_rel}: {syn}")
        files.append({"path": store_rel, "content": content})
    if not files:
        raise RuntimeError(
            "В ответе модели нет применимых файлов/edits. Нужен JSON с files[].edits."
        )
    return files
