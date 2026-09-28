from __future__ import annotations

import json
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


# «12|код» — модель копирует нумерацию из промпта (без пробела после |, как в number_lines)
_LINENO_PREFIX = re.compile(r"(?m)^[ \t]*\d+\|")


def strip_prompt_line_numbers(text: str) -> str:
    """Убрать префиксы «12|» из фрагментов — модель часто копирует их из промпта."""
    if not text or not _LINENO_PREFIX.search(text):
        return text
    lines = text.splitlines(keepends=True)
    nonempty = [ln for ln in lines if ln.strip()]
    numbered = sum(1 for ln in nonempty if _LINENO_PREFIX.match(ln))
    if numbered == 0:
        return text
    # чистим, если пронумерована хотя бы половина непустых строк (или ≥2)
    if numbered >= 2 or numbered >= max(1, (len(nonempty) + 1) // 2):
        return "".join(_LINENO_PREFIX.sub("", ln, count=1) for ln in lines)
    return text


def _normalize_ws(text: str) -> str:
    return re.sub(r"[ \t]+\n", "\n", text.replace("\r\n", "\n"))


_FILE_BLOCK = re.compile(
    r"<<<FILE\s+([^\n>]+)>>>\s*(.*?)<<<END>>>",
    re.DOTALL | re.IGNORECASE,
)
_EDIT_PAIR = re.compile(
    r"<<<OLD>>>\s*(.*?)\s*<<<NEW>>>\s*(.*?)(?=\s*<<<OLD>>>|\s*\Z)",
    re.DOTALL | re.IGNORECASE,
)


def parse_patch_response(text: str) -> dict[str, Any] | None:
    """Разобрать ответ модели: JSON или блоки <<<FILE>>>/<<<OLD>>>/<<<NEW>>>."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    # убрать markdown fences
    raw = re.sub(r"^```(?:json|JSON)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)

    data = _try_parse_json_patch(raw)
    if data and (data.get("files") or []):
        return data

    blocks = _parse_delimiter_patch(raw)
    if blocks:
        return {"files": blocks}
    return data  # может быть {"files":[]} из пустого JSON


def _try_parse_json_patch(text: str) -> dict[str, Any] | None:
    candidates: list[str] = [text]
    start = text.find("{")
    if start >= 0:
        candidates.append(text[start:])
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        try:
            obj, _ = json.JSONDecoder().raw_decode(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    # битый/обрезанный JSON с path+edits — не чиним эвристиками, пусть сработает delimiter
    return None


def _parse_delimiter_patch(text: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for m in _FILE_BLOCK.finditer(text):
        path = m.group(1).strip().strip('"').strip("'")
        body = m.group(2)
        edits: list[dict[str, str]] = []
        for em in _EDIT_PAIR.finditer(body):
            old = em.group(1).strip("\n")
            new = em.group(2).strip("\n")
            if old or new:
                edits.append({"old": old, "new": new})
        content_m = re.search(
            r"<<<CONTENT>>>\s*(.*)\Z", body, re.DOTALL | re.IGNORECASE
        )
        item: dict[str, Any] = {"path": path}
        if edits:
            item["edits"] = edits
        elif content_m and content_m.group(1).strip():
            item["content"] = content_m.group(1).strip("\n")
        else:
            continue
        files.append(item)
    return files


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

        old_clean = strip_prompt_line_numbers(old)
        new_clean = strip_prompt_line_numbers(new)

        replaced = _replace_once(content, old_clean, new_clean)
        if replaced is None:
            replaced = _replace_once(
                content,
                _normalize_ws(old_clean.strip("\n")),
                new_clean,
                flexible=True,
            )
        if replaced is None:
            replaced = _replace_by_stripped_lines(content, old_clean, new_clean)
        if replaced is None:
            preview = old_clean.replace("\n", "\\n")[:120]
            raise RuntimeError(f"edit #{i}: фрагмент old не найден: «{preview}»")
        content = replaced
    return content


def _replace_once(
    content: str,
    old: str,
    new: str,
    *,
    flexible: bool = False,
) -> str | None:
    if not old:
        return None
    if not flexible:
        count = content.count(old)
        if count == 1:
            return content.replace(old, new, 1)
        if count > 1:
            raise RuntimeError(
                f"фрагмент old встречается {count} раз — сделай длиннее"
            )
        return None

    # гибкий режим: допускаем CRLF и хвостовые пробелы на строках
    esc = re.escape(_normalize_ws(old))
    esc = esc.replace(r"\n", r"[ \t]*\r?\n")
    matches = list(re.finditer(esc, content))
    if len(matches) == 1:
        m = matches[0]
        return content[: m.start()] + new + content[m.end() :]
    if len(matches) > 1:
        raise RuntimeError(
            f"фрагмент old встречается {len(matches)} раз — сделай длиннее"
        )
    return None


def _replace_by_stripped_lines(content: str, old: str, new: str) -> str | None:
    """Сопоставить блок по содержимому строк без учёта отступов (модель часто теряет пробелы)."""
    old_lines = [ln.rstrip() for ln in _normalize_ws(old).strip("\n").split("\n")]
    # отбрасываем хвостовые пустые
    while old_lines and not old_lines[-1].strip():
        old_lines.pop()
    needles = [ln.strip() for ln in old_lines]
    if len(needles) < 2 or any(not n for n in needles):
        return None

    src_lines = content.splitlines(keepends=True)
    hits: list[tuple[int, int]] = []
    for i in range(len(src_lines) - len(needles) + 1):
        ok = True
        for j, needle in enumerate(needles):
            if src_lines[i + j].rstrip("\r\n").strip() != needle:
                ok = False
                break
        if ok:
            hits.append((i, i + len(needles)))
    if len(hits) != 1:
        return None
    start, end = hits[0]
    # сохранить перевод строки после блока, если был
    prefix = "".join(src_lines[:start])
    suffix = "".join(src_lines[end:])
    replacement = new
    if not replacement.endswith("\n") and suffix and src_lines[end - 1].endswith("\n"):
        # new без финального \n — ок, как в обычном replace
        pass
    return prefix + replacement + suffix


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
