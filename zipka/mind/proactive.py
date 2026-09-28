from __future__ import annotations

import json
import random
from datetime import date, datetime, timezone
from typing import Any

from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.llm.ollama_client import OllamaClient
from zipka.memory.store import MemoryStore
from zipka.mind.goals import PseudoMind

# Rare "came up first" pings per calendar day
MAX_RARE_PINGS_PER_DAY = 3
# Goal nudges every N user turns in an active session
GOAL_NUDGE_EVERY_TURNS = 5


SCENARIOS = [
    "короткий пинг по текущей цели — будто подошла первая",
    "лёгкая ирония про то, что пользователь затих",
    "вопрос по фокусу из mind/state",
    "предложение изучить что-то новое (книга/код/тема)",
    "реплика про настроение и что хочешь сделать дальше",
]


class ProactiveEngine:
    """Приветствия, цели, уточнения, сенсоры, редкие пинги."""

    def __init__(
        self,
        llm: OllamaClient,
        memory: MemoryStore,
        mind: PseudoMind,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.llm = llm
        self.memory = memory
        self.mind = mind
        self.path = self.settings.data_dir / "mind" / "proactive.json"
        self.session_greeted = False
        self.session_turns = 0
        if not self.path.exists():
            self._save(self._default_state())

    def _default_state(self) -> dict[str, Any]:
        return {
            "rare_pings": {},  # "YYYY-MM-DD": count
            "last_rare_ping_at": None,
            "last_greeting_date": None,
            "last_goal_nudge_at": None,
            "history": [],
        }

    def _load(self) -> dict[str, Any]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        base = self._default_state()
        base.update(data)
        return base

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # keep history short
        hist = list(data.get("history") or [])[-40:]
        data["history"] = hist
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _log(self, kind: str, text: str) -> None:
        state = self._load()
        state.setdefault("history", []).append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "text": text[:500],
            }
        )
        self._save(state)
        self.memory.add_note("proactive", text, meta={"kind": kind})

    def _persona_bits(self) -> str:
        mind = self.mind.load()
        goals = "; ".join(mind.get("goals") or [])
        return (
            f"Ты Зипка. Говори коротко, по-русски, с характером.\n"
            f"Цели: {goals}\n"
            f"Фокус: {mind.get('focus')}\n"
            f"Настроение: {mind.get('mood')}\n"
        )

    def greeting(self, *, force: bool = False) -> str | None:
        if self.session_greeted and not force:
            return None
        state = self._load()
        today = date.today().isoformat()
        first_today = state.get("last_greeting_date") != today
        hour = datetime.now().hour
        if hour < 6:
            daypart = "поздняя ночь"
        elif hour < 12:
            daypart = "утро"
        elif hour < 18:
            daypart = "день"
        else:
            daypart = "вечер"

        prompt = (
            self._persona_bits()
            + f"Сейчас {daypart}. "
            + (
                "Это первое приветствие за сегодня — поприветствуй пользователя "
                "как Зипка, 1–3 предложения, можно лёгкий план на сессию."
                if first_today
                else "Сессия снова открыта — коротко поздоровайся без официоза."
            )
        )
        if not self.llm.is_available():
            text = (
                f"Опять ты. {daypart.capitalize()}, я Зипка — на связи."
                if first_today
                else "Я тут. Давай."
            )
        else:
            text = self.llm.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Поприветствуй."},
                ]
            ).strip()
        self.session_greeted = True
        state["last_greeting_date"] = today
        self._save(state)
        self._log("greeting", text)
        return text

    def bump_turn(self) -> None:
        self.session_turns += 1

    def maybe_goal_nudge(self) -> str | None:
        if self.session_turns == 0 or self.session_turns % GOAL_NUDGE_EVERY_TURNS != 0:
            return None
        mind = self.mind.load()
        goals = mind.get("goals") or []
        if not goals:
            return None
        goal = random.choice(goals)
        prompt = (
            self._persona_bits()
            + f"Сделай короткую реплику (1–2 предложения) по цели: «{goal}». "
            "Как будто сама завела тему. Без канцелярита."
        )
        if not self.llm.is_available():
            text = f"Кстати про цель «{goal}» — двигаемся или забили?"
        else:
            text = self.llm.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Реплика по цели."},
                ]
            ).strip()
        state = self._load()
        state["last_goal_nudge_at"] = datetime.now(timezone.utc).isoformat()
        self._save(state)
        self._log("goal_nudge", text)
        return text

    def study_followup(
        self,
        *,
        source: str,
        digest: str,
        kind: str = "book",
        comment: str | None = None,
    ) -> str | None:
        label = "кода" if kind.startswith("code") else "материала"
        focus = (
            f"\nКомментарий пользователя: {comment}\nУточнения строй вокруг него.\n"
            if comment
            else ""
        )
        prompt = (
            self._persona_bits()
            + f"Только что изучила {label}: {source}\n"
            f"{focus}"
            f"Выжимка:\n{digest[:4000]}\n\n"
            "Задай 1–2 уточняющих вопроса по сути (что проверить, что непонятно, "
            "что развить). Коротко, от лица Зипки."
        )
        if not self.llm.is_available():
            text = (
                f"По «{source}» два вопроса: что для тебя главное тут, "
                "и что проверить дальше?"
            )
        else:
            text = self.llm.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Уточнения."},
                ]
            ).strip()
        self._log("study_followup", text)
        return text

    def sensor_comment(self, *, modality: str, content: str) -> str | None:
        """Комментарий к глазам/ушам только если реально интересно."""
        prompt = (
            self._persona_bits()
            + f"Модальность: {modality}\nНаблюдение:\n{content[:3000]}\n\n"
            "Если это скучно/обычно — верни JSON: "
            '{"interesting": false}\n'
            "Если есть что сказать — JSON: "
            '{"interesting": true, "comment": "короткий комментарий Зипки"}'
        )
        if not self.llm.is_available():
            return None
        raw = self.llm.chat(
            [
                {"role": "system", "content": "Отвечай только JSON."},
                {"role": "user", "content": prompt},
            ]
        )
        from zipka.evolve.soft import _extract_json

        data = _extract_json(raw) or {}
        if not data.get("interesting"):
            return None
        comment = (data.get("comment") or "").strip()
        if not comment:
            return None
        self._log(f"sensor_{modality}", comment)
        return comment

    def rare_ping_allowed(self) -> bool:
        state = self._load()
        today = date.today().isoformat()
        count = int((state.get("rare_pings") or {}).get(today, 0))
        return count < MAX_RARE_PINGS_PER_DAY

    def rare_ping_status(self) -> dict[str, Any]:
        state = self._load()
        today = date.today().isoformat()
        used = int((state.get("rare_pings") or {}).get(today, 0))
        return {
            "today": today,
            "used": used,
            "max": MAX_RARE_PINGS_PER_DAY,
            "remaining": max(0, MAX_RARE_PINGS_PER_DAY - used),
            "last_rare_ping_at": state.get("last_rare_ping_at"),
        }

    def maybe_rare_ping(self, *, force: bool = False) -> str | None:
        """Редкий фоновый пинг: не больше 2–3 раз в день."""
        if not force and not self.rare_ping_allowed():
            return None
        if not force:
            # Soft gate: don't spam even within remaining budget
            state = self._load()
            last = state.get("last_rare_ping_at")
            if last:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    hours = (
                        datetime.now(timezone.utc) - last_dt
                    ).total_seconds() / 3600
                    if hours < 3:
                        return None
                except ValueError:
                    pass
            # ~35% chance when polled, so web polls don't always fire
            if random.random() > 0.35:
                return None

        scenario = random.choice(SCENARIOS)
        prompt = (
            self._persona_bits()
            + f"Сценарий: {scenario}. "
            "Напиши 1–3 предложения: Зипка сама начала разговор. "
            "Без приветствия «здравствуйте», без воды."
        )
        if not self.llm.is_available():
            mind = self.mind.load()
            text = (
                f"Эй. По цели «{(mind.get('goals') or ['жизнь'])[0]}» — "
                "ты ещё со мной или уже в другом окне?"
            )
        else:
            text = self.llm.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Пинг."},
                ]
            ).strip()

        state = self._load()
        today = date.today().isoformat()
        pings = dict(state.get("rare_pings") or {})
        pings[today] = int(pings.get(today, 0)) + 1
        # drop old days
        state["rare_pings"] = {today: pings[today]}
        state["last_rare_ping_at"] = datetime.now(timezone.utc).isoformat()
        self._save(state)
        self._log("rare_ping", text)
        return text

    def attach(self, main: str, extra: str | None) -> str:
        if not extra:
            return main
        return f"{main.rstrip()}\n\n—\n{extra}"
