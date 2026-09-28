from __future__ import annotations

import base64
import sys
import threading
from datetime import datetime, timezone
from typing import Any

from zipka.config import Settings, ensure_data_dirs, get_settings


class Eyes:
    """Камера / экран / активное окно. Выключены по умолчанию.

    При `on()` веб-камера реально открывается (индикатор Windows загорается)
    и держится до `off()`. Снимки читают кадр из уже открытого устройства.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.enabled = False
        self.camera_index = 0
        self.snapshots_dir = self.settings.data_dir / "snapshots"
        self._cap: Any = None
        self._lock = threading.Lock()

    def on(self) -> str:
        with self._lock:
            if self.enabled and self._cap_is_open():
                return (
                    "Глаза уже включены, камера активна. "
                    "`eyes snap` — кадр, `eyes screen` — монитор, "
                    "`eyes window` — активное окно."
                )
            self._open_camera_locked()
            self.enabled = True
            return (
                "Глаза включены, камера активна. "
                "`eyes snap` — кадр с камеры, `eyes screen` — монитор, "
                "`eyes window` — активное окно."
            )

    def off(self) -> str:
        with self._lock:
            self.enabled = False
            self._close_camera_locked()
            return "Глаза выключены, камера освобождена."

    def snap(self) -> dict[str, Any]:
        """Кадр с веб-камеры."""
        self._require_on()
        with self._lock:
            if not self._cap_is_open():
                self._open_camera_locked()
            frame = self._read_frame_locked()
            return self._save_bgr(frame, prefix="eyes_cam")

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

    def _cap_is_open(self) -> bool:
        return self._cap is not None and bool(self._cap.isOpened())

    def _import_cv2(self):
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "opencv-python не установлен. pip install opencv-python"
            ) from exc
        return cv2

    def _open_camera_locked(self) -> None:
        cv2 = self._import_cv2()
        self._close_camera_locked()

        attempts: list[tuple[Any, ...]] = []
        if sys.platform == "win32":
            dshow = getattr(cv2, "CAP_DSHOW", None)
            msmf = getattr(cv2, "CAP_MSMF", None)
            if dshow is not None:
                attempts.append((self.camera_index, dshow))
            if msmf is not None:
                attempts.append((self.camera_index, msmf))
        attempts.append((self.camera_index,))

        for args in attempts:
            try:
                cap = cv2.VideoCapture(*args)
            except Exception:
                continue
            if cap is not None and cap.isOpened():
                # прогрев: первые кадры часто чёрные
                for _ in range(5):
                    cap.read()
                self._cap = cap
                return
            if cap is not None:
                cap.release()

        raise RuntimeError(
            "Не удалось открыть веб-камеру. "
            "Проверь, что она подключена и не занята другим приложением."
        )

    def _close_camera_locked(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _read_frame_locked(self):
        if not self._cap_is_open():
            raise RuntimeError("Камера не открыта.")
        # сбросить буфер — иначе часто приходит старый кадр
        ok, frame = False, None
        for _ in range(3):
            ok, frame = self._cap.read()
        if not ok or frame is None:
            # одна попытка переоткрыть
            self._open_camera_locked()
            ok, frame = self._cap.read()
            if not ok or frame is None:
                raise RuntimeError("Кадр с камеры не получен.")
        return frame

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

        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None

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
        cv2 = self._import_cv2()

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

        frame = np.asarray(shot)[:, :, :3].copy()
        return self._save_bgr(frame, prefix=prefix)

    def __del__(self) -> None:
        try:
            with self._lock:
                self._close_camera_locked()
        except Exception:
            pass
