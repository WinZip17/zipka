"""Локальный vision через GGUF + mmproj (без Ollama)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zipka.config import Settings, get_settings
from zipka.llm.base import LlmError
from zipka.llm.gguf_client import find_gguf_files, probe_llama_cpp
from zipka.llm.sanitize import strip_thinking
from zipka.runtime_settings import load_runtime, resolve_gpu_layers

# id → файлы для скачивания (лёгкая vision ~3GB, влезает после выгрузки чата)
VISION_PROFILES: dict[str, dict[str, Any]] = {
    "moondream2": {
        "id": "moondream2",
        "label": "Moondream2 (vision)",
        "blurb": "описание кадров без Ollama (~3 GB)",
        "handler": "moondream2",
        "filename": "moondream2-text-model-f16_ct-vicuna.gguf",
        "mmproj": "moondream2-mmproj-f16-20250414.gguf",
        "hf_repo": "Hahasb/moondream2-20250414-GGUF",
        "hf_file": "moondream2-text-model-f16_ct-vicuna.gguf",
        "hf_mmproj": "moondream2-mmproj-f16-20250414.gguf",
        "url": (
            "https://huggingface.co/Hahasb/moondream2-20250414-GGUF/resolve/main/"
            "moondream2-text-model-f16_ct-vicuna.gguf"
        ),
        "url_mmproj": (
            "https://huggingface.co/Hahasb/moondream2-20250414-GGUF/resolve/main/"
            "moondream2-mmproj-f16-20250414.gguf"
        ),
        "size_hint_gb": 3.5,
    },
}


def _handler_for_name(model_name: str, mmproj_name: str) -> str:
    blob = f"{model_name} {mmproj_name}".lower()
    if "moondream" in blob:
        return "moondream2"
    if "minicpm" in blob:
        return "minicpm-v-2.6"
    if "qwen2.5-vl" in blob or "qwen2-vl" in blob or "qwen25vl" in blob:
        return "qwen2.5-vl"
    if "llava-v1.6" in blob or "llava1.6" in blob or "llava-1.6" in blob:
        return "llava-1-6"
    if "llava" in blob or "bakllava" in blob:
        return "llava-1-5"
    return "llava-1-5"


def _make_handler(handler_id: str, clip_path: Path) -> Any:
    from llama_cpp import llama_chat_format as fmt

    path = str(clip_path)
    mapping = {
        "moondream2": getattr(fmt, "MoondreamChatHandler", None),
        "llava-1-5": getattr(fmt, "Llava15ChatHandler", None),
        "llava-1-6": getattr(fmt, "Llava16ChatHandler", None),
        "minicpm-v-2.6": getattr(fmt, "MiniCPMv26ChatHandler", None),
        "qwen2.5-vl": getattr(fmt, "Qwen25VLChatHandler", None),
    }
    cls = mapping.get(handler_id) or mapping["llava-1-5"]
    if cls is None:
        raise LlmError(f"В llama-cpp-python нет handler «{handler_id}».")
    return cls(clip_model_path=path, verbose=False)


def find_vision_pairs(models_dir: Path) -> list[dict[str, Any]]:
    """Пары (text GGUF + mmproj) в data/models."""
    if not models_dir.is_dir():
        return []
    mmprojs = [
        p
        for p in find_gguf_files(models_dir)
        if "mmproj" in p.name.lower()
    ]
    pairs: list[dict[str, Any]] = []
    for mm in mmprojs:
        siblings = [
            p
            for p in find_gguf_files(mm.parent)
            if p.resolve() != mm.resolve() and "mmproj" not in p.name.lower()
        ]
        if not siblings:
            # иногда mmproj лежит рядом с моделями в корне models/
            siblings = [
                p
                for p in find_gguf_files(models_dir)
                if p.resolve() != mm.resolve() and "mmproj" not in p.name.lower()
            ]
        if not siblings:
            continue
        # предпочитаем файл с похожим префиксом
        mm_stem = mm.name.lower().replace("mmproj", "").strip("-_.")
        scored: list[tuple[int, Path]] = []
        for s in siblings:
            score = 0
            low = s.name.lower()
            if "moondream" in low and "moondream" in mm.name.lower():
                score += 20
            if "llava" in low and "llava" in mm.name.lower():
                score += 15
            for token in mm_stem.split("-")[:3]:
                if len(token) > 3 and token in low:
                    score += 2
            # не брать чатовые Pathfinder/Qwen как vision text
            if any(
                t in low
                for t in ("pathfinder", "qwen2.5-7b-instruct", "qwen3-8b-q4")
            ):
                score -= 50
            scored.append((score, s))
        scored.sort(key=lambda x: (-x[0], x[1].stat().st_size if x[1].is_file() else 0))
        text = scored[0][1]
        if scored[0][0] < 0 and len(scored) > 1:
            # все чатовые — всё равно возьмём лучший из mmproj-соседей
            same_dir = [s for sc, s in scored if s.parent == mm.parent and sc >= 0]
            text = same_dir[0] if same_dir else scored[0][1]
        handler = _handler_for_name(text.name, mm.name)
        pairs.append(
            {
                "model_path": text,
                "mmproj_path": mm,
                "filename": text.name,
                "mmproj": mm.name,
                "handler": handler,
                "label": text.stem,
            }
        )
    # дедуп по model_path
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for p in pairs:
        key = str(p["model_path"].resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def resolve_vision_pair(settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    models_dir = settings.data_dir / "models"
    rt = load_runtime(settings)
    want_model = Path(str(rt.get("vision_gguf") or "").strip()).name
    want_mm = Path(str(rt.get("vision_mmproj") or "").strip()).name

    pairs = find_vision_pairs(models_dir)
    if want_model:
        for p in pairs:
            if p["filename"].lower() == want_model.lower():
                if want_mm and p["mmproj"].lower() != want_mm.lower():
                    mm = models_dir / want_mm
                    if mm.is_file():
                        p = dict(p)
                        p["mmproj_path"] = mm
                        p["mmproj"] = mm.name
                return p
        # явный файл без автопары
        model_path = models_dir / want_model
        if model_path.is_file() and want_mm:
            mm = models_dir / want_mm
            if mm.is_file():
                return {
                    "model_path": model_path,
                    "mmproj_path": mm,
                    "filename": model_path.name,
                    "mmproj": mm.name,
                    "handler": _handler_for_name(model_path.name, mm.name),
                    "label": model_path.stem,
                }
    if pairs:
        # moondream предпочтительнее (меньше VRAM)
        pairs_sorted = sorted(
            pairs,
            key=lambda p: (0 if "moondream" in p["filename"].lower() else 1, p["filename"]),
        )
        return pairs_sorted[0]
    return None


def vision_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    pair = resolve_vision_pair(settings)
    pairs = find_vision_pairs(settings.data_dir / "models")
    return {
        "available": pair is not None,
        "backend": "gguf" if pair else None,
        "filename": pair["filename"] if pair else None,
        "mmproj": pair["mmproj"] if pair else None,
        "handler": pair["handler"] if pair else None,
        "label": pair["label"] if pair else None,
        "path": str(pair["model_path"]) if pair else None,
        "pairs": [
            {
                "filename": p["filename"],
                "mmproj": p["mmproj"],
                "handler": p["handler"],
                "label": p["label"],
            }
            for p in pairs
        ],
        "download_hint": (
            "python -m zipka.main models download --id moondream2"
            if pair is None
            else None
        ),
        "ollama_fallback": True,
    }


class VisionGgufClient:
    """Отдельный короткий GGUF только для описания картинок."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._llm: Any = None
        self._pair: dict[str, Any] | None = None

    def is_available(self) -> bool:
        ok, _ = probe_llama_cpp()
        return ok and resolve_vision_pair(self.settings) is not None

    def unload(self) -> None:
        llm = self._llm
        self._llm = None
        self._pair = None
        if llm is not None:
            close = getattr(llm, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def _ensure_loaded(self) -> Any:
        pair = resolve_vision_pair(self.settings)
        if pair is None:
            raise LlmError(
                "Нет локальной vision-модели (GGUF + mmproj) в data/models. "
                "Скачай: python -m zipka.main models download --id moondream2"
            )
        ok, err = probe_llama_cpp()
        if not ok:
            raise LlmError(err or "llama-cpp-python недоступен")

        same = (
            self._llm is not None
            and self._pair
            and self._pair.get("filename") == pair["filename"]
            and self._pair.get("mmproj") == pair["mmproj"]
        )
        if same:
            return self._llm

        self.unload()
        from llama_cpp import Llama

        handler = _make_handler(pair["handler"], pair["mmproj_path"])
        n_gpu = int(resolve_gpu_layers(self.settings))
        # vision обычно небольшой — можно больше слоёв на GPU
        if n_gpu == 0:
            n_gpu = 0
        kwargs: dict[str, Any] = {
            "model_path": str(pair["model_path"]),
            "chat_handler": handler,
            "n_ctx": min(4096, max(2048, int(self.settings.zipka_gguf_ctx))),
            "n_gpu_layers": n_gpu if n_gpu != 0 else 0,
            "logits_all": True,
            "verbose": False,
        }
        try:
            self._llm = Llama(**kwargs)
        except TypeError:
            kwargs.pop("logits_all", None)
            self._llm = Llama(**kwargs)
        self._pair = pair
        return self._llm

    def describe(
        self,
        image_b64: str,
        prompt: str = "Что ты видишь? Опиши кратко по-русски.",
    ) -> str:
        llm = self._ensure_loaded()
        raw = (image_b64 or "").strip()
        if raw.startswith("data:"):
            data_uri = raw
        else:
            data_uri = f"data:image/jpeg;base64,{raw}"

        messages = [
            {
                "role": "system",
                "content": (
                    "Ты глаза Зипки. Опиши изображение кратко и по делу, по-русски. "
                    "Без воды и без выдумок."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": prompt},
                ],
            },
        ]
        try:
            out = llm.create_chat_completion(
                messages=messages,
                max_tokens=min(512, int(self.settings.zipka_gguf_max_tokens or 512)),
                temperature=0.2,
            )
        except Exception as exc:
            raise LlmError(f"Vision GGUF не смог описать кадр: {exc}") from exc

        choice = (out.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        return strip_thinking(text).strip() or "(пустое описание кадра)"
