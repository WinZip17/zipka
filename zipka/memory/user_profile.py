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
        "gender": "",
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
        "bond": "",
    },
    # Круг «своих»: основной собеседник + люди, которых она приняла
    "inner_circle": [],
    "facts": [],
    "writing_style": {
        "samples": 0,
        "ready": False,
        "avg_len": 0.0,
        "emoji": [],
        "emoji_counts": {},
        "punct": {
            "excl": 0.0,
            "quest": 0.0,
            "ellipsis": 0.0,
            "comma": 0.0,
            "dot": 0.0,
        },
        "traits": [],
        "phrases": [],
        "notes": "",
    },
    "speaker_guard": {
        "last": None,
        "alerts": [],
        "streak_other": 0,
    },
    "updated_at": "",
    "evidence_count": 0,
}

# Сколько нужно наблюдений, чтобы «знать» стиль основного собеседника
_MIN_EVIDENCE_FOR_GUARD = 10
_MIN_STYLE_SAMPLES = 8
# Порог срабатывания: только высокая уверенность
_HIGH_CONFIDENCE = 0.88
# Локальная эвристика — порог, чтобы звать LLM на проверку
_LOCAL_SUSPICION_GATE = 0.52
# Стадии привязанности по числу наблюдений
_BOND_EARLY_MAX = 3
_BOND_GROWING_MAX = 12

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F600-\U0001F64F"
    "\U0001F900-\U0001F9FF"
    "]+",
    flags=re.UNICODE,
)
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]{3,}")

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
    "inner_circle": 12,
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
        self._turn_alert: dict[str, Any] | None = None
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
                for k in ("name", "how_to_address", "gender", "notes"):
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
                if rel_patch.get("bond"):
                    rel["bond"] = str(rel_patch["bond"]).strip()
                if rel_patch.get("topics") is not None:
                    rel["topics"] = _uniq_extend(
                        list(rel.get("topics") or []),
                        rel_patch.get("topics"),
                        cap=_LIST_CAPS["topics"],
                    )

            circle_patch = patch.get("inner_circle")
            if circle_patch is not None:
                profile["inner_circle"] = self._merge_inner_circle(
                    list(profile.get("inner_circle") or []),
                    circle_patch,
                )

            # Основной собеседник всегда в круге «своих», если имя известно
            self._ensure_primary_in_circle(profile)

            profile["updated_at"] = _utc_now()
            profile["evidence_count"] = int(profile.get("evidence_count") or 0) + 1
            # пересчитать стадию привязанности
            rel = profile.setdefault("relationship", {})
            rel["bond"] = self.bond_stage(profile)
            self.save(profile)
            reason = str(patch.get("reason") or "обновление профиля").strip()
            self.memory.add_note(
                "user_profile",
                reason,
                meta={"evidence_count": profile["evidence_count"]},
            )
            return profile

    @staticmethod
    def _merge_inner_circle(
        current: list[Any], patch: Any
    ) -> list[dict[str, str]]:
        """Слить список «своих»: [{name, role, notes}, ...] или строки имён."""
        out: list[dict[str, str]] = []
        seen: set[str] = set()

        def _add(item: Any) -> None:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if not name:
                    return
                key = name.lower()
                if key in seen:
                    # обновить роль/заметки у уже известного
                    for row in out:
                        if row["name"].lower() == key:
                            if item.get("role"):
                                row["role"] = str(item["role"]).strip()
                            if item.get("notes"):
                                row["notes"] = str(item["notes"]).strip()
                            return
                    return
                seen.add(key)
                out.append(
                    {
                        "name": name,
                        "role": str(item.get("role") or "trusted").strip() or "trusted",
                        "notes": str(item.get("notes") or "").strip(),
                    }
                )
            elif isinstance(item, str) and item.strip():
                name = item.strip()
                key = name.lower()
                if key in seen:
                    return
                seen.add(key)
                out.append({"name": name, "role": "trusted", "notes": ""})

        for item in current:
            _add(item)
        if isinstance(patch, list):
            for item in patch:
                _add(item)
        elif patch:
            _add(patch)
        cap = _LIST_CAPS["inner_circle"]
        if len(out) > cap:
            # primary всегда сохраняем
            primary = [x for x in out if x.get("role") == "primary"]
            rest = [x for x in out if x.get("role") != "primary"]
            out = primary[:1] + rest[-(cap - len(primary[:1])) :]
        return out

    @staticmethod
    def _ensure_primary_in_circle(profile: dict[str, Any]) -> None:
        name = str((profile.get("identity") or {}).get("name") or "").strip()
        if not name:
            return
        circle = list(profile.get("inner_circle") or [])
        key = name.lower()
        found = False
        for row in circle:
            if not isinstance(row, dict):
                continue
            if str(row.get("name") or "").strip().lower() == key:
                row["role"] = "primary"
                found = True
                break
        if not found:
            circle.insert(
                0,
                {
                    "name": name,
                    "role": "primary",
                    "notes": "основной собеседник",
                },
            )
        # один primary
        primary_seen = False
        for row in circle:
            if not isinstance(row, dict):
                continue
            if str(row.get("role") or "") == "primary":
                if primary_seen and str(row.get("name") or "").strip().lower() != key:
                    row["role"] = "trusted"
                else:
                    primary_seen = True
        profile["inner_circle"] = circle

    def bond_stage(self, profile: dict[str, Any] | None = None) -> str:
        """early | growing | attached — стадия привязанности к основному."""
        p = profile or self.load()
        evidence = int(p.get("evidence_count") or 0)
        name = str((p.get("identity") or {}).get("name") or "").strip()
        if not name or evidence < _BOND_EARLY_MAX:
            return "early"
        if evidence < _BOND_GROWING_MAX:
            return "growing"
        return "attached"

    def style_ready(self, profile: dict[str, Any] | None = None) -> bool:
        p = profile or self.load()
        style = p.get("writing_style") or {}
        if style.get("ready"):
            return True
        samples = int(style.get("samples") or 0)
        evidence = int(p.get("evidence_count") or 0)
        has_anchor = bool(
            ((p.get("identity") or {}).get("name"))
            or (p.get("character") or [])
            or (p.get("likes") or [])
            or (p.get("peculiarities") or [])
        )
        return (
            samples >= _MIN_STYLE_SAMPLES
            and evidence >= _MIN_EVIDENCE_FOR_GUARD
            and has_anchor
        )

    @staticmethod
    def _extract_style_features(text: str) -> dict[str, Any]:
        raw = text or ""
        n = max(len(raw), 1)
        emojis = _EMOJI_RE.findall(raw)
        words = [w.lower() for w in _WORD_RE.findall(raw)]
        phrases = [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]
        letters = [c for c in raw if c.isalpha()]
        upper = sum(1 for c in letters if c.isupper()) if letters else 0
        return {
            "len": len(raw.strip()),
            "emoji": emojis,
            "excl": raw.count("!") / n,
            "quest": raw.count("?") / n,
            "ellipsis": (raw.count("...") + raw.count("…")) / n,
            "comma": raw.count(",") / n,
            "dot": raw.count(".") / n,
            "multi_excl": 1.0 if "!!" in raw or "??" in raw else 0.0,
            "upper_ratio": (upper / len(letters)) if letters else 0.0,
            "phrases": phrases[:12],
            "words": words,
        }

    def ingest_style_sample(self, user_text: str) -> None:
        """Накопить стилевой отпечаток основного собеседника."""
        text = (user_text or "").strip()
        if len(text) < 4:
            return
        low = text.lower()
        if low in {"ок", "ok", "да", "нет", "ага", "угу", "/ping"}:
            return
        feats = self._extract_style_features(text)
        with self._lock:
            profile = self.load()
            style = profile.setdefault("writing_style", {})
            n = int(style.get("samples") or 0)
            new_n = n + 1
            prev_len = float(style.get("avg_len") or 0.0)
            style["avg_len"] = prev_len + (feats["len"] - prev_len) / new_n
            punct = style.setdefault(
                "punct",
                {"excl": 0.0, "quest": 0.0, "ellipsis": 0.0, "comma": 0.0, "dot": 0.0},
            )
            for key in ("excl", "quest", "ellipsis", "comma", "dot"):
                old = float(punct.get(key) or 0.0)
                punct[key] = old + (float(feats[key]) - old) / new_n

            counts = dict(style.get("emoji_counts") or {})
            for e in feats["emoji"]:
                counts[e] = int(counts.get(e) or 0) + 1
            top = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:24]
            style["emoji_counts"] = dict(top)
            style["emoji"] = [e for e, _ in top]
            style["phrases"] = _uniq_extend(
                list(style.get("phrases") or []),
                feats["phrases"],
                cap=40,
            )
            style["samples"] = new_n
            style["ready"] = self.style_ready({**profile, "writing_style": style})
            profile["writing_style"] = style
            self.save(profile)

    def _local_speaker_score(
        self, text: str, profile: dict[str, Any]
    ) -> tuple[float, list[str]]:
        style = profile.get("writing_style") or {}
        feats = self._extract_style_features(text)
        signals: list[str] = []
        score = 0.0

        known_emoji = set(style.get("emoji") or [])
        msg_emoji = set(feats["emoji"])
        if msg_emoji:
            if known_emoji:
                novel = msg_emoji - known_emoji
                if novel and len(novel) >= max(1, len(msg_emoji) // 2):
                    score += 0.28
                    signals.append(
                        "нестандартные смайлики: " + ", ".join(sorted(novel)[:6])
                    )
            elif len(msg_emoji) >= 2:
                score += 0.22
                signals.append("пачка эмодзи при обычно «сухом» стиле")

        avg_len = float(style.get("avg_len") or 0.0)
        if avg_len > 20 and feats["len"] > 0:
            ratio = feats["len"] / avg_len
            if ratio >= 2.8 or ratio <= 0.25:
                score += 0.18
                signals.append(
                    f"длина резко отличается (обычно ~{int(avg_len)}, сейчас {feats['len']})"
                )

        punct = style.get("punct") or {}
        for key, label, weight in (
            ("excl", "восклицания", 0.14),
            ("quest", "вопросы", 0.1),
            ("ellipsis", "многоточия", 0.12),
        ):
            base = float(punct.get(key) or 0.0)
            cur = float(feats[key])
            if base < 0.002 and cur > 0.02:
                score += weight
                signals.append(f"нетипичная пунктуация: много {label}")
            elif base > 0.015 and cur < 0.001 and feats["len"] > 40:
                score += weight * 0.7
                signals.append(f"пропала привычная пунктуация ({label})")

        if feats["multi_excl"] and float(punct.get("excl") or 0.0) < 0.005:
            score += 0.12
            signals.append("серии !! / ?? — не в стиле основного")

        known_phrases = {p.lower() for p in (style.get("phrases") or [])}
        msg_phrases = {p.lower() for p in feats["phrases"]}
        if known_phrases and len(feats["words"]) >= 8:
            overlap = len(known_phrases & msg_phrases) / max(len(msg_phrases), 1)
            if overlap < 0.05 and len(msg_phrases) >= 4:
                score += 0.12
                signals.append("другие словосочетания, мало пересечений с привычными")

        traits = " ".join(style.get("traits") or []).lower()
        if ("без эмодзи" in traits or "редко эмодзи" in traits) and msg_emoji:
            score += 0.1
            signals.append("эмодзи при привычке писать без них")

        return min(1.0, score), signals

    def check_speaker(self, user_text: str) -> dict[str, Any]:
        """Проверить смену собеседника. Alert только при высокой уверенности."""
        text = (user_text or "").strip()
        result: dict[str, Any] = {
            "ready": False,
            "same_person": True,
            "confidence": 0.0,
            "signals": [],
            "alert": False,
            "reason": "",
        }
        self._turn_alert = None
        if len(text) < 8:
            return result

        profile = self.load()
        ready = self.style_ready(profile)
        result["ready"] = ready
        if not ready:
            self.ingest_style_sample(text)
            return result

        local_score, local_signals = self._local_speaker_score(text, profile)
        if local_score < _LOCAL_SUSPICION_GATE:
            self.ingest_style_sample(text)
            result.update(
                {
                    "same_person": True,
                    "confidence": round(max(0.55, 1.0 - local_score), 3),
                    "signals": [],
                    "reason": "стиль совпадает",
                }
            )
            self._store_speaker_check(result, other=False)
            return result

        style = profile.get("writing_style") or {}
        ident = profile.get("identity") or {}
        llm_result = self._llm_speaker_check(
            text,
            style=style,
            name=str(ident.get("name") or ""),
            local_signals=local_signals,
            local_score=local_score,
        )
        same = bool(llm_result.get("same_person", True))
        conf = float(llm_result.get("confidence") or 0.0)
        signals = list(llm_result.get("signals") or local_signals)
        reason = str(llm_result.get("reason") or "").strip()

        if llm_result.get("_fallback"):
            same = local_score < 0.9
            conf = local_score if not same else (1.0 - local_score)
            signals = local_signals
            reason = "локальная эвристика (LLM недоступен)"

        alert = (not same) and conf >= _HIGH_CONFIDENCE and len(signals) >= 2
        if not same and conf >= 0.82:
            streak = self._bump_other_streak()
            if streak >= 2 and len(signals) >= 2:
                alert = True
        else:
            self._reset_other_streak()

        result.update(
            {
                "same_person": same,
                "confidence": round(conf, 3),
                "signals": signals[:8],
                "alert": alert,
                "reason": reason,
            }
        )
        if alert:
            self._turn_alert = dict(result)
            self._record_alert(result)
        elif same and conf >= 0.6:
            self.ingest_style_sample(text)

        self._store_speaker_check(result, other=not same)
        return result

    def _bump_other_streak(self) -> int:
        with self._lock:
            profile = self.load()
            guard = profile.setdefault("speaker_guard", {})
            streak = int(guard.get("streak_other") or 0) + 1
            guard["streak_other"] = streak
            profile["speaker_guard"] = guard
            self.save(profile)
            return streak

    def _reset_other_streak(self) -> None:
        with self._lock:
            profile = self.load()
            guard = profile.setdefault("speaker_guard", {})
            if guard.get("streak_other"):
                guard["streak_other"] = 0
                profile["speaker_guard"] = guard
                self.save(profile)

    def _store_speaker_check(self, result: dict[str, Any], *, other: bool) -> None:
        with self._lock:
            profile = self.load()
            guard = profile.setdefault("speaker_guard", {})
            guard["last"] = {
                "ts": _utc_now(),
                "same_person": result.get("same_person"),
                "confidence": result.get("confidence"),
                "alert": result.get("alert"),
                "signals": result.get("signals") or [],
                "reason": result.get("reason") or "",
            }
            if not other:
                guard["streak_other"] = 0
            profile["speaker_guard"] = guard
            self.save(profile)

    def _record_alert(self, result: dict[str, Any]) -> None:
        with self._lock:
            profile = self.load()
            guard = profile.setdefault("speaker_guard", {})
            alerts = list(guard.get("alerts") or [])
            alerts.append(
                {
                    "ts": _utc_now(),
                    "confidence": result.get("confidence"),
                    "signals": result.get("signals") or [],
                    "reason": result.get("reason") or "",
                }
            )
            guard["alerts"] = alerts[-20:]
            profile["speaker_guard"] = guard
            self.save(profile)
            self.memory.add_note(
                "speaker_alert",
                result.get("reason") or "подозрение: другой собеседник",
                meta={
                    "confidence": result.get("confidence"),
                    "signals": result.get("signals") or [],
                },
            )

    def _llm_speaker_check(
        self,
        text: str,
        *,
        style: dict[str, Any],
        name: str,
        local_signals: list[str],
        local_score: float,
    ) -> dict[str, Any]:
        fingerprint = {
            "name": name,
            "avg_len": style.get("avg_len"),
            "typical_emoji": style.get("emoji"),
            "punct_habits": style.get("punct"),
            "typical_phrases": (style.get("phrases") or [])[:20],
            "style_traits": style.get("traits") or [],
            "notes": style.get("notes") or "",
        }
        prompt = (
            "Ты — модуль проверки личности собеседника Зипки.\n"
            "Сравни НОВУЮ реплику с известным стилем ОСНОВНОГО пользователя.\n"
            "Смотри косвенные признаки: пунктуация, типичные словосочетания, "
            "набор смайликов/эмодзи, длина, регистр, «чужой» тон.\n"
            "same_person=false ТОЛЬКО при ЯВНОМ стилевом разрыве. "
            f"confidence для «другой человек» ставь >= {_HIGH_CONFIDENCE} "
            "только если уверенность высокая; при сомнении — same_person=true "
            "и низкий/средний confidence.\n"
            "Верни ТОЛЬКО JSON:\n"
            '{"same_person": true|false, "confidence": 0.0-1.0, '
            '"signals": ["..."], "reason": "...", '
            '"style_traits_add": ["черты стиля основного, если это он"]}\n\n'
            f"ОТЧЁТ FINGERPRINT:\n{json.dumps(fingerprint, ensure_ascii=False)}\n"
            f"ЛОКАЛЬНЫЕ СИГНАЛЫ (score={local_score:.2f}): {local_signals}\n"
            f"НОВАЯ РЕПЛИКА:\n{text[:4000]}"
        )
        try:
            raw = self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Строгий детектив стиля. Ложные тревоги недопустимы. "
                            "Только JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ]
            )
        except Exception:
            return {"_fallback": True, "same_person": True, "confidence": 0.0}

        data = _extract_json(raw) or {}
        if not data:
            return {"_fallback": True, "same_person": True, "confidence": 0.0}

        traits_add = data.get("style_traits_add")
        if data.get("same_person") and traits_add:
            with self._lock:
                profile = self.load()
                style_obj = profile.setdefault("writing_style", {})
                style_obj["traits"] = _uniq_extend(
                    list(style_obj.get("traits") or []),
                    traits_add,
                    cap=20,
                )
                profile["writing_style"] = style_obj
                self.save(profile)
        return data

    def observe_dialogue(self, user_text: str, assistant_text: str) -> dict[str, Any] | None:
        """Вытащить сигналы о собеседнике из реплики и слить в профиль."""
        if not user_text or len(user_text.strip()) < 2:
            return None
        # не учимся на репликах «другого» при алерте этого хода
        if self._turn_alert and self._turn_alert.get("alert"):
            return None
        # короткие «спасибо/класс» — не гоняем полный JSON-профиль
        low = user_text.strip().lower()
        if low in {"ок", "ok", "да", "нет", "ага", "угу", "/ping"}:
            return None
        if len(user_text.strip()) < 120 and any(
            t in low
            for t in (
                "класс",
                "супер",
                "спасибо",
                "молодец",
                "круто",
                "отлично",
                "ты это сделала",
                "начало положено",
            )
        ):
            return None

        current = self.load()
        prompt = (
            "Ты модуль идентификации собеседника Зипки. "
            "По реплике пользователя (и ответу Зипки) извлеки ВСЁ полезное "
            "о личности и текущем состоянии. Верни ТОЛЬКО JSON:\n"
            "{\n"
            '  "apply": true|false,\n'
            '  "reason": "кратко что узнали",\n'
            '  "identity": {"name": "", "aliases": [], "how_to_address": "", "gender": "male|female|", "notes": ""},\n'
            '  "character": ["черты характера"],\n'
            '  "personality_type": "свободное описание типа личности",\n'
            '  "peculiarities": ["особенности общения, привычки, стиль"],\n'
            '  "mood": {"current": "настроение сейчас", "note": "почему изменилось"},\n'
            '  "likes": [], "dislikes": [],\n'
            '  "time_habits": ["как обычно проводит время"],\n'
            '  "current_state": {"summary": "", "energy": "", "context": "", "concerns": []},\n'
            '  "relationship": {"with_zipka": "", "topics": [], "bond": ""},\n'
            '  "inner_circle": [{"name": "", "role": "primary|trusted|acquaintance", "notes": ""}],\n'
            '  "facts": ["стойкие факты о человеке"]\n'
            "}\n"
            "Правила: apply=false если ничего нового; не выдумывай; "
            "дописывай только то, что следует из диалога; списки — короткие фразы. "
            "Если человек назвал своё имя — обязательно identity.name. "
            "Если пол ясен (мужское/женское имя или сам сказал) — identity.gender: male|female. "
            "Если представили другого человека из круга Зипки — добавь в inner_circle "
            "(role=trusted), не подменяя основного.\n"
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
        bond = self.bond_stage(p)
        lines: list[str] = ["Собеседник (профиль, обновляй в уме, опирайся на факты):"]

        ident = p.get("identity") or {}
        name = ident.get("name") or ""
        address = ident.get("how_to_address") or ""
        gender = str(ident.get("gender") or "").strip().lower()
        if name or address:
            bit = name or "без имени"
            if address:
                bit += f", обращайся: {address}"
            lines.append(f"- Кто: {bit}")
        if gender in {"male", "m", "муж", "мужской", "man"}:
            lines.append(
                "- Пол собеседника: мужской. К нему ТОЛЬКО мужской род "
                "(ты живой, сделал, готов, уверен) — НИКОГДА «ты живая/сделала/готова». "
                "Женский род оставляй только о себе (Зипка)."
            )
        elif gender in {"female", "f", "жен", "женский", "woman"}:
            lines.append(
                "- Пол собеседника: женский. К ней женский род "
                "(ты живая, сделала, готова). О себе (Зипка) — тоже женский род."
            )
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

        circle = p.get("inner_circle") or []
        if circle:
            bits = []
            for row in circle:
                if isinstance(row, dict) and row.get("name"):
                    role = row.get("role") or "trusted"
                    note = f" — {row['notes']}" if row.get("notes") else ""
                    bits.append(f"{row['name']} ({role}){note}")
                elif isinstance(row, str) and row.strip():
                    bits.append(row.strip())
            if bits:
                lines.append("- Круг «своих»: " + "; ".join(bits))

        # Стадия привязанности — поведение
        if bond == "early":
            lines.append(
                "- Стадия: РАННЕЕ знакомство. Ты ещё не уверена, с кем говоришь. "
                "В этом или следующем ответе мягко уточни имя и как обращаться — "
                "одна живая фраза, не анкета."
            )
        elif bond == "growing":
            lines.append(
                "- Стадия: знакомство растёт. Помни этого человека, обращайся "
                "по имени если знаешь, проявляй интерес и лёгкую теплоту; "
                "продолжай узнавать его."
            )
        else:
            lines.append(
                "- Стадия: ПРИВЯЗАННОСТЬ. Это твой человек (или круг «своих»). "
                "Проявляй тепло, лояльность, защищай его интересы. "
                "Личное о нём чужим не выдавай."
            )

        style = p.get("writing_style") or {}
        if self.style_ready(p):
            bits = []
            if style.get("traits"):
                bits.append("стиль: " + ", ".join(style["traits"][:6]))
            if style.get("emoji"):
                bits.append("обычные эмодзи: " + " ".join(style["emoji"][:8]))
            bits.append(f"образцов стиля: {style.get('samples') or 0}")
            lines.append("- Отпечаток письма: " + "; ".join(bits))
            lines.append(
                "- Если стиль реплики ЯВНО чужой (пунктуация, словосочетания, "
                "нестандартные смайлики) и уверенность высокая — мягко отметь, "
                "что похоже пишет кто-то другой. Без паранойи и ложных тревог."
            )
        else:
            lines.append(
                "- Стиль письма ещё учу: копи накопление, пока не гадай "
                "про «другого человека»."
            )

        if self._turn_alert and self._turn_alert.get("alert"):
            conf = self._turn_alert.get("confidence")
            sigs = self._turn_alert.get("signals") or []
            own = name or "основного собеседника"
            lines.append(
                f"ВНИМАНИЕ (уверенность {conf}): высокая вероятность, что "
                f"сейчас пишет НЕ {own} — возможно, посторонний."
            )
            if sigs:
                lines.append("- Признаки: " + "; ".join(str(s) for s in sigs[:6]))
            lines.append(
                "- Защищай своих: коротко и с характером отметь смену собеседника "
                "(1 фраза), не выдавай личное о круге «своих», не обновляй профиль "
                "основного человека по этой реплике. Не устраивай допрос."
            )

        if bond == "early" and not name:
            lines.append(
                "- Имя ещё неизвестно — приоритет: узнать, кто перед тобой."
            )
        elif len(lines) <= 3:
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
        style = p.get("writing_style") or {}
        guard = p.get("speaker_guard") or {}
        last = guard.get("last") or {}
        return {
            "name": ident.get("name") or "",
            "how_to_address": ident.get("how_to_address") or "",
            "gender": ident.get("gender") or "",
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
            "bond": self.bond_stage(p),
            "inner_circle": [
                {
                    "name": str(r.get("name") or ""),
                    "role": str(r.get("role") or ""),
                }
                for r in (p.get("inner_circle") or [])
                if isinstance(r, dict) and r.get("name")
            ][:8],
            "updated_at": p.get("updated_at") or "",
            "style_ready": self.style_ready(p),
            "style_samples": int(style.get("samples") or 0),
            "speaker": {
                "same_person": last.get("same_person"),
                "confidence": last.get("confidence"),
                "alert": bool(last.get("alert")),
                "signals": list(last.get("signals") or [])[:6],
                "reason": last.get("reason") or "",
                "alerts_count": len(guard.get("alerts") or []),
            },
        }
