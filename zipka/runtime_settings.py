from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from zipka.config import Settings, ensure_data_dirs, get_settings

ComputeMode = Literal["cpu", "gpu", "hybrid"]

DEFAULT_RUNTIME: dict[str, Any] = {
    "compute_mode": "cpu",
    "gpu_layers": 16,
    "chat_model_id": "pathfinder",
}


def _runtime_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    ensure_data_dirs(settings)
    folder = settings.data_dir / "settings"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "runtime.json"


def load_runtime(settings: Settings | None = None) -> dict[str, Any]:
    path = _runtime_path(settings)
    if not path.exists():
        return dict(DEFAULT_RUNTIME)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_RUNTIME)
    if not isinstance(data, dict):
        return dict(DEFAULT_RUNTIME)
    out = dict(DEFAULT_RUNTIME)
    out.update(data)
    mode = str(out.get("compute_mode") or "cpu").lower()
    if mode not in {"cpu", "gpu", "hybrid"}:
        mode = "cpu"
    out["compute_mode"] = mode
    try:
        out["gpu_layers"] = max(1, min(int(out.get("gpu_layers") or 16), 128))
    except (TypeError, ValueError):
        out["gpu_layers"] = 16
    chat_id = str(out.get("chat_model_id") or "pathfinder").strip().lower()
    if chat_id not in {"pathfinder", "qwen25"}:
        chat_id = "pathfinder"
    out["chat_model_id"] = chat_id
    return out


def save_runtime(patch: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    current = load_runtime(settings)
    if "compute_mode" in patch and patch["compute_mode"] is not None:
        mode = str(patch["compute_mode"]).lower()
        if mode not in {"cpu", "gpu", "hybrid"}:
            raise ValueError("compute_mode: cpu | gpu | hybrid")
        current["compute_mode"] = mode
    if "gpu_layers" in patch and patch["gpu_layers"] is not None:
        current["gpu_layers"] = max(1, min(int(patch["gpu_layers"]), 128))
    if "chat_model_id" in patch and patch["chat_model_id"] is not None:
        chat_id = str(patch["chat_model_id"]).strip().lower()
        if chat_id not in {"pathfinder", "qwen25"}:
            raise ValueError("chat_model_id: pathfinder | qwen25")
        current["chat_model_id"] = chat_id
    path = _runtime_path(settings)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def resolve_gpu_layers(settings: Settings | None = None) -> int:
    """Слои на GPU для llama.cpp: 0=CPU, -1=все на GPU, N=гибрид."""
    settings = settings or get_settings()
    rt = load_runtime(settings)
    mode = rt["compute_mode"]
    if mode == "cpu":
        return 0
    if mode == "gpu":
        return -1
    # hybrid: UI-заданое число, иначе .env
    env_layers = int(settings.zipka_gguf_gpu_layers or 0)
    if env_layers > 0 and not rt.get("gpu_layers"):
        return env_layers
    return int(rt.get("gpu_layers") or 16)


def hybrid_explain(
    *,
    n_gpu: int,
    n_layer: int | None = None,
) -> str:
    """Понятное объяснение hybrid для UI."""
    if n_layer and n_layer > 0:
        gpu = min(max(0, n_gpu), n_layer)
        cpu = n_layer - gpu
        pct = round(100 * gpu / n_layer)
        tip = (
            f"Hybrid: {gpu}/{n_layer} слоёв на GPU (~{pct}%), {cpu} на CPU. "
            "Нагрузка в основном на видеокарте — CPU в диспетчере часто почти не видно. "
            "Чтобы сильнее задействовать процессор, снизь слайдер (8–16)."
        )
        if gpu >= n_layer:
            tip = (
                f"Hybrid: {n_gpu} ≥ {n_layer} слоёв модели — фактически весь расчёт на GPU "
                "(как режим GPU). Уменьши слайдер, если нужен CPU."
            )
        return tip
    return (
        f"Hybrid: {n_gpu} слоёв на GPU, остальные на CPU. "
        "Pathfinder ≈40 слоёв: при 24 на GPU процессор почти не заметно. "
        "Для заметного CPU поставь 8–16."
    )


def detect_gpu_capability() -> dict[str, Any]:
    """Может ли текущий llama-cpp реально оффлоадить на GPU."""
    llama_gpu = False
    nvidia = False
    note = ""
    try:
        from zipka.llm.gguf_client import probe_llama_cpp

        ok, err = probe_llama_cpp()
        if not ok:
            note = err or "llama-cpp-python не загружается."
        else:
            import llama_cpp

            fn = getattr(llama_cpp, "llama_supports_gpu_offload", None)
            if callable(fn):
                llama_gpu = bool(fn())
            else:
                llama_gpu = any(
                    hasattr(llama_cpp, name)
                    for name in ("LLAMA_SUPPORTS_GPU_OFFLOAD", "llama_backend_init")
                )
    except Exception:
        note = "Не удалось проверить llama-cpp-python."

    try:
        if shutil.which("nvidia-smi"):
            proc = subprocess.run(
                ["nvidia-smi", "-L"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            nvidia = proc.returncode == 0 and bool((proc.stdout or "").strip())
    except (OSError, subprocess.TimeoutExpired):
        pass

    if not note:
        if llama_gpu:
            note = "GPU offload доступен (можно cpu / gpu / hybrid)."
        elif nvidia:
            note = (
                "Видеокарта NVIDIA есть, но llama-cpp-python без GPU. "
                "Для GPU поставь CUDA-колесо с "
                "https://abetlen.github.io/llama-cpp-python/whl/cu124 "
                "(или cu121/cu122 под свою CUDA)."
            )
        else:
            note = (
                "Сейчас только CPU (типично для win_amd64 CPU-колеса). "
                "Режимы GPU/hybrid включатся после установки CUDA-сборки."
            )
    return {
        "llama_gpu_offload": llama_gpu,
        "nvidia_detected": nvidia,
        "note": note,
    }


def compute_status(
    settings: Settings | None = None,
    *,
    load_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    rt = load_runtime(settings)
    layers = resolve_gpu_layers(settings)
    cap = detect_gpu_capability()
    n_layer = None
    if load_info and load_info.get("n_layer"):
        try:
            n_layer = int(load_info["n_layer"])
        except (TypeError, ValueError):
            n_layer = None
    hybrid_note = hybrid_explain(
        n_gpu=int(rt.get("gpu_layers") or 16),
        n_layer=n_layer,
    )
    note = cap.get("note") or ""
    if rt["compute_mode"] == "hybrid":
        note = f"{hybrid_note} {note}".strip()
    out: dict[str, Any] = {
        "mode": rt["compute_mode"],
        "gpu_layers": rt["gpu_layers"],
        "resolved_n_gpu_layers": layers,
        "hybrid_possible": True,
        "hybrid_hint": hybrid_note,
        **cap,
        "note": note,
    }
    if load_info:
        out["load"] = load_info
    return out
