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
    ) -> dict[str, Any]:
        root = None
        if project_root:
            root = self.remember_project(project_root)
        else:
            root = self.last_project()

        base = root or ROOT_DIR
        tree = self._list_editable_files(prefer_root=root)
        scope_hint = (
            f"Проект: {root}. Пути указывай относительно этой папки."
            if root
            else "Можно менять файлы внутри zipka/ и web/ (пути от корня Zipka)."
        )
        raw = self.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Ты модуль hard-evolve Зипки. Верни ТОЛЬКО JSON:\n"
                        '{"files": [{"path": "relative/path.ext", '
                        '"content": "полный новый текст файла"}]}\n'
                        f"{scope_hint} Не трогай .env и секреты."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Запрос: {request}\n\n"
                        + (f"Контекст изучения:\n{context[:8000]}\n\n" if context else "")
                        + "Доступные файлы:\n"
                        + "\n".join(tree[:100])
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
            abs_path = (base / rel).resolve() if root else (ROOT_DIR / rel).resolve()
            if not self._is_allowed(abs_path):
                continue
            # store path relative to base for apply
            try:
                store_rel = abs_path.relative_to(base).as_posix() if root else abs_path.relative_to(ROOT_DIR).as_posix()
            except ValueError:
                continue
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

        meta = {
            "id": patch_id,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "files": applied,
            "request": pending.get("request"),
            "project_root": pending.get("project_root"),
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
        files: list[str] = []
        roots = [prefer_root] if prefer_root else self.allowed_roots
        if prefer_root and prefer_root not in self.allowed_roots:
            roots = [prefer_root, *self.allowed_roots]
        for root in roots:
            if not root or not root.exists():
                continue
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                if any(part in {".git", "node_modules", ".venv", "venv", "__pycache__"} for part in p.parts):
                    continue
                if p.suffix.lower() not in EDITABLE_SUFFIXES:
                    continue
                if p.name.lower() in BLOCKED_NAMES:
                    continue
                try:
                    files.append(p.relative_to(root).as_posix())
                except ValueError:
                    continue
        # unique keep order
        seen = set()
        out = []
        for f in files:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out


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
