from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path

from zipka.config import Settings, ensure_data_dirs, get_settings


class Eyes:
    """Веб-камера. Выключена по умолчанию."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.enabled = False
        self.camera_index = 0
        self.snapshots_dir = self.settings.data_dir / "snapshots"

    def on(self) -> str:
        self.enabled = True
        return "Глаза включены. Скажи `eyes snap`, чтобы я взглянула."

    def off(self) -> str:
        self.enabled = False
        return "Глаза выключены."

    def snap(self) -> dict:
        if not self.enabled:
            raise RuntimeError("Глаза выключены. Сначала `eyes on`.")
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "opencv-python не установлен. pip install opencv-python"
            ) from exc

        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            raise RuntimeError("Не удалось открыть веб-камеру.")
        try:
            ok, frame = cap.read()
            if not ok or frame is None:
                raise RuntimeError("Кадр с камеры не получен.")
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = self.snapshots_dir / f"eyes_{ts}.jpg"
            cv2.imwrite(str(path), frame)
            ok2, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok2:
                raise RuntimeError("Не удалось закодировать кадр.")
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            return {"path": str(path), "image_b64": b64}
        finally:
            cap.release()
