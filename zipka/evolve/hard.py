from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zipka.config import ROOT_DIR, Settings, ensure_data_dirs, get_settings
from zipka.llm.ollama_client import OllamaClient
from zipka.memory.store import MemoryStore

APPROVE_PHRASE = "разрешаю правку кода"
APPROVE_PHRASES = {
    APPROVE_PHRASE,
    "разрешаю правку кода.",
    "approve code patch",
    "approve patch",
}

BLOCKED_NAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}

EDITABLE_SUFFIXES = {
    ".py",
    ".html",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".css",
    ".md",
    ".yaml",
    ".yml",
    ".txt",
    ".json",
    ".toml",
    ".go",
    ".rs",
    ".java",
    ".cs",
}

# Правила для правок React UI (MUI) — в system prompt hard-evolve
FRONTEND_EDIT_RULES = """
Правила UI (web/frontend, React + MUI v9 + Emotion):
1. Стили ТОЛЬКО через prop sx={{ ... }} или theme. Никакого нативного CSS в JSX.
2. Запрещено: style="color:red", style={'color: red'}, <style>...</style>,
   class="...", inline CSS-строки, отдельные .css ради одной кнопки.
3. В sx используй camelCase: backgroundColor, borderRadius, fontSize — не
   background-color / border-radius.
4. Не подменяй MUI-компоненты (Box, Stack, Button, InputBase, Typography…) на
   голые div/button/input, если задача этого не требует.
5. Сохраняй существующие импорты @mui/material и @mui/icons-material.
6. Не пиши CSS-селекторы (.class {}, #id {}) внутрь TSX/JSX.
7. Меняй минимум строк; копируй стиль соседнего кода один в один.
""".strip()


class HardEvolve:
    """Правки кода только после явного approve (Zipka и/или изученный проект)."""

    def __init__(
        self,
        llm: OllamaClient,
        memory: MemoryStore,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.memory = memory
        ensure_data_dirs(self.settings)
        self.patches_dir = self.settings.data_dir / "patches"
        self.pending_path = self.patches_dir / "pending.json"
        self.projects_path = self.settings.data_dir / "mind" / "projects.json"
        self.allowed_roots = [
            self.settings.package_dir.resolve(),
            self.settings.web_dir.resolve(),
        ]
        self._load_project_roots()

    def _load_project_roots(self) -> None:
        if not self.projects_path.exists():
            return
        try:
            data = json.loads(self.projects_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for item in data.get("roots") or []:
            try:
                root = Path(item).expanduser().resolve()
            except OSError:
                continue
            if root.is_dir() and root not in self.allowed_roots:
                self.allowed_roots.append(root)

    def remember_project(self, path: str | Path) -> Path:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Не папка: {root}")
        data = {"roots": [], "last": str(root)}
        if self.projects_path.exists():
            try:
                data = json.loads(self.projects_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        roots = [str(root)]
        for r in data.get("roots") or []:
            if r != str(root):
                roots.append(r)
        data["roots"] = roots[:8]
        data["last"] = str(root)
        self.projects_path.parent.mkdir(parents=True, exist_ok=True)
        self.projects_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if root not in self.allowed_roots:
            self.allowed_roots.append(root)
        return root

    def last_project(self) -> Path | None:
        if not self.projects_path.exists():
            return None
        try:
            data = json.loads(self.projects_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        last = data.get("last")
        if not last:
            return None
        p = Path(last)
        return p if p.exists() else None

    def wants_code_change(self, text: str) -> bool:
        lowered = text.lower()
        keys = [
            "измени свой код",
            "правь код",
            "поправь код",
            "self-modify",
            "измени модуль",
            "добавь в код",
            "hard evolve",
            "перепиши файл",
            "предложи правки",
            "внеси правки",
            "поправь проект",
            "измени проект",
            "сделай правки",
            "отрефактори",
            "поменяй в интерфейсе",
            "поправь интерфейс",
            "поменяй ui",
            "измени ui",
            "в своём коде",
            "в своем коде",
            "сама себя",
            "себя поправь",
            "поправь себя",
            "textarea",
            "текстареа",
            "поле ввода",
        ]
        return any(k in lowered for k in keys)

    def wants_self_edit(self, text: str) -> bool:
        """Правки самой Зипки (zipka/ + web/), а не внешнего last_project."""
        lowered = text.lower()
        keys = [
            "себе",
            "себя",
            "свой код",
            "своём коде",
            "своем коде",
            "свою",
            "зипк",
            "zipka",
            "интерфейс",
            "в чате",
            "ui",
            "composer",
            "textarea",
            "текстареа",
            "поле ввода",
            "web/frontend",
            "фронтенд",
            "frontend",
        ]
        return any(k in lowered for k in keys)

    def is_approve(self, text: str) -> bool:
        return text.strip().lower() in APPROVE_PHRASES

    def has_pending(self) -> bool:
        return self.pending_path.exists()

    def load_pending(self) -> dict[str, Any] | None:
        if not self.pending_path.exists():
            return None
        return json.loads(self.pending_path.read_text(encoding="utf-8"))

    def clear_pending(self) -> None:
        if self.pending_path.exists():
            self.pending_path.unlink()

    def propose(
        self,
        request: str,
        *,
        project_root: str | Path | None = None,
        context: str | None = None,
        self_edit: bool = False,
    ) -> dict[str, Any]:
        if self_edit:
            root = None
        elif project_root:
            root = self.remember_project(project_root)
        else:
            root = self.last_project()

        base = root or ROOT_DIR
        tree = self._list_editable_files(prefer_root=root)
        focus_files = self._pick_focus_files(request, tree, limit=4)
        focus_blobs: list[str] = []
        for rel in focus_files:
            abs_path = (base / rel).resolve()
            try:
                if abs_path.is_file() and abs_path.stat().st_size < 120_000:
                    body = abs_path.read_text(encoding="utf-8", errors="ignore")
                    focus_blobs.append(f"### {rel}\n```\n{body}\n```")
            except OSError:
                continue

        scope_hint = (
            f"Проект: {root}. Пути указывай относительно этой папки."
            if root
            else (
                "Это самоправка Зипки. Пути относительно корня репозитория Zipka, "
                "например: zipka/agent.py, web/frontend/src/components/Composer.tsx. "
                "Меняй только zipka/ и web/. UI чата — в web/frontend/src/."
            )
        )
        touches_frontend = any(
            f.replace("\\", "/").startswith("web/frontend/")
            or f.endswith((".tsx", ".jsx"))
            for f in focus_files
        ) or any(
            k in request.lower()
            for k in (
                "интерфейс",
                "ui",
                "jsx",
                "tsx",
                "mui",
                "кнопк",
                "чат",
                "composer",
                "textarea",
                "инпут",
                "поле ввода",
                "frontend",
            )
        )
        system = (
            "Ты модуль hard-evolve Зипки. Верни ТОЛЬКО JSON:\n"
            '{"files": [{"path": "relative/path.ext", '
            '"content": "полный новый текст файла"}]}\n'
            f"{scope_hint} Не трогай .env, secrets, node_modules, dist. "
            "Меняй минимум файлов. "
        )
        if touches_frontend or self_edit:
            system += "\n" + FRONTEND_EDIT_RULES
        else:
            system += (
                "Если правишь React — сохрани существующие импорты и поведение, "
                "кроме запрошенного."
            )

        raw = self.llm.chat(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"Запрос: {request}\n\n"
                        + (f"Контекст изучения:\n{context[:8000]}\n\n" if context else "")
                        + (
                            "Текущие файлы для правки:\n"
                            + "\n\n".join(focus_blobs)
                            + "\n\n"
                            if focus_blobs
                            else ""
                        )
                        + "Доступные файлы:\n"
                        + "\n".join(tree[:120])
                    ),
                },
            ]
        )
        data = _extract_json(raw) or {"files": []}
        files = []
        for item in data.get("files", []):
            rel = str(item.get("path", "")).replace("\\", "/").lstrip("/")
            content = item.get("content")
            if not rel or content is None:
                continue
            if Path(rel).name.lower() in BLOCKED_NAMES:
                continue
            abs_path = (base / rel).resolve()
            if not self._is_allowed(abs_path):
                continue
            try:
                store_rel = abs_path.relative_to(base).as_posix()
            except ValueError:
                continue
            bad = self._frontend_style_problems(store_rel, str(content))
            if bad:
                raise RuntimeError(
                    "Патч отклонён: в JSX нельзя так стилизовать (нативный CSS). "
                    + bad
                    + " Переформулируй запрос или попроси снова: стили только через sx={{…}}."
                )
            files.append({"path": store_rel, "content": content})
        if not files:
            raise RuntimeError(
                "Не удалось сформировать безопасный патч. Уточни, какой файл править."
            )
        patch_id = (
            datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        pending = {
            "id": patch_id,
            "request": request,
            "files": files,
            "project_root": str(root) if root else None,
            "self_edit": bool(self_edit or root is None),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending_approval",
        }
        self.pending_path.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.memory.log_evolve(
            "hard_propose",
            {
                "id": patch_id,
                "files": [f["path"] for f in files],
                "request": request,
                "project_root": pending["project_root"],
                "self_edit": pending["self_edit"],
            },
        )
        return pending

    def apply_pending(self) -> dict[str, Any]:
        pending = self.load_pending()
        if not pending:
            raise RuntimeError("Нет ожидающего патча.")
        patch_id = pending["id"]
        base = (
            Path(pending["project_root"]).resolve()
            if pending.get("project_root")
            else ROOT_DIR
        )
        if pending.get("project_root"):
            self.remember_project(base)

        backup_dir = self.patches_dir / patch_id / "backup"
        new_dir = self.patches_dir / patch_id / "new"
        backup_dir.mkdir(parents=True, exist_ok=True)
        new_dir.mkdir(parents=True, exist_ok=True)

        applied = []
        for item in pending["files"]:
            rel = item["path"]
            abs_path = (base / rel).resolve()
            if not self._is_allowed(abs_path):
                raise RuntimeError(f"Путь вне sandbox: {rel}")
            if abs_path.name.lower() in BLOCKED_NAMES:
                raise RuntimeError(f"Файл запрещён: {rel}")
            backup_file = backup_dir / rel
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            if abs_path.exists():
                shutil.copy2(abs_path, backup_file)
            else:
                backup_file.write_text("", encoding="utf-8")
            new_file = new_dir / rel
            new_file.parent.mkdir(parents=True, exist_ok=True)
            new_file.write_text(item["content"], encoding="utf-8")
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(item["content"], encoding="utf-8")
            applied.append(rel)

        rebuild_note = None
        if any(
            rel.replace("\\", "/").startswith("web/frontend/")
            or "/frontend/src/" in rel.replace("\\", "/")
            for rel in applied
        ):
            rebuild_note = self._maybe_rebuild_frontend()

        meta = {
            "id": patch_id,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "files": applied,
            "request": pending.get("request"),
            "project_root": pending.get("project_root"),
            "frontend_rebuild": rebuild_note,
        }
        (self.patches_dir / patch_id / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.clear_pending()
        self.memory.log_evolve("hard_apply", meta)
        return meta

    def rollback(self, patch_id: str) -> dict[str, Any]:
        backup_dir = self.patches_dir / patch_id / "backup"
        new_dir = self.patches_dir / patch_id / "new"
        meta_path = self.patches_dir / patch_id / "meta.json"
        if not backup_dir.exists():
            raise RuntimeError(f"Бэкап {patch_id} не найден.")
        base = ROOT_DIR
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("project_root"):
                base = Path(meta["project_root"]).resolve()
                self.remember_project(base)
        restored: list[str] = []
        for backup_file in backup_dir.rglob("*"):
            if not backup_file.is_file():
                continue
            rel = backup_file.relative_to(backup_dir).as_posix()
            target = (base / rel).resolve()
            if not self._is_allowed(target):
                continue
            content = backup_file.read_text(encoding="utf-8")
            previously_missing = content == "" and (new_dir / rel).exists()
            if previously_missing:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            restored.append(rel)
        result = {"id": patch_id, "restored": restored}
        self.memory.log_evolve("hard_rollback", result)
        return result

    def format_pending(self, pending: dict[str, Any] | None = None) -> str:
        pending = pending or self.load_pending()
        if not pending:
            return "Нет ожидающего патча."
        root = pending.get("project_root") or str(ROOT_DIR)
        lines = [
            f"Патч {pending['id']} ждёт approve.",
            f"Корень: {root}",
            f"Запрос: {pending.get('request', '')}",
            "Файлы:",
            *[f"- {f['path']} ({len(f['content'])} символов)" for f in pending["files"]],
            f"Чтобы применить, напиши точно: {APPROVE_PHRASE}",
            "Или нажми кнопку «Разрешаю правку кода» в web.",
        ]
        return "\n".join(lines)

    def _is_allowed(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        if resolved.name.lower() in BLOCKED_NAMES:
            return False
        return any(
            resolved == root or root in resolved.parents for root in self.allowed_roots
        )

    def _list_editable_files(
        self, *, prefer_root: Path | None = None
    ) -> list[str]:
        """Для самоправки пути относительно ROOT_DIR (zipka/..., web/...)."""
        files: list[str] = []
        skip = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist"}

        if prefer_root is None:
            scan_roots = [
                self.settings.package_dir.resolve(),
                self.settings.web_dir.resolve(),
            ]
            for root in scan_roots:
                if not root.exists():
                    continue
                for p in root.rglob("*"):
                    if not p.is_file():
                        continue
                    if any(part in skip for part in p.parts):
                        continue
                    if p.suffix.lower() not in EDITABLE_SUFFIXES:
                        continue
                    if p.name.lower() in BLOCKED_NAMES:
                        continue
                    try:
                        files.append(p.relative_to(ROOT_DIR).as_posix())
                    except ValueError:
                        continue
        else:
            root = prefer_root.resolve()
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                if any(part in skip for part in p.parts):
                    continue
                if p.suffix.lower() not in EDITABLE_SUFFIXES:
                    continue
                if p.name.lower() in BLOCKED_NAMES:
                    continue
                try:
                    files.append(p.relative_to(root).as_posix())
                except ValueError:
                    continue

        seen: set[str] = set()
        out: list[str] = []
        for f in files:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def _pick_focus_files(
        self, request: str, tree: list[str], *, limit: int = 4
    ) -> list[str]:
        lowered = request.lower()
        scored: list[tuple[int, str]] = []
        hints = [
            ("composer", 50),
            ("textarea", 40),
            ("input", 20),
            ("чат", 25),
            ("сообщен", 25),
            ("интерфейс", 15),
            ("sidepanel", 30),
            ("app.tsx", 20),
            ("agent.py", 15),
            ("style", 10),
            ("frontend", 10),
        ]
        for rel in tree:
            score = 0
            name = rel.lower()
            for hint, w in hints:
                if hint in lowered and hint in name:
                    score += w
            if "composer" in name:
                score += 10
            if score:
                scored.append((score, rel))
        scored.sort(key=lambda x: (-x[0], x[1]))
        picked = [rel for _, rel in scored[:limit]]
        if any(
            k in lowered
            for k in ("textarea", "текстареа", "поле ввода", "инпут", "input", "сообщен", "интерфейс", "ui", "кнопк")
        ):
            cand = "web/frontend/src/components/Composer.tsx"
            if cand in tree and cand not in picked:
                picked.insert(0, cand)
            theme = "web/frontend/src/theme.ts"
            if theme in tree and theme not in picked:
                picked.append(theme)
        return picked[:limit]

    def _frontend_style_problems(self, rel: str, content: str) -> str | None:
        """Поймать типичный «нативный CSS» в JSX/TSX патчах."""
        path = rel.replace("\\", "/").lower()
        if not path.endswith((".tsx", ".jsx")):
            return None
        if not (
            "web/frontend/" in path
            or "/frontend/" in path
            or path.startswith("frontend/")
        ):
            # внешние проекты не жёстко валидируем тем же MUI-контрактом
            if "mui" not in content.lower() and "sx={{" not in content:
                return None

        problems: list[str] = []
        # HTML-style attribute
        if re.search(r"\bstyle\s*=\s*['\"][^'\"]*[;:][^'\"]*['\"]", content):
            problems.append("найден style=\"…\" со CSS-строкой")
        if re.search(r"\bstyle\s*=\s*\{\s*['`][^'`]+:[^'`]+['`]\s*\}", content):
            problems.append("найден style={'css: ...'} — нужна sx={{ camelCase }}")
        if re.search(r"<\s*style[\s>]", content, re.I):
            problems.append("найден тег <style>")
        if re.search(r"\bclass\s*=\s*['\"]", content):
            problems.append("найден class=… (в React нужен className или sx)")
        # CSS rule blocks dumped into TSX
        if re.search(r"\{[^{}]*[a-z-]+\s*:\s*[^;]+;[^{}]*\}", content) and re.search(
            r"\.[a-zA-Z_][\w-]*\s*\{", content
        ):
            problems.append("похоже на CSS-селекторы (.class { … }) внутри TSX")
        # kebab-case in sx object keys without quotes is SyntaxError; with quotes is smell
        if re.search(r"sx=\{\{[^}]*['\"][a-z]+-[a-z]+['\"]\s*:", content):
            problems.append("в sx ключи с дефисом — используй camelCase (backgroundColor)")
        if problems:
            return "; ".join(problems)
        return None

    def _maybe_rebuild_frontend(self) -> str | None:
        """Пересобрать React UI после правок исходников."""
        import subprocess

        frontend = ROOT_DIR / "web" / "frontend"
        if not (frontend / "package.json").exists():
            return None
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            return "npm не найден — собери вручную: cd web/frontend && npm run build"
        try:
            proc = subprocess.run(
                [npm, "run", "build"],
                cwd=str(frontend),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=180,
                check=False,
            )
            if proc.returncode == 0:
                return "web/frontend: npm run build OK"
            err = (proc.stderr or proc.stdout or "").strip()[-500:]
            return f"web/frontend build failed: {err}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"web/frontend build error: {exc}"


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
