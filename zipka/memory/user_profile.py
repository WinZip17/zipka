from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from typing import Any

from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.memory.store import MemoryStore

DEFAULT_PROFILE: dict[str, Any] = {
    "identity": {
        "name": "",
        "aliases": [],
        "how_to_address": "",
        "notes": "",
    },
    "character": [],
    "personality_type": "",
    "peculiarities": [],
    "mood": {
        "current": "",
        "previous": "",
        "changed_at": "",
        "history": [],
    },
    "likes": [],
    "dislikes": [],
    "time_habits": [],
    "current_state": {
        "summary": "",
        "energy": "",
        "context": "",
        "concerns": [],
    },
    "relationship": {
        "with_zipka": "",
        "topics": [],
    },
    "facts": [],
    "updated_at": "",
    "evidence_count": 0,
}

_LIST_CAPS = {
    "character": 24,
    "peculiarities": 24,
    "likes": 40,
    "dislikes": 40,
    "time_habits": 24,
    "facts": 60,
    "aliases": 12,
    "topics": 20,
    "concerns": 16,
    "mood_history": 30,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _uniq_extend(dst: list[Any], src: Any, *, cap: int) -> list[Any]:
    if not isinstance(src, list):
        if isinstance(src, str) and src.strip():
            src = [src.strip()]
        else:
            return dst
    out = list(dst)
    seen = {str(x).strip().lower() for x in out if str(x).strip()}
    for item in src:
        s = str(item).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    if len(out) > cap:
        out = out[-cap:]
    return out


class UserProfiler:
    """Профиль собеседника: характер, настроение, вкусы, привычки."""

    def __init__(
        self,
        memory: MemoryStore,
        llm: Any,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.memory = memory
        self.llm = llm
        self.path = self.settings.data_dir / "memory" / "user_profile.json"
        self._lock = threading.Lock()
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self.save(dict(DEFAULT_PROFILE))

    def load(self) -> dict[str, Any]:
        data = self.memory.read_json(self.path, None)
        if not isinstance(data, dict):
            return json.loads(json.dumps(DEFAULT_PROFILE))
        merged = json.loads(json.dumps(DEFAULT_PROFILE))
        return self._deep_merge(merged, data)

    def save(self, data: dict[str, Any]) -> None:
        self.memory.write_json(self.path, data)

    @staticmethod
    def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        out = dict(base)
        for key, value in patch.items():
            if (
                key in out
                and isinstance(out[key], dict)
                and isinstance(value, dict)
            ):
                out[key] = UserProfiler._deep_merge(out[key], value)
            else:
                out[key] = value
        return out

    def apply_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Слить патч в профиль с учётом списков и истории настроения."""
        with self._lock:
            profile = self.load()
            if not patch or not patch.get("apply", True):
                return profile

            ident = patch.get("identity")
            if isinstance(ident, dict):
                cur = profile.setdefault("identity", {})
                for k in ("name", "how_to_address", "notes"):
                    if ident.get(k):
                        cur[k] = str(ident[k]).strip()
                if ident.get("aliases") is not None:
                    cur["aliases"] = _uniq_extend(
                        list(cur.get("aliases") or []),
                        ident.get("aliases"),
                        cap=_LIST_CAPS["aliases"],
                    )

            for list_key in (
                "character",
                "peculiarities",
                "likes",
                "dislikes",
                "time_habits",
                "facts",
            ):
                if list_key in patch and patch[list_key] is not None:
                    profile[list_key] = _uniq_extend(
                        list(profile.get(list_key) or []),
                        patch[list_key],
                        cap=_LIST_CAPS[list_key],
                    )

            if patch.get("personality_type"):
                profile["personality_type"] = str(patch["personality_type"]).strip()

            mood_patch = patch.get("mood")
            if isinstance(mood_patch, dict) or isinstance(mood_patch, str):
                if isinstance(mood_patch, str):
                    mood_patch = {"current": mood_patch}
                new_mood = str(mood_patch.get("current") or "").strip()
                mood = profile.setdefault("mood", {})
                old = str(mood.get("current") or "").strip()
                if new_mood and new_mood.lower() != old.lower():
                    if old:
                        mood["previous"] = old
                        history = list(mood.get("history") or [])
                        history.append(
                            {
                                "ts": _utc_now(),
                                "mood": old,
                                "note": str(mood_patch.get("note") or "").strip(),
                            }
                        )
                        mood["history"] = history[-_LIST_CAPS["mood_history"] :]
                    mood["current"] = new_mood
                    mood["changed_at"] = _utc_now()
                elif mood_patch.get("note") and old:
                    history = list(mood.get("history") or [])
                    history.append(
                        {
                            "ts": _utc_now(),
                            "mood": old,
                            "note": str(mood_patch.get("note")).strip(),
                        }
                    )
                    mood["history"] = history[-_LIST_CAPS["mood_history"] :]

            state_patch = patch.get("current_state")
            if isinstance(state_patch, dict):
                state = profile.setdefault("current_state", {})
                for k in ("summary", "energy", "context"):
                    if state_patch.get(k):
                        state[k] = str(state_patch[k]).strip()
                if state_patch.get("concerns") is not None:
                    state["concerns"] = _uniq_extend(
                        list(state.get("concerns") or []),
                        state_patch.get("concerns"),
                        cap=_LIST_CAPS["concerns"],
                    )

            rel_patch = patch.get("relationship")
            if isinstance(rel_patch, dict):
                rel = profile.setdefault("relationship", {})
                if rel_patch.get("with_zipka"):
                    rel["with_zipka"] = str(rel_patch["with_zipka"]).strip()
                if rel_patch.get("topics") is not None:
                    rel["topics"] = _uniq_extend(
                        list(rel.get("topics") or []),
                        rel_patch.get("topics"),
                        cap=_LIST_CAPS["topics"],
                    )

            profile["updated_at"] = _utc_now()
            profile["evidence_count"] = int(profile.get("evidence_count") or 0) + 1
            self.save(profile)
            reason = str(patch.get("reason") or "обновление профиля").strip()
            self.memory.add_note(
                "user_profile",
                reason,
                meta={"evidence_count": profile["evidence_count"]},
            )
            return profile

    def observe_dialogue(self, user_text: str, assistant_text: str) -> dict[str, Any] | None:
        """Вытащить сигналы о собеседнике из реплики и слить в профиль."""
        if not user_text or len(user_text.strip()) < 2:
            return None
        # служебные короткие команды не анализируем
        low = user_text.strip().lower()
        if low in {"ок", "ok", "да", "нет", "ага", "угу", "/ping"}:
            return None

        current = self.load()
        prompt = (
            "Ты модуль идентификации собеседника Зипки. "
            "По реплике пользователя (и ответу Зипки) извлеки ВСЁ полезное "
            "о личности и текущем состоянии. Верни ТОЛЬКО JSON:\n"
            "{\n"
            '  "apply": true|false,\n'
            '  "reason": "кратко что узнали",\n'
            '  "identity": {"name": "", "aliases": [], "how_to_address": "", "notes": ""},\n'
            '  "character": ["черты характера"],\n'
            '  "personality_type": "свободное описание типа личности",\n'
            '  "peculiarities": ["особенности общения, привычки, стиль"],\n'
            '  "mood": {"current": "настроение сейчас", "note": "почему изменилось"},\n'
            '  "likes": [], "dislikes": [],\n'
            '  "time_habits": ["как обычно проводит время"],\n'
            '  "current_state": {"summary": "", "energy": "", "context": "", "concerns": []},\n'
            '  "relationship": {"with_zipka": "", "topics": []},\n'
            '  "facts": ["стойкие факты о человеке"]\n'
            "}\n"
            "Правила: apply=false если ничего нового; не выдумывай; "
            "дописывай только то, что следует из диалога; списки — короткие фразы.\n"
            f"ТЕКУЩИЙ ПРОФИЛЬ:\n{json.dumps(current, ensure_ascii=False)}\n\n"
            f"USER: {user_text[:4000]}\n"
            f"ZIPKA: {assistant_text[:2000]}"
        )
        try:
            raw = self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Анализируй собеседника. Отвечай только валидным JSON, "
                            "без markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]
            )
        except Exception:
            return None
        data = _extract_json(raw)
        if not data or not data.get("apply"):
            return None
        return self.apply_patch(data)

    def observe_sensor(self, modality: str, content: str) -> dict[str, Any] | None:
        """Дополнить профиль по глазам/ушам (внешность, тон, окружение)."""
        text = (content or "").strip()
        if len(text) < 8:
            return None
        current = self.load()
        prompt = (
            f"Источник: {modality}. Из описания извлеки сигналы о собеседнике "
            "(настроение по лицу/голосу, окружение, привычки). "
            "Только JSON как у модуля профиля; apply=false если не про человека.\n"
            f"ПРОФИЛЬ:\n{json.dumps({'mood': current.get('mood'), 'peculiarities': current.get('peculiarities'), 'current_state': current.get('current_state')}, ensure_ascii=False)}\n\n"
            f"ОПИСАНИЕ:\n{text[:3000]}"
        )
        try:
            raw = self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": "Анализируй сенсор. Только JSON.",
                    },
                    {"role": "user", "content": prompt},
                ]
            )
        except Exception:
            return None
        data = _extract_json(raw)
        if not data or not data.get("apply"):
            return None
        data["reason"] = data.get("reason") or f"сенсор {modality}"
        return self.apply_patch(data)

    def prompt_block(self) -> str:
        """Текст для system prompt."""
        p = self.load()
        lines: list[str] = ["Собеседник (профиль, обновляй в уме, опирайся на факты):"]

        ident = p.get("identity") or {}
        name = ident.get("name") or ""
        address = ident.get("how_to_address") or ""
        if name or address:
            bit = name or "без имени"
            if address:
                bit += f", обращайся: {address}"
            lines.append(f"- Кто: {bit}")
        if ident.get("notes"):
            lines.append(f"- Заметки об имени/роли: {ident['notes']}")
        if ident.get("aliases"):
            lines.append("- Также: " + ", ".join(ident["aliases"]))

        if p.get("personality_type"):
            lines.append(f"- Тип личности: {p['personality_type']}")
        if p.get("character"):
            lines.append("- Характер: " + ", ".join(p["character"]))
        if p.get("peculiarities"):
            lines.append("- Особенности: " + ", ".join(p["peculiarities"]))

        mood = p.get("mood") or {}
        if mood.get("current"):
            mline = f"- Настроение сейчас: {mood['current']}"
            if mood.get("previous"):
                mline += f" (было: {mood['previous']})"
            lines.append(mline)
        history = mood.get("history") or []
        if history:
            recent = history[-3:]
            bits = [
                f"{h.get('mood')}" + (f" — {h['note']}" if h.get("note") else "")
                for h in recent
            ]
            lines.append("- Сдвиги настроения: " + "; ".join(bits))

        if p.get("likes"):
            lines.append("- Любит: " + ", ".join(p["likes"]))
        if p.get("dislikes"):
            lines.append("- Не любит: " + ", ".join(p["dislikes"]))
        if p.get("time_habits"):
            lines.append("- Как проводит время: " + ", ".join(p["time_habits"]))

        state = p.get("current_state") or {}
        if state.get("summary") or state.get("energy") or state.get("context"):
            parts = [
                x
                for x in (
                    state.get("summary"),
                    f"энергия: {state['energy']}" if state.get("energy") else "",
                    state.get("context"),
                )
                if x
            ]
            lines.append("- Текущее состояние: " + "; ".join(parts))
        if state.get("concerns"):
            lines.append("- Заботы: " + ", ".join(state["concerns"]))

        rel = p.get("relationship") or {}
        if rel.get("with_zipka"):
            lines.append(f"- Отношение ко мне: {rel['with_zipka']}")
        if rel.get("topics"):
            lines.append("- Частые темы: " + ", ".join(rel["topics"]))
        if p.get("facts"):
            lines.append("- Факты: " + "; ".join(p["facts"][-12:]))

        if len(lines) == 1:
            lines.append(
                "- Пока мало данных. Мягко узнавай имя, характер, вкусы, "
                "настроение и как проводит время — без допроса."
            )
        else:
            lines.append(
                "- Уточняй пробелы естественно в разговоре; не повторяй "
                "очевидное и не выдумывай за человека."
            )
        return "\n".join(lines)

    def summary_for_ui(self) -> dict[str, Any]:
        p = self.load()
        mood = p.get("mood") or {}
        ident = p.get("identity") or {}
        state = p.get("current_state") or {}
        return {
            "name": ident.get("name") or "",
            "how_to_address": ident.get("how_to_address") or "",
            "personality_type": p.get("personality_type") or "",
            "character": list(p.get("character") or [])[:12],
            "peculiarities": list(p.get("peculiarities") or [])[:12],
            "mood": mood.get("current") or "",
            "mood_previous": mood.get("previous") or "",
            "likes": list(p.get("likes") or [])[:12],
            "dislikes": list(p.get("dislikes") or [])[:12],
            "time_habits": list(p.get("time_habits") or [])[:12],
            "current_state": state.get("summary") or "",
            "energy": state.get("energy") or "",
            "facts_count": len(p.get("facts") or []),
            "evidence_count": int(p.get("evidence_count") or 0),
            "updated_at": p.get("updated_at") or "",
        }
