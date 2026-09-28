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


class HardEvolve:
    """Правки собственного кода только после явного approve."""

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
        self.allowed_roots = [
            self.settings.package_dir.resolve(),
            self.settings.web_dir.resolve(),
        ]

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

    def propose(self, request: str) -> dict[str, Any]:
        tree = self._list_editable_files()
        raw = self.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Ты модуль hard-evolve Зипки. Верни ТОЛЬКО JSON:\n"
                        '{"files": [{"path": "zipka/relative/or/web/...", '
                        '"content": "полный новый текст файла"}]}\n'
                        "Можно менять только файлы внутри zipka/ и web/. "
                        "Не трогай .env и секреты."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Запрос: {request}\n\nДоступные файлы:\n"
                        + "\n".join(tree[:80])
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
            abs_path = (ROOT_DIR / rel).resolve()
            if not self._is_allowed(abs_path):
                continue
            files.append({"path": rel, "content": content})
        if not files:
            raise RuntimeError(
                "Не удалось сформировать безопасный патч. Уточни, какой файл править."
            )
        patch_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
        pending = {
            "id": patch_id,
            "request": request,
            "files": files,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending_approval",
        }
        self.pending_path.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.memory.log_evolve(
            "hard_propose",
            {"id": patch_id, "files": [f["path"] for f in files], "request": request},
        )
        return pending

    def apply_pending(self) -> dict[str, Any]:
        pending = self.load_pending()
        if not pending:
            raise RuntimeError("Нет ожидающего патча.")
        patch_id = pending["id"]
        backup_dir = self.patches_dir / patch_id / "backup"
        new_dir = self.patches_dir / patch_id / "new"
        backup_dir.mkdir(parents=True, exist_ok=True)
        new_dir.mkdir(parents=True, exist_ok=True)

        applied = []
        for item in pending["files"]:
            rel = item["path"]
            abs_path = (ROOT_DIR / rel).resolve()
            if not self._is_allowed(abs_path):
                raise RuntimeError(f"Путь вне sandbox: {rel}")
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
        if not backup_dir.exists():
            raise RuntimeError(f"Бэкап {patch_id} не найден.")
        restored: list[str] = []
        for backup_file in backup_dir.rglob("*"):
            if not backup_file.is_file():
                continue
            rel = backup_file.relative_to(backup_dir).as_posix()
            target = (ROOT_DIR / rel).resolve()
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
        lines = [
            f"Патч {pending['id']} ждёт approve.",
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
        return any(
            resolved == root or root in resolved.parents for root in self.allowed_roots
        )

    def _list_editable_files(self) -> list[str]:
        files: list[str] = []
        for root in self.allowed_roots:
            if not root.exists():
                continue
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in {".py", ".html", ".js", ".css", ".md", ".yaml", ".yml", ".txt"}:
                    files.append(p.relative_to(ROOT_DIR).as_posix())
        return sorted(files)


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
