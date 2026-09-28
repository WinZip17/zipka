from __future__ import annotations

import base64
import sys
from datetime import datetime, timezone
from typing import Any

from zipka.config import Settings, ensure_data_dirs, get_settings


class Eyes:
    """Камера / экран / активное окно. Выключены по умолчанию."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.enabled = False
        self.camera_index = 0
        self.snapshots_dir = self.settings.data_dir / "snapshots"

    def on(self) -> str:
        self.enabled = True
        return (
            "Глаза включены. "
            "`eyes snap` — камера, `eyes screen` — монитор, "
            "`eyes window` — активное окно."
        )

    def off(self) -> str:
        self.enabled = False
        return "Глаза выключены."

    def snap(self) -> dict[str, Any]:
        """Кадр с веб-камеры."""
        self._require_on()
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
            return self._save_bgr(frame, prefix="eyes_cam")
        finally:
            cap.release()

    def screen(self, monitor: int = 1) -> dict[str, Any]:
        """Скриншот монитора (1 = основной, 0 = все виртуальные)."""
        self._require_on()
        sct = self._mss()
        with sct as s:
            monitors = s.monitors
            if monitor < 0 or monitor >= len(monitors):
                raise RuntimeError(
                    f"Монитор {monitor} недоступен. Есть 0..{len(monitors) - 1} "
                    "(0 = весь виртуальный рабочий стол)."
                )
            shot = s.grab(monitors[monitor])
            return self._save_mss(shot, prefix=f"eyes_screen{monitor}")

    def window(self) -> dict[str, Any]:
        """Скриншот активного (foreground) окна."""
        self._require_on()
        region = self._active_window_region()
        if not region:
            raise RuntimeError(
                "Не удалось определить активное окно. "
                "На Windows нужен доступ к WinAPI; попробуй `eyes screen`."
            )
        left, top, width, height = region
        if width < 2 or height < 2:
            raise RuntimeError("Активное окно слишком маленькое или свёрнуто.")
        sct = self._mss()
        with sct as s:
            shot = s.grab(
                {"left": left, "top": top, "width": width, "height": height}
            )
            return self._save_mss(shot, prefix="eyes_window")

    def _require_on(self) -> None:
        if not self.enabled:
            raise RuntimeError("Глаза выключены. Сначала `eyes on`.")

    @staticmethod
    def _mss():
        try:
            import mss
        except ImportError as exc:
            raise RuntimeError(
                "Для экрана нужен пакет mss: pip install mss"
            ) from exc
        return mss.mss()

    def _active_window_region(self) -> tuple[int, int, int, int] | None:
        if sys.platform != "win32":
            # Best-effort: primary monitor if no WinAPI
            return None
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None

        # Exclude minimized windows (GetWindowPlacement would be better;
        # negative huge coords often mean minimized)
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None

        # Clamp to virtual screen bounds via mss monitor 0
        try:
            with self._mss() as s:
                virt = s.monitors[0]
                vleft, vtop = virt["left"], virt["top"]
                vright = vleft + virt["width"]
                vbottom = vtop + virt["height"]
                left = max(left, vleft)
                top = max(top, vtop)
                right = min(right, vright)
                bottom = min(bottom, vbottom)
                width = right - left
                height = bottom - top
        except Exception:
            pass

        if width < 2 or height < 2:
            return None
        return left, top, width, height

    def _save_bgr(self, frame, *, prefix: str) -> dict[str, Any]:
        import cv2

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self.snapshots_dir / f"{prefix}_{ts}.jpg"
        cv2.imwrite(str(path), frame)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise RuntimeError("Не удалось закодировать кадр.")
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        return {"path": str(path), "image_b64": b64, "source": prefix}

    def _save_mss(self, shot, *, prefix: str) -> dict[str, Any]:
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("Нужен numpy") from exc

        # mss → BGRA ndarray; OpenCV expects BGR
        frame = np.asarray(shot)[:, :, :3].copy()
        return self._save_bgr(frame, prefix=prefix)
