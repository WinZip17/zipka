from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.memory.store import MemoryStore
from zipka.system_limits import max_book_bytes

BOOK_SUFFIXES = {".txt", ".md", ".markdown", ".fb2", ".xml", ".djvu", ".djv"}

CODE_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".kts",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".scala",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".psm1",
    ".bat",
    ".cmd",
    ".json",
    ".jsonc",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".vue",
    ".svelte",
    ".astro",
    ".lua",
    ".r",
    ".R",
    ".pl",
    ".pm",
    ".ex",
    ".exs",
    ".erl",
    ".hs",
    ".clj",
    ".dart",
    ".zig",
    ".nim",
    ".v",
    ".gradle",
    ".cmake",
    ".makefile",
    ".mk",
    ".dockerfile",
    ".tf",
    ".proto",
    ".graphql",
    ".gql",
    ".wasm",
}

ARCHIVE_SUFFIXES = {".zip", ".rar"}
READABLE_SUFFIXES = BOOK_SUFFIXES | CODE_SUFFIXES

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    ".idea",
    ".vscode",
    "vendor",
    "coverage",
}

MAX_CODE_BYTES = 1_500_000
# Динамический потолок для книг/архивов (см. zipka.system_limits.max_book_bytes)
MAX_BOOK_BYTES = max_book_bytes()


class BookReader:
    """Читает книги и исходники (.py/.js/.ts/…) в память."""

    def __init__(
        self,
        llm: Any,
        memory: MemoryStore,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.memory = memory
        ensure_data_dirs(self.settings)
        self.notes_dir = self.settings.data_dir / "books" / "notes"
        self.extract_dir = self.settings.data_dir / "books" / "extracted"
        self.extract_dir.mkdir(parents=True, exist_ok=True)

    def read(
        self,
        path: str | Path,
        *,
        max_chunks: int = 6,
        member: str | None = None,
        max_files: int = 24,
        comment: str | None = None,
        mode: str | None = None,
    ) -> dict:
        file_path = Path(path).expanduser().resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        if file_path.is_dir():
            return self._read_directory(
                file_path,
                max_chunks=max_chunks,
                max_files=max_files,
                comment=comment,
                mode=mode,
            )

        source_label = file_path.name
        inner_name: str | None = None
        work_path = file_path
        if file_path.suffix.lower() in ARCHIVE_SUFFIXES:
            work_path, inner_name = self._extract_book(file_path, member=member)
            source_label = f"{file_path.name}:{inner_name}"

        return self._summarize_file(
            work_path,
            source_label=source_label,
            origin=str(file_path),
            archive_member=inner_name,
            max_chunks=max_chunks,
            comment=comment,
        )

    def list_archive_books(self, path: str | Path) -> list[str]:
        file_path = Path(path).expanduser().resolve()
        suffix = file_path.suffix.lower()
        if suffix == ".zip":
            return self._list_zip_books(file_path)
        if suffix == ".rar":
            return self._list_rar_books(file_path)
        raise ValueError("Ожидается .zip или .rar")

    def _read_directory(
        self,
        directory: Path,
        *,
        max_chunks: int,
        max_files: int,
        comment: str | None = None,
        mode: str | None = None,
    ) -> dict:
        files = self._collect_readable_files(directory, mode=mode)[:max_files]
        if not files:
            raise RuntimeError(
                f"В `{directory}` нет читаемых файлов "
                f"(книги/исходники). Проверь расширения или mode=books|code."
            )

        book_n = sum(1 for f in files if self._kind_for(f) == "book")
        code_n = len(files) - book_n
        if book_n and code_n:
            folder_kind = "folder_mixed"
        elif code_n:
            folder_kind = "folder_code"
        else:
            folder_kind = "folder_books"

        digests: list[str] = []
        total_chunks = 0
        per_file_chunks = max(2, max_chunks // max(1, min(len(files), 5)))
        for fp in files:
            part = self._summarize_file(
                fp,
                source_label=str(fp.relative_to(directory)),
                origin=str(fp),
                archive_member=None,
                max_chunks=per_file_chunks,
                comment=comment,
            )
            digests.append(
                f"## {fp.relative_to(directory).as_posix()}\n\n{part['digest']}"
            )
            total_chunks += part["chunks"]

        digest = "\n\n".join(digests)
        overview = ""
        try:
            overview = self.llm.summarize(
                digest[:14000],
                instruction=(
                    f"Сделай обзор папки «{directory.name}» ({folder_kind}): "
                    f"книг={book_n}, кода={code_n}. Структура, назначение, "
                    "главные темы/модули, на что обратить внимание."
                    + (
                        f" Фокус пользователя: {comment}"
                        if comment
                        else ""
                    )
                ),
            )
        except Exception:
            overview = ""

        out = self.notes_dir / f"{directory.name}_dir_digest.md"
        header = (
            f"# Изучение папки: {directory}\n\n"
            f"Тип: {folder_kind}\n"
            f"Файлов: {len(files)} (книги={book_n}, код={code_n})\n"
        )
        if comment:
            header += f"\nКомментарий пользователя: {comment}\n"
        if overview:
            header += f"\n## Обзор\n\n{overview}\n"
        out.write_text(f"{header}\n{digest}\n", encoding="utf-8")

        note_kind = "code" if folder_kind != "folder_books" else "book"
        self.memory.add_note(
            note_kind,
            (overview or f"Изучена папка {directory} ({len(files)} файлов).")
            + (f" Комментарий: {comment}" if comment else ""),
            meta={
                "source": str(directory),
                "files": [str(f) for f in files],
                "comment": comment,
                "folder_kind": folder_kind,
            },
        )
        return {
            "source": str(directory),
            "archive_member": None,
            "chunks": total_chunks,
            "digest_path": str(out),
            "digest": (overview + "\n\n" + digest) if overview else digest,
            "overview": overview,
            "kind": folder_kind,
            "files": [str(f) for f in files],
            "comment": comment,
            "book_count": book_n,
            "code_count": code_n,
            "is_project": folder_kind in {"folder_code", "folder_mixed"},
        }

    def _summarize_file(
        self,
        path: Path,
        *,
        source_label: str,
        origin: str,
        archive_member: str | None,
        max_chunks: int,
        comment: str | None = None,
    ) -> dict:
        kind = self._kind_for(path)
        text = self._load_text(path)
        if not text.strip():
            raise RuntimeError(f"Файл пуст или не прочитан: {path}")

        if kind == "book":
            return self._summarize_book(
                text,
                path=path,
                source_label=source_label,
                origin=origin,
                archive_member=archive_member,
                comment=comment,
            )

        # Код: несколько коротких проходов, но не больше 3 (было 6 — слишком медленно)
        chunks = self._chunk(text, size=3500)[: max(1, min(int(max_chunks), 3))]
        summaries: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            instruction = self._instruction(
                kind, source_label, i, len(chunks), comment=comment
            )
            summary = self.llm.summarize(chunk, instruction=instruction)
            summaries.append(summary)
        digest = "\n\n".join(summaries)
        # одна заметка, а не по куску — иначе раздувается system prompt
        self.memory.add_note(
            kind,
            digest[:1800],
            meta={
                "source": origin,
                "archive_member": archive_member,
                "chunks": len(chunks),
                "path": str(path),
                "comment": comment,
            },
        )
        return self._write_digest(
            digest=digest,
            origin=origin,
            archive_member=archive_member,
            source_label=source_label,
            kind=kind,
            comment=comment,
            chunks=len(chunks),
        )

    def _summarize_book(
        self,
        text: str,
        *,
        path: Path,
        source_label: str,
        origin: str,
        archive_member: str | None,
        comment: str | None = None,
    ) -> dict:
        """Один вызов LLM по выборке из начала/середины/конца — не 6 проходов подряд."""
        sample = self._sample_book_text(text, budget=10_000)
        focus = ""
        if comment and comment.strip():
            focus = (
                f"\nКомментарий/фокус пользователя (обязательно учти): {comment.strip()}\n"
                "Отвечай в первую очередь на этот фокус, остальное — кратко."
            )
        chars = len(text)
        instruction = (
            f"Сделай краткую выжимку книги «{source_label}» "
            f"(~{chars} символов текста; ниже — выборка начала/середины/конца). "
            "Сюжет, герои, тон, ключевые идеи. Не цитируй длинные куски дословно."
            f"{focus}"
        )
        digest = self.llm.summarize(sample, instruction=instruction)
        self.memory.add_note(
            "book",
            digest[:1800],
            meta={
                "source": origin,
                "archive_member": archive_member,
                "chunks": 1,
                "chars": chars,
                "sampled_chars": len(sample),
                "path": str(path),
                "comment": comment,
            },
        )
        return self._write_digest(
            digest=digest,
            origin=origin,
            archive_member=archive_member,
            source_label=source_label,
            kind="book",
            comment=comment,
            chunks=1,
        )

    def _write_digest(
        self,
        *,
        digest: str,
        origin: str,
        archive_member: str | None,
        source_label: str,
        kind: str,
        comment: str | None,
        chunks: int,
    ) -> dict:
        digest_stem = Path(origin).stem
        if archive_member:
            digest_stem = f"{Path(origin).stem}__{Path(archive_member).stem}"
        out = self.notes_dir / f"{digest_stem}_digest.md"
        title = "Код" if kind == "code" else "Выжимка"
        header = f"# {title}: {source_label}\n"
        if comment:
            header += f"\nКомментарий пользователя: {comment}\n"
        out.write_text(f"{header}\n{digest}\n", encoding="utf-8")
        return {
            "source": origin,
            "archive_member": archive_member,
            "chunks": chunks,
            "digest_path": str(out),
            "digest": digest,
            "kind": kind,
            "comment": comment,
        }

    @staticmethod
    def _sample_book_text(text: str, *, budget: int = 10_000) -> str:
        """Выборка по книге: начало / четверти / конец. Дешевле, чем гнать все чанки в LLM."""
        text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
        if not text:
            return ""
        if len(text) <= budget:
            return text
        # 5 окон
        win = max(800, budget // 5)
        n = len(text)
        starts = [
            0,
            max(0, n // 4 - win // 2),
            max(0, n // 2 - win // 2),
            max(0, (3 * n) // 4 - win // 2),
            max(0, n - win),
        ]
        parts: list[str] = []
        seen: set[int] = set()
        for s in starts:
            s = min(s, max(0, n - 1))
            key = s // max(win // 2, 1)
            if key in seen:
                continue
            seen.add(key)
            parts.append(text[s : s + win].strip())
        return "\n\n---\n\n".join(p for p in parts if p)

    @staticmethod
    def _kind_for(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in CODE_SUFFIXES:
            return "code"
        if suffix in BOOK_SUFFIXES:
            return "book"
        return "book"

    @staticmethod
    def _instruction(
        kind: str,
        source_label: str,
        i: int,
        n: int,
        *,
        comment: str | None = None,
    ) -> str:
        focus = ""
        if comment and comment.strip():
            focus = (
                f"\nКомментарий/фокус пользователя (обязательно учти): {comment.strip()}\n"
                "Отвечай в первую очередь на этот фокус, остальное — кратко."
            )
        if kind == "code":
            return (
                f"Изучи фрагмент {i}/{n} исходника «{source_label}». "
                "Кратко: назначение, ключевые функции/классы/API, зависимости, "
                "важные паттерны и риски. Не копируй длинные куски кода."
                f"{focus}"
            )
        return (
            f"Сделай краткую выжимку фрагмента {i}/{n} книги "
            f"«{source_label}». Не цитируй длинные куски дословно."
            f"{focus}"
        )

    def _collect_readable_files(
        self, root: Path, *, mode: str | None = None
    ) -> list[Path]:
        mode = (mode or "auto").lower()
        if mode == "books":
            allowed = BOOK_SUFFIXES
        elif mode == "code":
            allowed = CODE_SUFFIXES
        else:
            allowed = READABLE_SUFFIXES

        found: list[Path] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix.lower() not in allowed:
                continue
            try:
                size = path.stat().st_size
                limit = (
                    MAX_BOOK_BYTES
                    if path.suffix.lower() in BOOK_SUFFIXES
                    else MAX_CODE_BYTES
                )
                if size > limit:
                    continue
            except OSError:
                continue
            found.append(path)

        def rank(p: Path) -> tuple:
            name = p.name.lower()
            boost = 0
            if name in {
                "main.py",
                "app.py",
                "index.ts",
                "index.js",
                "main.ts",
                "main.go",
                "readme.md",
            }:
                boost = -10
            if p.suffix.lower() in CODE_SUFFIXES:
                boost -= 1
            return (boost, len(p.parts), str(p).lower())

        return sorted(found, key=rank)

    def _collect_source_files(self, root: Path) -> list[Path]:
        return self._collect_readable_files(root, mode="code")

    def _extract_book(
        self, archive: Path, *, member: str | None = None
    ) -> tuple[Path, str]:
        suffix = archive.suffix.lower()
        if suffix == ".zip":
            members = self._list_zip_books(archive)
            chosen = self._pick_member(members, member)
            return self._extract_zip_member(archive, chosen), chosen
        if suffix == ".rar":
            members = self._list_rar_books(archive)
            chosen = self._pick_member(members, member)
            return self._extract_rar_member(archive, chosen), chosen
        raise ValueError(f"Неподдерживаемый архив: {suffix}")

    @staticmethod
    def _pick_member(members: list[str], member: str | None) -> str:
        if not members:
            raise RuntimeError(
                "В архиве нет читаемых файлов "
                "(книги или исходники .py/.js/.ts/…)."
            )
        if member:
            for name in members:
                if name == member or name.lower() == member.lower():
                    return name
                if Path(name).name.lower() == Path(member).name.lower():
                    return name
            raise FileNotFoundError(
                f"Файл «{member}» не найден в архиве. Есть: {', '.join(members[:40])}"
            )
        for preferred in (
            ".fb2",
            ".djvu",
            ".djv",
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".go",
            ".rs",
            ".txt",
            ".md",
            ".xml",
        ):
            for name in members:
                if Path(name).suffix.lower() == preferred:
                    return name
        return members[0]

    def _list_zip_books(self, archive: Path) -> list[str]:
        with zipfile.ZipFile(archive, "r") as zf:
            names = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if Path(name).suffix.lower() in READABLE_SUFFIXES:
                    names.append(name)
            return sorted(names)

    def _extract_zip_member(self, archive: Path, member: str) -> Path:
        target_dir = self.extract_dir / archive.stem
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "r") as zf:
            dest = (target_dir / Path(member).name).resolve()
            if not str(dest).startswith(str(target_dir.resolve())):
                raise RuntimeError("Небезопасный путь внутри ZIP.")
            with zf.open(member) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
        return dest

    def _rarfile(self):
        try:
            import rarfile
        except ImportError as exc:
            raise RuntimeError(
                "Для .rar нужен пакет rarfile: pip install rarfile"
            ) from exc
        return rarfile

    def _list_rar_books(self, archive: Path) -> list[str]:
        rarfile = self._rarfile()
        try:
            with rarfile.RarFile(archive) as rf:
                names = []
                for info in rf.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename
                    if Path(name).suffix.lower() in READABLE_SUFFIXES:
                        names.append(name.replace("\\", "/"))
                return sorted(names)
        except rarfile.NeedFirstVolume as exc:
            raise RuntimeError("Нужен первый том многотомного RAR.") from exc
        except rarfile.RarCannotExec as exc:
            raise RuntimeError(
                "Для RAR нужен UnRAR/WinRAR в PATH "
                "(или установи UnRAR и укажи rarfile.UNRAR_TOOL)."
            ) from exc

    def _extract_rar_member(self, archive: Path, member: str) -> Path:
        rarfile = self._rarfile()
        target_dir = self.extract_dir / archive.stem
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = (target_dir / Path(member).name).resolve()
        if not str(dest).startswith(str(target_dir.resolve())):
            raise RuntimeError("Небезопасный путь внутри RAR.")
        try:
            with rarfile.RarFile(archive) as rf:
                with rf.open(member) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
        except rarfile.RarCannotExec as exc:
            raise RuntimeError(
                "Для RAR нужен UnRAR/WinRAR в PATH."
            ) from exc
        return dest

    def _load_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".djvu", ".djv"}:
            return self._djvu_to_text(path)
        raw = path.read_text(encoding="utf-8", errors="ignore")
        if suffix in {".txt", ".md", ".markdown"}:
            return raw
        if suffix in {".fb2"} or (
            suffix == ".xml" and "<FictionBook" in raw[:2000]
        ):
            return self._fb2_to_text(raw)
        return raw

    def _find_djvutxt(self) -> str | None:
        """Найти djvutxt в PATH или типичных путях Windows."""
        found = shutil.which("djvutxt") or shutil.which("djvutxt.exe")
        if found:
            return found
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "DjVuLibre"
            / "djvutxt.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "DjVuLibre"
            / "djvutxt.exe",
            Path(r"C:\DjVuLibre\djvutxt.exe"),
            Path.home() / "AppData" / "Local" / "Programs" / "DjVuLibre" / "djvutxt.exe",
        ]
        for path in candidates:
            if path.is_file():
                return str(path)
        return None

    def _djvu_to_text(self, path: Path) -> str:
        """Извлечь текст из DJVU: сначала встроенный djvu-rs, затем djvutxt."""
        text = self._djvu_via_rs(path)
        if text is not None:
            return text

        import subprocess

        djvutxt = self._find_djvutxt()
        if djvutxt:
            try:
                proc = subprocess.run(
                    [djvutxt, str(path)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=180,
                    check=False,
                )
                text = (proc.stdout or "").strip()
                if text:
                    return text
                err = (proc.stderr or "").strip()
                raise RuntimeError(
                    "djvutxt не извлёк текст из DJVU"
                    + (f": {err}" if err else " (пустой текстовый слой / скан без OCR).")
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"djvutxt не смог прочитать DJVU: {exc}") from exc

        raise RuntimeError(
            "Не удалось прочитать DJVU.\n"
            "Установи зависимость: pip install djvu-rs\n"
            "Если файл — скан без текстового слоя (без OCR), текста в нём нет."
        )

    def _djvu_via_rs(self, path: Path) -> str | None:
        """Читалка на djvu-rs (wheel, без системного DjVuLibre). None = пакет нет."""
        try:
            import djvu_rs
        except ImportError:
            return None

        try:
            doc = djvu_rs.Document.open(str(path.resolve()))
            parts: list[str] = []
            for i in range(doc.page_count()):
                page = doc.page(i)
                chunk = ""
                try:
                    raw = page.text()
                    if raw:
                        chunk = str(raw).strip()
                except Exception:
                    chunk = ""
                if not chunk:
                    try:
                        layer = page.text_layer()
                        if layer is not None:
                            chunk = str(layer).strip()
                    except Exception:
                        pass
                if chunk:
                    parts.append(chunk)
            joined = "\n\n".join(parts).strip()
            if not joined:
                raise RuntimeError(
                    "DJVU открыт (djvu-rs), но текстовый слой пуст "
                    "(возможно, это скан без OCR)."
                )
            return joined
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Не удалось разобрать DJVU (djvu-rs): {exc}") from exc

    def _fb2_to_text(self, raw: str) -> str:
        """FB2 → текст. Streaming parse, без повторного обхода всего дерева в памяти."""
        import io

        cleaned = re.sub(r'xmlns(:\w+)?="[^"]+"', "", raw)
        parts: list[str] = []
        max_chars = 400_000  # хватит для выборки; не тащим мегароманы целиком в LLM
        try:
            for _event, elem in ET.iterparse(io.StringIO(cleaned), events=("end",)):
                tag = elem.tag.split("}")[-1].lower()
                if tag in {"p", "v", "subtitle", "text-author"}:
                    bits = []
                    if elem.text and elem.text.strip():
                        bits.append(elem.text.strip())
                    for child in elem:
                        if child.tail and child.tail.strip():
                            bits.append(child.tail.strip())
                    if bits:
                        parts.append(" ".join(bits))
                elif tag == "title":
                    title_bits = [
                        (t or "").strip()
                        for t in elem.itertext()
                        if (t or "").strip()
                    ]
                    if title_bits:
                        parts.append(" ".join(title_bits))
                # освобождаем поддерево
                elem.clear()
                if sum(len(p) for p in parts) >= max_chars:
                    break
        except ET.ParseError:
            rough = re.sub(r"<[^>]+>", " ", raw)
            return re.sub(r"\s+", " ", rough)[:max_chars].strip()
        text = "\n".join(p for p in parts if p)
        return text[:max_chars]

    @staticmethod
    def _chunk(text: str, size: int = 3500) -> list[str]:
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            return []
        return [text[i : i + size] for i in range(0, len(text), size)]
