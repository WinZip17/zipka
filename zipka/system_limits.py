from __future__ import annotations

import os
import sys
from functools import lru_cache


def available_ram_bytes() -> int | None:
    """Свободная (доступная) оперативная память в байтах."""
    if sys.platform.startswith("linux"):
        value = _linux_mem_available()
        if value is not None:
            return value

    if sys.platform == "win32":
        value = _windows_avail_phys()
        if value is not None:
            return value

    if sys.platform == "darwin":
        value = _darwin_mem_estimate()
        if value is not None:
            return value

    return None


def _linux_mem_available() -> int | None:
    path = "/proc/meminfo"
    if not os.path.exists(path):
        return None
    data: dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2 and parts[0].endswith(":"):
                key = parts[0][:-1]
                try:
                    data[key] = int(parts[1]) * 1024  # kB → bytes
                except ValueError:
                    continue
    if "MemAvailable" in data:
        return data["MemAvailable"]
    if "MemFree" in data and "Buffers" in data and "Cached" in data:
        return data["MemFree"] + data["Buffers"] + data["Cached"]
    return data.get("MemFree")


def _windows_avail_phys() -> int | None:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
        return int(stat.ullAvailPhys)
    except Exception:
        return None


def _darwin_mem_estimate() -> int | None:
    """Грубая оценка: ~40% от hw.memsize (без mach API)."""
    try:
        import ctypes
        import ctypes.util

        libc_name = ctypes.util.find_library("c")
        if not libc_name:
            return None
        libc = ctypes.CDLL(libc_name, use_errno=True)
        size = ctypes.c_uint64(0)
        length = ctypes.c_size_t(ctypes.sizeof(size))
        name = b"hw.memsize"
        if (
            libc.sysctlbyname(name, ctypes.byref(size), ctypes.byref(length), None, 0)
            != 0
        ):
            return None
        return max(1, int(size.value * 0.4))
    except Exception:
        return None


@lru_cache
def max_book_bytes(
    *,
    fraction: float = 0.12,
    minimum: int = 32 * 1024 * 1024,
    maximum: int = 512 * 1024 * 1024,
    fallback: int = 80 * 1024 * 1024,
) -> int:
    """Лимит размера книги/архива исходя из доступной RAM.

    Доля свободной памяти, зажатая в [minimum, maximum].
    Переопределение: ZIPKA_MAX_BOOK_BYTES (байты).
    """
    override = os.environ.get("ZIPKA_MAX_BOOK_BYTES", "").strip()
    if override.isdigit():
        return max(1, int(override))

    avail = available_ram_bytes()
    if avail is None or avail <= 0:
        return fallback
    proposed = int(avail * fraction)
    return max(minimum, min(proposed, maximum))


def format_bytes(n: int) -> str:
    if n >= 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024 * 1024):.1f} ГБ"
    return f"{n / (1024 * 1024):.0f} МБ"
