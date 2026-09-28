from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zipka.config import ROOT_DIR, Settings, ensure_data_dirs, get_settings
from zipka.evolve.patch_build import materialize_patch, number_lines
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
2. Запрещено: style=\"...\", <style>, class=\"...\", CSS-селекторы в TSX.
3. В sx: camelCase; одно двоеточие — bgcolor: \"#007BFF\" (никогда bgcolor:=).
4. Не подменяй MUI-компоненты на голые div/button без нужды.
5. Сохраняй импорты, onKeyDown, disabled и подписи — меняй только запрошенное.
6. Формат: edits old→new, НЕ переписывай файл целиком.
""".strip()

PATCH_SYSTEM = """
Ты модуль hard-evolve Зипки. Верни ТОЛЬКО JSON без markdown и без пояснений.

Формат (точечные правки существующего файла):
{"files":[{"path":"relative/path.ext","edits":[{"old":"точный уникальный фрагмент ИЗ ФАЙЛА","new":"замена"}]}]}

Для НОВОГО файла:
{"files":[{"path":"relative/path.ext","content":"полный текст"}]}

Правила:
- old копируй 1:1 из текущего файла (включая отступы), встречается ровно 1 раз.
- Обычно 1–2 файла и 1–5 edits. Не дублируй весь файл в content, если файл уже есть.
- Большую фичу делай МИНИМАЛЬНЫМ шагом: заготовка/хук/вызов, не весь пайплайн целиком.
- Не трогай .env, secrets, node_modules, dist.
- Синтаксис должен остаться валидным (скобки, кавычки, JSX).
- Если не можешь сделать правку — верни {"files":[]} (но лучше маленький рабочий шаг).
""".strip()


class HardEvolve:
    """Правки кода только после явного approve (Zipka и/или изученный проект)."""

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
            "добавь в свой код",
            "hard evolve",
            "перепиши файл",
            "предложи правки",
            "внеси правки",
            "внеси эти правки",
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
            "реализуй в коде",
            "реализуй это",
            "внедри в код",
            "примени правк",
            "подготовь патч",
            "сделай патч",
            "добавь функцию",
            "добавь метод",
            "вызови её после",
            "вызови ее после",
            "textarea",
            "текстареа",
            "поле ввода",
            "цвет кнопк",
            "кнопку отправ",
            "кнопка отправ",
            "поменяй цвет",
            "измени цвет",
            "покрась",
            "сделай синим",
            "сделай красн",
            "сделай зелён",
            "сделай зелен",
        ]
        if any(k in lowered for k in keys):
            return True

        # путь к файлу репо + глагол правки → hard-evolve (не болтовня с примером)
        if self._mentions_repo_code_path(lowered) and self._has_change_verb(lowered):
            return True

        change_verbs = self._change_verbs()
        ui_targets = (
            "кнопк",
            "цвет",
            "интерфейс",
            "в чате",
            "ui",
            "frontend",
            "composer",
            "отправк",
            "textarea",
            "поле ввода",
            "стиль",
            "фон",
            "тема",
            "mui",
            "свой код",
            "своего кода",
            "зипк",
            "zipka",
            "web/",
            "layout",
            "иконк",
            "шрифт",
            "eyes.py",
            "vision.py",
            "agent.py",
            "detect_faces",
            "самообуч",
        )
        return any(v in lowered for v in change_verbs) and any(
            t in lowered for t in ui_targets
        )

    @staticmethod
    def _change_verbs() -> tuple[str, ...]:
        return (
            "поменяй",
            "измени",
            "сделай",
            "покрась",
            "замени",
            "поставь",
            "убери",
            "добавь",
            "добавлю",
            "сдвинь",
            "увеличь",
            "уменьши",
            "переименуй",
            "реализуй",
            "внедри",
            "подключи",
            "пропиши",
            "допиши",
            "вставь",
            "вызови",
        )

    def _has_change_verb(self, lowered: str) -> bool:
        return any(v in lowered for v in self._change_verbs())

    @staticmethod
    def _mentions_repo_code_path(lowered: str) -> bool:
        if re.search(
            r"(?:zipka|web)[/\\][\w./\\-]+\.(?:py|ts|tsx|js|jsx|css|json|yaml|yml|toml|md)",
            lowered,
        ):
            return True
        if re.search(r"\b[\w-]+\.(?:py|tsx|ts|jsx)\b", lowered) and any(
            k in lowered
            for k in (
                "zipka",
                "sensors",
                "frontend",
                "components",
                "eyes",
                "vision",
                "agent",
            )
        ):
            return True
        return False

    def wants_self_edit(self, text: str) -> bool:
        """Явный запрос правок самой Зипки."""
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

    def wants_external_edit(self, text: str) -> bool:
        """Явно указан внешний/изученный проект (не Зипка)."""
        lowered = text.lower()
        keys = [
            "в этом проекте",
            "в изученном проекте",
            "в изученном",
            "во внешнем проекте",
            "во внешнем",
            "в чужом проекте",
            "по изученному проекту",
            "по этому проекту",
            "в last project",
            "внешн",
        ]
        if any(k in lowered for k in keys):
            return True
        path = self._extract_dir_path(text)
        if path is None:
            return False
        try:
            path.resolve().relative_to(ROOT_DIR.resolve())
            return False  # путь внутри Zipka → не внешний
        except ValueError:
            return True

    def resolve_patch_target(self, text: str) -> tuple[bool, Path | None]:
        """Куда править: (self_edit, project_root).

        Без явного внешнего проекта всегда Зипка сама.
        """
        if self.wants_external_edit(text):
            path = self._extract_dir_path(text)
            if path and path.is_dir():
                try:
                    path.resolve().relative_to(ROOT_DIR.resolve())
                except ValueError:
                    return False, path
            last = self.last_project()
            if last:
                try:
                    last.resolve().relative_to(ROOT_DIR.resolve())
                except ValueError:
                    return False, last
            # Просили внешний, но цели нет — не уходим в самоправку молча
            raise RuntimeError(
                "Нужен внешний проект: укажи путь к папке или сначала "
                "«изучи папку …», потом «предложи правки в этом проекте»."
            )
        return True, None

    def _extract_dir_path(self, text: str) -> Path | None:
        """Вытащить путь к папке из текста, если есть."""
        patterns = [
            r'(?:[A-Za-z]:[\\/][^\s"\'«»]+)',
            r'(?:\\\\[^\s"\'«»]+)',
            r'(?:/(?:home|Users|var|opt|tmp)/[^\s"\'«»]+)',
        ]
        for pat in patterns:
            for match in re.finditer(pat, text):
                raw = match.group(0).rstrip(".,;:)")
                # trim trailing Cyrillic glued words if any — stop at space already
                try:
                    p = Path(raw).expanduser()
                    if p.exists() and p.is_dir():
                        return p.resolve()
                except OSError:
                    continue
        return None

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
        focus_files = self._pick_focus_files(request, tree, limit=3)
        originals: dict[str, str] = {}
        focus_blobs: list[str] = []
        for rel in focus_files:
            abs_path = (base / rel).resolve()
            try:
                if abs_path.is_file() and abs_path.stat().st_size < 120_000:
                    body = abs_path.read_text(encoding="utf-8", errors="ignore")
                    originals[rel.replace("\\", "/")] = body
                    numbered = number_lines(body, max_chars=14_000)
                    focus_blobs.append(
                        "### " + rel + "\n```\n" + numbered + "\n```"
                    )
            except OSError:
                continue

        scope_hint = (
            f"Проект: {root}. Пути указывай относительно этой папки."
            if root
            else (
                "Самоправка Зипки. Пути от корня репо, например "
                "web/frontend/src/components/Composer.tsx. Только zipka/ и web/."
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
                "цвет",
            )
        )
        system = PATCH_SYSTEM + "\n" + scope_hint
        if touches_frontend or self_edit:
            system += "\n" + FRONTEND_EDIT_RULES

        user_content = f"Запрос: {request}\n\n"
        if context:
            user_content += f"Контекст изучения:\n{context[:4000]}\n\n"
        if focus_blobs:
            user_content += (
                "Текущие файлы (прави через edits old→new):\n"
                + "\n\n".join(focus_blobs)
                + "\n\n"
            )
        else:
            user_content += (
                "Фокус-файлы не подставились — выбери путь из списка ниже "
                "и сделай минимальный edit/новый файл.\n\n"
            )
        user_content += (
            "Сделай ОДИН минимальный рабочий шаг под запрос "
            "(например хук вызова / заготовка модуля), не весь продукт сразу.\n"
            "Ответ — только JSON.\n\n"
            "Другие доступные пути (не читай все — только если нужно):\n"
            + "\n".join(tree[:40])
        )

        last_error = ""
        files: list[dict[str, str]] = []
        raw_last = ""
        for _attempt in range(2):
            prompt = user_content
            if last_error:
                prompt = (
                    user_content
                    + "\n\nПРЕДЫДУЩИЙ ПАТЧ ОТКЛОНЁН:\n"
                    + last_error
                    + "\nВерни новый JSON. old должен точно совпадать с файлом. "
                    "Без markdown, без текста вокруг JSON."
                )
            messages: list[dict[str, str]] = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
            try:
                raw = self.llm.chat(
                    messages,
                    temperature=0.15,
                    max_tokens=3072,
                )
            except TypeError:
                raw = self.llm.chat(messages)
            raw_last = raw or ""
            try:
                files = materialize_patch(
                    {},
                    raw=raw,
                    extract_json=_extract_json,
                    base=base,
                    originals=originals,
                    blocked_names=BLOCKED_NAMES,
                    is_allowed=self._is_allowed,
                    style_check=self._frontend_style_problems,
                )
                last_error = ""
                break
            except RuntimeError as exc:
                last_error = str(exc)
                files = []
        if not files:
            tip = last_error or "Не удалось сформировать безопасный патч."
            preview = re.sub(r"\s+", " ", raw_last).strip()[:280]
            if preview and "files[].edits" in tip:
                tip += (
                    f"\nМодель ответила не JSON-патчем (начало: «{preview}»). "
                    "Уточни файл и маленький шаг: например "
                    "«в zipka/sensors/eyes.py добавь функцию detect_faces»."
                )
            raise RuntimeError(tip)

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
            "mode": "edits",
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
            ("кнопк", 45),
            ("отправ", 40),
            ("цвет", 35),
            ("input", 20),
            ("чат", 25),
            ("сообщен", 25),
            ("интерфейс", 15),
            ("sidepanel", 30),
            ("app.tsx", 20),
            ("agent.py", 25),
            ("eyes", 55),
            ("камер", 50),
            ("глаз", 50),
            ("vision", 55),
            ("moondream", 40),
            ("лиц", 45),
            ("face", 45),
            ("кадр", 40),
            ("сним", 35),
            ("распозна", 40),
            ("самообуч", 30),
            ("профил", 25),
            ("user_profile", 35),
            ("style", 10),
            ("frontend", 10),
            ("theme", 25),
        ]
        path_boosts = [
            (("камер", "глаз", "лиц", "face", "кадр", "сним", "vision", "распозна"), (
                ("sensors/eyes.py", 80),
                ("llm/vision.py", 75),
                ("agent.py", 55),
                ("memory/user_profile.py", 35),
                ("mind/proactive.py", 25),
            )),
            (("самообуч", "soft-evolve", "soft evolve", "характер", "навык"), (
                ("evolve/soft.py", 60),
                ("agent.py", 50),
                ("character/persona.py", 40),
                ("mind/goals.py", 35),
            )),
            (("чат", "сообщен", "кнопк", "цвет", "ui", "интерфейс", "composer"), (
                ("web/frontend/src/components/Composer.tsx", 70),
                ("web/frontend/src/components/MessageList.tsx", 45),
                ("web/frontend/src/App.tsx", 40),
                ("web/frontend/src/theme.ts", 30),
            )),
        ]
        for rel in tree:
            score = 0
            name = rel.lower().replace("\\", "/")
            for hint, w in hints:
                if hint in lowered and hint in name:
                    score += w
            for keys, boosts in path_boosts:
                if any(k in lowered for k in keys):
                    for needle, w in boosts:
                        if needle in name:
                            score += w
            # Composer не получает бонус «просто за имя», иначе UI крадёт любой запрос
            if "composer" in name and any(
                k in lowered
                for k in (
                    "кнопк",
                    "отправ",
                    "цвет",
                    "чат",
                    "сообщен",
                    "ui",
                    "интерфейс",
                    "composer",
                    "textarea",
                    "поле ввода",
                )
            ):
                score += 40
            if score:
                scored.append((score, rel))
        scored.sort(key=lambda x: (-x[0], x[1]))
        picked = [rel for _, rel in scored[:limit]]

        # добор по домену, если эвристика пустая/слабая
        domain_defaults: list[str] = []
        if any(
            k in lowered
            for k in ("камер", "глаз", "лиц", "face", "кадр", "сним", "vision", "распозна")
        ):
            domain_defaults = [
                "zipka/sensors/eyes.py",
                "zipka/llm/vision.py",
                "zipka/agent.py",
            ]
        elif any(
            k in lowered
            for k in (
                "textarea",
                "текстареа",
                "поле ввода",
                "инпут",
                "input",
                "сообщен",
                "интерфейс",
                "ui",
                "кнопк",
                "цвет",
                "отправ",
                "чат",
            )
        ):
            domain_defaults = [
                "web/frontend/src/components/Composer.tsx",
                "web/frontend/src/theme.ts",
            ]
        elif any(k in lowered for k in ("свой код", "самообуч", "зипк", "добавь в код")):
            domain_defaults = ["zipka/agent.py"]

        for cand in domain_defaults:
            if cand in tree and cand not in picked:
                picked.append(cand)
            # tree может хранить с другим разделителем
            alt = cand.replace("/", "\\")
            if alt in tree and cand not in picked and alt not in picked:
                picked.append(alt)

        # нормализуем к путям из tree
        normalized: list[str] = []
        tree_map = {t.replace("\\", "/"): t for t in tree}
        for rel in picked:
            key = rel.replace("\\", "/")
            if key in tree_map and tree_map[key] not in normalized:
                normalized.append(tree_map[key])
        if not normalized and tree:
            # последний шанс: agent.py / main module
            for fallback in ("zipka/agent.py", "zipka/main.py"):
                if fallback in tree_map:
                    normalized.append(tree_map[fallback])
                    break
            if not normalized:
                normalized = tree[:1]
        return normalized[:limit]

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
        # типичная опечатка LLM в sx/объектах
        if re.search(r"\b[A-Za-z_][\w]*\s*:=", content):
            problems.append("найден := (нужно ':' в объектах или '=' в присваивании)")
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
