from __future__ import annotations

from typing import Any

import numpy as np

from zipka.config import Settings, get_settings


class Ears:
    """Микрофон + локальный STT. Выключены по умолчанию."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.enabled = False
        self._model: Any = None

    def on(self) -> str:
        self.enabled = True
        return "Уши включены. Скажи `ears listen`, чтобы я послушала."

    def off(self) -> str:
        self.enabled = False
        return "Уши выключены."

    def listen(self, seconds: float = 5.0) -> str:
        if not self.enabled:
            raise RuntimeError("Уши выключены. Сначала `ears on`.")
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice не установлен.") from exc

        sample_rate = 16000
        frames = int(seconds * sample_rate)
        audio = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="float32")
        sd.wait()
        mono = np.squeeze(audio)
        return self._transcribe(mono, sample_rate)

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
