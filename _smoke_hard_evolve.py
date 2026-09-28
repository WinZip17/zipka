"""Примитивные smoke-тесты hard-evolve: parse/apply + propose (mock LLM).

Не пишет в исходники (только pending, потом clear). Бэкенд должен быть на :8765.
"""
from __future__ import annotations

import json
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from zipka.evolve.hard import HardEvolve
from zipka.evolve.patch_build import apply_edits, parse_patch_response
from zipka.memory.store import MemoryStore
from zipka.config import get_settings


PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  OK  {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f" FAIL {name}" + (f" — {detail}" if detail else ""))


class ScriptedLLM:
    """Отдаёт заранее подготовленные ответы по очереди."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, messages, temperature=0.1, max_tokens=4096):  # noqa: ANN001
        self.calls.append(messages)
        if not self.replies:
            return '{"files":[]}'
        return self.replies.pop(0)


def test_backend_up() -> None:
    print("\n== backend ==")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/settings/models", timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        check("GET /api/settings/models", True, f"keys={list(data)[:6]}")
    except Exception as exc:
        check("GET /api/settings/models", False, str(exc))


def test_parse_apply_py() -> None:
    print("\n== parse/apply .py (eyes.py) ==")
    path = ROOT / "zipka" / "sensors" / "eyes.py"
    original = path.read_text(encoding="utf-8")
    raw = """<<<FILE zipka/sensors/eyes.py>>>
<<<OLD>>>
    def off(self) -> str:
        with self._lock:
            self.enabled = False
            self._close_camera_locked()
            return "Глаза выключены, камера освобождена."
<<<NEW>>>
    def off(self) -> str:
        with self._lock:
            self.enabled = False
            self._close_camera_locked()
            return "Глаза выключены, камера освобождена."

    def detect_faces(self, frame=None):
        \"\"\"Заглушка детекции лиц.\"\"\"
        return []
<<<END>>>
"""
    data = parse_patch_response(raw)
    check("parse delimiter eyes", bool(data and data.get("files")))
    if not data:
        return
    edits = data["files"][0]["edits"]
    try:
        out = apply_edits(original, edits)
        check("apply detect_faces", "def detect_faces" in out and "def off" in out)
        check("original untouched on disk", path.read_text(encoding="utf-8") == original)
    except Exception as exc:
        check("apply detect_faces", False, str(exc))

    # numbered old (как модель копирует из промпта)
    numbered = (
        "44|    def off(self) -> str:\n"
        "45|        with self._lock:\n"
        "46|            self.enabled = False\n"
        "47|            self._close_camera_locked()\n"
        '48|            return "Глаза выключены, камера освобождена."\n'
    )
    try:
        out2 = apply_edits(original, [{"old": numbered, "new": edits[0]["new"]}])
        check("apply with N| prefixes", "def detect_faces" in out2)
    except Exception as exc:
        check("apply with N| prefixes", False, str(exc))


def test_parse_apply_ui() -> None:
    print("\n== parse/apply UI (Composer.tsx) ==")
    path = ROOT / "web" / "frontend" / "src" / "components" / "Composer.tsx"
    original = path.read_text(encoding="utf-8")
    # минимальная правка: title у Send
    if 'title="Отправить"' in original:
        old = 'title="Отправить"'
        new = 'title="Отправить сообщение"'
    elif "SendIcon" in original:
        old = "<SendIcon fontSize=\"small\" />"
        new = "<SendIcon fontSize=\"small\" titleAccess=\"send-smoketest\" />"
    else:
        check("find Composer anchor", False, "нет якоря")
        return

    raw = f"""<<<FILE web/frontend/src/components/Composer.tsx>>>
<<<OLD>>>
{old}
<<<NEW>>>
{new}
<<<END>>>
"""
    data = parse_patch_response(raw)
    check("parse delimiter Composer", bool(data and data.get("files")))
    try:
        out = apply_edits(original, data["files"][0]["edits"])
        check("apply UI edit", new in out and old not in out)
        check("Composer disk untouched", path.read_text(encoding="utf-8") == original)
    except Exception as exc:
        check("apply UI edit", False, str(exc))


def test_propose_mock_py_and_ui() -> None:
    print("\n== HardEvolve.propose (mock LLM) ==")
    settings = get_settings()
    memory = MemoryStore(settings)
    pending_backup = None
    pending_path = settings.data_dir / "patches" / "pending.json"
    if pending_path.exists():
        pending_backup = pending_path.read_text(encoding="utf-8")

    eyes = (ROOT / "zipka" / "sensors" / "eyes.py").read_text(encoding="utf-8")
    # якорь для py
    py_old = (
        "    def off(self) -> str:\n"
        "        with self._lock:\n"
        "            self.enabled = False\n"
        "            self._close_camera_locked()\n"
        '            return "Глаза выключены, камера освобождена."'
    )
    py_new = (
        py_old
        + "\n\n"
        + "    def detect_faces(self, frame=None):\n"
        + '        """Заглушка детекции лиц."""\n'
        + "        return []"
    )
    py_reply = (
        "<<<FILE zipka/sensors/eyes.py>>>\n"
        "<<<OLD>>>\n"
        f"{py_old}\n"
        "<<<NEW>>>\n"
        f"{py_new}\n"
        "<<<END>>>\n"
    )

    composer = (ROOT / "web" / "frontend" / "src" / "components" / "Composer.tsx").read_text(
        encoding="utf-8"
    )
    if 'title="Отправить"' in composer:
        ui_old, ui_new = 'title="Отправить"', 'title="Отправить сообщение"'
    else:
        ui_old = "<SendIcon fontSize=\"small\" />"
        ui_new = "<SendIcon fontSize=\"small\" titleAccess=\"send-smoketest\" />"
    ui_reply = (
        "<<<FILE web/frontend/src/components/Composer.tsx>>>\n"
        "<<<OLD>>>\n"
        f"{ui_old}\n"
        "<<<NEW>>>\n"
        f"{ui_new}\n"
        "<<<END>>>\n"
    )

    try:
        llm = ScriptedLLM([py_reply])
        hard = HardEvolve(llm, memory, settings)
        hard.clear_pending()
        pending = hard.propose(
            "в zipka/sensors/eyes.py добавь функцию detect_faces",
            self_edit=True,
        )
        paths = [f["path"] for f in pending["files"]]
        check("propose py path", any("eyes.py" in p for p in paths), str(paths))
        check(
            "propose py content has detect_faces",
            any("detect_faces" in f["content"] for f in pending["files"]),
        )
        hard.clear_pending()

        llm2 = ScriptedLLM([ui_reply])
        hard2 = HardEvolve(llm2, memory, settings)
        pending2 = hard2.propose(
            "в web/frontend/src/components/Composer.tsx поменяй title кнопки отправки",
            self_edit=True,
        )
        paths2 = [f["path"] for f in pending2["files"]]
        check("propose UI path", any("Composer.tsx" in p for p in paths2), str(paths2))
        check(
            "propose UI content changed",
            any(ui_new in f["content"] for f in pending2["files"]),
        )
        hard2.clear_pending()

        # битый JSON → retry с delimiter
        broken = (
            '{"files":[{"path":"zipka/sensors/eyes.py","edits":[{"old":"class Eyes:\\n """Камера'
        )
        llm3 = ScriptedLLM([broken, py_reply])
        hard3 = HardEvolve(llm3, memory, settings)
        pending3 = hard3.propose(
            "в zipka/sensors/eyes.py добавь detect_faces",
            self_edit=True,
        )
        check("retry after broken JSON", len(llm3.calls) == 2, f"calls={len(llm3.calls)}")
        check(
            "retry succeeded",
            any("detect_faces" in f["content"] for f in pending3["files"]),
        )
        hard3.clear_pending()
    except Exception as exc:
        check("propose mock suite", False, f"{exc}\n{traceback.format_exc()}")
    finally:
        if pending_backup is not None:
            pending_path.parent.mkdir(parents=True, exist_ok=True)
            pending_path.write_text(pending_backup, encoding="utf-8")
        elif pending_path.exists():
            pending_path.unlink()


def test_broken_json_not_silent() -> None:
    print("\n== broken JSON parse ==")
    broken = (
        '{"files":[{"path":"zipka/sensors/eyes.py","edits":[{"old":"class Eyes:\\n """Камера'
    )
    data = parse_patch_response(broken)
    check("broken JSON -> no fake files", not (data and data.get("files")))


def main() -> int:
    print("Zipka hard-evolve smoke tests")
    test_backend_up()
    test_parse_apply_py()
    test_parse_apply_ui()
    test_broken_json_not_silent()
    test_propose_mock_py_and_ui()
    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
