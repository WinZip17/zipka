from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from zipka.config import Settings, ensure_data_dirs, get_settings

ComputeMode = Literal["cpu", "gpu", "hybrid"]


def _clamp_float(value: Any, *, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def _clamp_int(value: Any, *, lo: int, hi: int, default: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def normalize_sampling(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Нормализованные параметры сэмплинга / контекста для чата."""
    src = data or {}
    return {
        "temperature": _clamp_float(
            src.get("temperature", DEFAULT_RUNTIME["temperature"]),
            lo=0.0,
            hi=2.0,
            default=float(DEFAULT_RUNTIME["temperature"]),
        ),
        "repeat_penalty": _clamp_float(
            src.get("repeat_penalty", DEFAULT_RUNTIME["repeat_penalty"]),
            lo=1.0,
            hi=2.0,
            default=float(DEFAULT_RUNTIME["repeat_penalty"]),
        ),
        "seed": _clamp_int(
            src.get("seed", DEFAULT_RUNTIME["seed"]),
            lo=-1,
            hi=2_147_483_647,
            default=int(DEFAULT_RUNTIME["seed"]),
        ),
        "enable_thinking": bool(
            src.get("enable_thinking", DEFAULT_RUNTIME["enable_thinking"])
        ),
        "num_ctx": _clamp_int(
            src.get("num_ctx", DEFAULT_RUNTIME["num_ctx"]),
            lo=2048,
            hi=131072,
            default=int(DEFAULT_RUNTIME["num_ctx"]),
        ),
    }


DEFAULT_RUNTIME: dict[str, Any] = {
    "compute_mode": "cpu",
    "gpu_layers": 16,
    "chat_gguf": "Pathfinder-RP-12B-RU.Q4_K_M.gguf",
    "code_gguf": "Qwen2.5-7B-Instruct-Q5_K_M.gguf",
    "vision_gguf": "",
    "vision_mmproj": "",
    "soft_evolve_from_dialogue": False,
    "sensors_enabled": False,
    "whisper_model": "small",
    # sampling (чат GGUF/Ollama)
    "temperature": 0.7,
    "repeat_penalty": 1.1,
    "seed": -1,  # -1 = случайный
    "enable_thinking": False,
    "num_ctx": 8192,
}


def _runtime_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    ensure_data_dirs(settings)
    folder = settings.data_dir / "settings"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "runtime.json"


def load_runtime(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    path = _runtime_path(settings)
    data: dict[str, Any] | None = None
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError):
            data = None
    if data is None:
        out = dict(DEFAULT_RUNTIME)
        from zipka.sensors.ears import normalize_whisper_model

        out["whisper_model"] = normalize_whisper_model(
            settings.zipka_whisper_model, default="small"
        )
        return out
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

    # миграция legacy chat_model_id → chat_gguf
    from zipka.llm.chat_models import LEGACY_IDS, _normalize_name

    if not str(out.get("chat_gguf") or "").strip():
        legacy = str(out.get("chat_model_id") or "").strip()
        if legacy:
            out["chat_gguf"] = LEGACY_IDS.get(legacy.lower(), _normalize_name(legacy))
    out["chat_gguf"] = _normalize_name(out.get("chat_gguf")) or DEFAULT_RUNTIME["chat_gguf"]
    out["code_gguf"] = _normalize_name(out.get("code_gguf")) or DEFAULT_RUNTIME["code_gguf"]
    # keep legacy field in sync for old readers
    out["chat_model_id"] = out["chat_gguf"]
    out["soft_evolve_from_dialogue"] = bool(out.get("soft_evolve_from_dialogue"))
    out["sensors_enabled"] = bool(out.get("sensors_enabled"))
    from zipka.sensors.ears import normalize_whisper_model

    # runtime.json явно → иначе ZIPKA_WHISPER_MODEL / Settings
    whisper_src = (
        data["whisper_model"]
        if "whisper_model" in data
        else settings.zipka_whisper_model
    )
    out["whisper_model"] = normalize_whisper_model(whisper_src, default="small")
    out.update(normalize_sampling(out))
    return out


def save_runtime(patch: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    from zipka.llm.chat_models import LEGACY_IDS, _normalize_name

    current = load_runtime(settings)
    if "compute_mode" in patch and patch["compute_mode"] is not None:
        mode = str(patch["compute_mode"]).lower()
        if mode not in {"cpu", "gpu", "hybrid"}:
            raise ValueError("compute_mode: cpu | gpu | hybrid")
        current["compute_mode"] = mode
    if "gpu_layers" in patch and patch["gpu_layers"] is not None:
        current["gpu_layers"] = max(1, min(int(patch["gpu_layers"]), 128))

    if "chat_gguf" in patch and patch["chat_gguf"] is not None:
        current["chat_gguf"] = _normalize_name(patch["chat_gguf"])
    if "code_gguf" in patch and patch["code_gguf"] is not None:
        current["code_gguf"] = _normalize_name(patch["code_gguf"])
    if "vision_gguf" in patch and patch["vision_gguf"] is not None:
        current["vision_gguf"] = _normalize_name(patch["vision_gguf"])
    if "vision_mmproj" in patch and patch["vision_mmproj"] is not None:
        current["vision_mmproj"] = _normalize_name(patch["vision_mmproj"])
    if "soft_evolve_from_dialogue" in patch and patch["soft_evolve_from_dialogue"] is not None:
        current["soft_evolve_from_dialogue"] = bool(patch["soft_evolve_from_dialogue"])
    if "sensors_enabled" in patch and patch["sensors_enabled"] is not None:
        current["sensors_enabled"] = bool(patch["sensors_enabled"])
    if "whisper_model" in patch and patch["whisper_model"] is not None:
        from zipka.sensors.ears import normalize_whisper_model

        current["whisper_model"] = normalize_whisper_model(
            patch["whisper_model"],
            default=str(
                (settings or get_settings()).zipka_whisper_model or "small"
            ),
        )

    sampling_keys = (
        "temperature",
        "repeat_penalty",
        "seed",
        "enable_thinking",
        "num_ctx",
    )
    if any(k in patch and patch[k] is not None for k in sampling_keys):
        merged = {k: current.get(k) for k in sampling_keys}
        for k in sampling_keys:
            if k in patch and patch[k] is not None:
                merged[k] = patch[k]
        current.update(normalize_sampling(merged))

    # legacy API: chat_model_id как id или filename
    if "chat_model_id" in patch and patch["chat_model_id"] is not None:
        raw = str(patch["chat_model_id"]).strip()
        current["chat_gguf"] = LEGACY_IDS.get(raw.lower(), _normalize_name(raw))

    current["chat_model_id"] = current["chat_gguf"]
    current["vision_gguf"] = _normalize_name(current.get("vision_gguf")) or ""
    current["vision_mmproj"] = _normalize_name(current.get("vision_mmproj")) or ""
    current["soft_evolve_from_dialogue"] = bool(
        current.get("soft_evolve_from_dialogue")
    )
    current["sensors_enabled"] = bool(current.get("sensors_enabled"))
    from zipka.sensors.ears import normalize_whisper_model

    current["whisper_model"] = normalize_whisper_model(
        current.get("whisper_model"),
        default=str((settings or get_settings()).zipka_whisper_model or "small"),
    )
    current.update(normalize_sampling(current))
    path = _runtime_path(settings)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def sampling_status(settings: Settings | None = None) -> dict[str, Any]:
    """Параметры сэмплинга для status / UI."""
    return normalize_sampling(load_runtime(settings))


def resolve_whisper_model(settings: Settings | None = None) -> str:
    """Размер Whisper: runtime.json → ZIPKA_WHISPER_MODEL / Settings."""
    from zipka.sensors.ears import normalize_whisper_model

    settings = settings or get_settings()
    return normalize_whisper_model(
        load_runtime(settings).get("whisper_model"),
        default=str(settings.zipka_whisper_model or "small"),
    )


def resolve_gpu_layers(settings: Settings | None = None) -> int:
    """Слои на GPU для llama.cpp: 0=CPU, -1=все на GPU, N=гибрид."""
    settings = settings or get_settings()
    rt = load_runtime(settings)
    mode = rt["compute_mode"]
    if mode == "cpu":
        return 0
    if mode == "gpu":
        return -1
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


def list_cuda_devices() -> list[dict[str, Any]]:
    """Список NVIDIA GPU через nvidia-smi (Intel Iris сюда не попадает)."""
    if not shutil.which("nvidia-smi"):
        return []
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        vram = None
        if len(parts) >= 3:
            try:
                vram = int(float(parts[2]))
            except ValueError:
                vram = None
        out.append({"index": idx, "name": parts[1], "vram_mb": vram})
    return out


def pick_preferred_cuda_device(
    devices: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Выбрать дискретный NVIDIA (RTX/GTX/Quadro), не Intel."""
    devices = devices if devices is not None else list_cuda_devices()
    if not devices:
        return None

    def score(d: dict[str, Any]) -> tuple[int, int]:
        name = str(d.get("name") or "").lower()
        # Intel never in nvidia-smi; всё равно отсекаем на всякий
        if "intel" in name or "iris" in name or "uhd" in name:
            return (-100, int(d.get("vram_mb") or 0))
        s = 0
        if any(x in name for x in ("rtx", "gtx", "quadro", "tesla", "geforce")):
            s += 10
        if "laptop" in name or "mobile" in name:
            s += 1  # всё равно ок для ноутбука
        return (s, int(d.get("vram_mb") or 0))

    return max(devices, key=score)


def _prefer_windows_high_performance_gpu() -> str | None:
    """Windows: GpuPreference=2 (High performance) для текущего python.exe.

    Иначе при включённой iGPU (Iris) гибридная графика может слать процесс
    на Intel, а CUDA-память — на RTX.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        exe = str(Path(sys.executable).resolve())
        key_path = r"Software\Microsoft\DirectX\UserGpuPreferences"
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            # 2 = High performance (дискретная), 1 = Power saving (iGPU)
            winreg.SetValueEx(key, exe, 0, winreg.REG_SZ, "GpuPreference=2;")
        return exe
    except OSError:
        return None


def apply_cuda_device_preference(
    *,
    mode: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Перед загрузкой GGUF зафиксировать дискретный NVIDIA.

    - CUDA_DEVICE_ORDER=PCI_BUS_ID
    - CUDA_VISIBLE_DEVICES=<предпочитаемый индекс> (если пользователь не задал)
    - Windows High performance GPU для python.exe
    """
    mode = (mode or "").lower()
    if mode == "cpu":
        return {"applied": False, "reason": "cpu_mode"}

    devices = list_cuda_devices()
    preferred = pick_preferred_cuda_device(devices)
    info: dict[str, Any] = {
        "applied": False,
        "devices": devices,
        "preferred": preferred,
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "windows_gpu_pref": None,
    }
    if preferred is None:
        info["reason"] = "no_nvidia"
        return info

    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    # Не затирать явный выбор пользователя, кроме force
    if force or "CUDA_VISIBLE_DEVICES" not in os.environ:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(int(preferred["index"]))
        info["cuda_visible_devices"] = os.environ["CUDA_VISIBLE_DEVICES"]
        info["applied"] = True
    else:
        info["reason"] = "user_cuda_visible_devices"

    win_exe = _prefer_windows_high_performance_gpu()
    if win_exe:
        info["windows_gpu_pref"] = win_exe
        info["applied"] = True

    return info


def llama_gpu_kwargs(*, n_gpu_layers: int) -> dict[str, Any]:
    """Аргументы Llama для одного дискретного GPU (без split по устройствам)."""
    kwargs: dict[str, Any] = {"n_gpu_layers": int(n_gpu_layers)}
    if int(n_gpu_layers) == 0:
        return kwargs
    try:
        import llama_cpp

        split_none = getattr(llama_cpp, "LLAMA_SPLIT_MODE_NONE", 0)
    except Exception:
        split_none = 0
    kwargs["main_gpu"] = 0  # после CUDA_VISIBLE_DEVICES всегда локальный 0
    kwargs["split_mode"] = split_none
    kwargs["tensor_split"] = None
    return kwargs


def detect_gpu_capability() -> dict[str, Any]:
    """Может ли текущий llama-cpp реально оффлоадить на GPU."""
    llama_gpu = False
    nvidia = False
    note = ""
    devices = list_cuda_devices()
    preferred = pick_preferred_cuda_device(devices)
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

    nvidia = bool(devices) or bool(shutil.which("nvidia-smi"))
    if not devices and shutil.which("nvidia-smi"):
        try:
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
        if llama_gpu and preferred:
            vram = preferred.get("vram_mb")
            vram_bit = f", {vram} МБ" if vram else ""
            note = (
                f"GPU offload: {preferred.get('name')} "
                f"(CUDA{preferred.get('index')}{vram_bit}). "
                "Слои считаются на NVIDIA; в Диспетчере смотри график «CUDA» у RTX, "
                "не «3D» у Intel Iris."
            )
        elif llama_gpu:
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
        if preferred and sys.platform == "win32":
            note += (
                " При двух GPU (Iris+RTX) python.exe должен быть на "
                "«Высокая производительность» в Параметры → Дисплей → Графика."
            )
    return {
        "llama_gpu_offload": llama_gpu,
        "nvidia_detected": nvidia,
        "devices": devices,
        "preferred_device": preferred,
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
