from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np

from zipka.config import Settings, get_settings

_log = logging.getLogger("zipka.ears")

_SAMPLE_RATE = 16000
_MAX_RECORD_SEC = 60.0
_MIN_RECORD_SEC = 0.25
_TRIM_PAD_SEC = 0.12
_SILENCE_RMS = 0.008
_PEAK_TARGET = 0.9
_WHISPER_SIZES = ("tiny", "base", "small", "medium", "large-v3")
_INITIAL_PROMPT = (
    "Разговорный русский. Имена: Зипка, Юра, WinZip. "
    "Локальный ИИ, код, книги, новости."
)


def normalize_whisper_model(raw: str | None, *, default: str = "small") -> str:
    name = str(raw or "").strip().lower()
    if name in _WHISPER_SIZES:
        return name
    # aliases
    if name in {"large", "large-v2"}:
        return "large-v3"
    return default if default in _WHISPER_SIZES else "small"


def resolve_whisper_device() -> tuple[str, str]:
    """(device, compute_type): CUDA float16 или CPU int8."""
    try:
        import ctranslate2

        types = {
            str(x).lower()
            for x in ctranslate2.get_supported_compute_types("cuda")
        }
        if types:
            if "float16" in types:
                return "cuda", "float16"
            if "int8_float16" in types:
                return "cuda", "int8_float16"
            return "cuda", sorted(types)[0]
    except Exception:
        pass
    try:
        from zipka.torch_compat import quiet_torch_noise

        quiet_torch_noise()
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def preprocess_audio(
    audio: np.ndarray,
    *,
    sample_rate: int = _SAMPLE_RATE,
) -> np.ndarray:
    """Trim тишины по краям, затем peak-normalize (~0.9)."""
    mono = np.asarray(audio, dtype=np.float32).reshape(-1)
    if mono.size == 0:
        return mono
    # trim до DC: иначе вычитание среднего поднимает «тишину» над порогом
    win = max(1, int(sample_rate * 0.02))
    pad = int(sample_rate * _TRIM_PAD_SEC)
    n = mono.size
    if n >= win * 2:

        def _rms_at(i: int) -> float:
            chunk = mono[i : i + win]
            return float(np.sqrt(np.mean(chunk * chunk))) if chunk.size else 0.0

        start = 0
        while start + win <= n and _rms_at(start) < _SILENCE_RMS:
            start += win
        end = n
        while end - win >= start and _rms_at(end - win) < _SILENCE_RMS:
            end -= win
        start = max(0, start - pad)
        end = min(n, end + pad)
        if end > start:
            mono = mono[start:end]
    if mono.size == 0:
        return mono.astype(np.float32, copy=False)
    mono = mono - float(np.mean(mono))
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if peak > 1e-6:
        mono = mono * (_PEAK_TARGET / peak)
    return mono.astype(np.float32, copy=False)


class Ears:
    """Микрофон + локальный STT. Выключены по умолчанию.

    Push-to-talk: listen_start() → … → listen_stop() → текст.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.enabled = False
        self._model: Any = None
        self._model_key: tuple[str, str, str] | None = None
        self._lock = threading.Lock()
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._stream: Any = None
        self._started_at = 0.0
        self._max_timer: threading.Timer | None = None
        self._pending_audio: np.ndarray | None = None

    def on(self) -> str:
        self.enabled = True
        return (
            "Уши включены. Зажми микрофон в чате, говори, отпусти — распознаю."
        )

    def off(self) -> str:
        with self._lock:
            if self._recording:
                self._stop_stream_unlocked()
            self._pending_audio = None
        self.enabled = False
        return "Уши выключены."

    def unload_model(self) -> None:
        """Сбросить кэш Whisper (после смены размера в настройках)."""
        with self._lock:
            self._model = None
            self._model_key = None

    def status_info(self) -> dict[str, Any]:
        from zipka.runtime_settings import resolve_whisper_model

        model = resolve_whisper_model(self.settings)
        device, ctype = resolve_whisper_device()
        return {
            "model": model,
            "device": device,
            "compute_type": ctype,
            "loaded": self._model is not None,
            "options": list(_WHISPER_SIZES),
        }

    @property
    def is_recording(self) -> bool:
        return self._recording

    def listen_start(self) -> str:
        if not self.enabled:
            raise RuntimeError("Уши выключены. Сначала включи «Уши».")
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice не установлен.") from exc

        with self._lock:
            if self._recording:
                raise RuntimeError("Уже идёт запись. Отпусти микрофон.")
            self._chunks = []
            self._pending_audio = None
            self._started_at = time.monotonic()

            def _callback(indata, frames, time_info, status) -> None:  # noqa: ARG001
                if self._recording:
                    self._chunks.append(np.array(indata, copy=True))

            stream = sd.InputStream(
                samplerate=_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                callback=_callback,
            )
            stream.start()
            self._stream = stream
            self._recording = True

            if self._max_timer is not None:
                self._max_timer.cancel()
            self._max_timer = threading.Timer(_MAX_RECORD_SEC, self._auto_stop_max)
            self._max_timer.daemon = True
            self._max_timer.start()

        return "Запись…"

    def _auto_stop_max(self) -> None:
        with self._lock:
            if self._recording:
                self._stop_stream_unlocked()

    def _stop_stream_unlocked(self) -> np.ndarray:
        """Остановить поток и вернуть mono float32. Вызывать под _lock."""
        self._recording = False
        if self._max_timer is not None:
            self._max_timer.cancel()
            self._max_timer = None
        stream = self._stream
        self._stream = None
        chunks = list(self._chunks)
        self._chunks = []
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if not chunks:
            mono = np.zeros(0, dtype=np.float32)
        else:
            mono = np.squeeze(np.concatenate(chunks, axis=0)).astype(
                np.float32, copy=False
            )
        self._pending_audio = mono
        return mono

    def listen_stop(self) -> str:
        if not self.enabled:
            raise RuntimeError("Уши выключены.")
        with self._lock:
            if self._recording:
                elapsed = time.monotonic() - self._started_at
                mono = self._stop_stream_unlocked()
            elif self._pending_audio is not None:
                mono = self._pending_audio
                self._pending_audio = None
                elapsed = max(_MIN_RECORD_SEC, mono.size / float(_SAMPLE_RATE))
            else:
                raise RuntimeError("Запись не шла. Зажми микрофон и говори.")
            self._pending_audio = None

        if elapsed < _MIN_RECORD_SEC or mono.size < int(
            _SAMPLE_RATE * _MIN_RECORD_SEC
        ):
            return "(слишком коротко)"
        return self._transcribe(mono, _SAMPLE_RATE)

    def listen(self, seconds: float = 5.0) -> str:
        """Совместимость CLI: фиксированная длительность."""
        if not self.enabled:
            raise RuntimeError("Уши выключены. Сначала `ears on`.")
        sec = max(_MIN_RECORD_SEC, min(float(seconds), _MAX_RECORD_SEC))
        self.listen_start()
        try:
            time.sleep(sec)
            return self.listen_stop()
        except Exception:
            with self._lock:
                if self._recording:
                    self._stop_stream_unlocked()
                self._pending_audio = None
            raise

    def _transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        prepared = preprocess_audio(audio, sample_rate=sample_rate)
        if prepared.size < int(sample_rate * _MIN_RECORD_SEC):
            return "(тишина)"
        rms = float(np.sqrt(np.mean(prepared * prepared))) if prepared.size else 0.0
        if rms < _SILENCE_RMS * 0.5:
            return "(тишина)"

        from zipka.ai_activity import announce_ai
        from zipka.runtime_settings import resolve_whisper_model

        announce_ai(
            "уши STT",
            resolve_whisper_model(self.settings),
            f"sec={prepared.size / float(sample_rate):.1f}",
        )
        model = self._get_model()
        announce_ai("инференс Whisper", resolve_whisper_model(self.settings))
        segments, _info = model.transcribe(
            prepared,
            language="ru",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=_INITIAL_PROMPT,
            without_timestamps=True,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text or "(тишина)"

    def _get_model(self) -> Any:
        from zipka.runtime_settings import resolve_whisper_model

        name = resolve_whisper_model(self.settings)
        device, ctype = resolve_whisper_device()
        key = (name, device, ctype)
        if self._model is not None and self._model_key == key:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper не установлен. pip install faster-whisper"
            ) from exc
        from zipka.ai_activity import announce_ai

        announce_ai("загрузка Whisper", name, f"device={device}", f"compute={ctype}")
        try:
            self._model = WhisperModel(name, device=device, compute_type=ctype)
            self._model_key = key
            _log.info("Whisper loaded: %s device=%s compute=%s", name, device, ctype)
        except Exception as exc:
            if device != "cpu":
                _log.warning(
                    "Whisper CUDA failed (%s), fallback CPU int8", exc
                )
                self._model = WhisperModel(
                    name, device="cpu", compute_type="int8"
                )
                self._model_key = (name, "cpu", "int8")
            else:
                raise
        return self._model
