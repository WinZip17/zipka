from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from zipka.config import Settings, get_settings

_SAMPLE_RATE = 16000
_MAX_RECORD_SEC = 60.0
_MIN_RECORD_SEC = 0.25


class Ears:
    """Микрофон + локальный STT. Выключены по умолчанию.

    Push-to-talk: listen_start() → … → listen_stop() → текст.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.enabled = False
        self._model: Any = None
        self._lock = threading.Lock()
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._stream: Any = None
        self._started_at = 0.0
        self._max_timer: threading.Timer | None = None
        self._pending_audio: np.ndarray | None = None

    def on(self) -> str:
        self.enabled = True
        return "Уши включены. Зажми «Слушать», говори, отпусти — распознаю."

    def off(self) -> str:
        with self._lock:
            if self._recording:
                self._stop_stream_unlocked()
            self._pending_audio = None
        self.enabled = False
        return "Уши выключены."

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
                raise RuntimeError("Уже идёт запись. Отпусти «Слушать».")
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
                raise RuntimeError("Запись не шла. Зажми «Слушать» и говори.")
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
        model = self._get_model()
        segments, _info = model.transcribe(audio, language="ru")
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text or "(тишина)"

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper не установлен. pip install faster-whisper"
                ) from exc
            self._model = WhisperModel(
                self.settings.zipka_whisper_model, device="cpu", compute_type="int8"
            )
        return self._model
