"""Скачать чатовые / vision GGUF для Зипки."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from zipka.config import ensure_data_dirs, get_settings
from zipka.llm.chat_models import CHAT_PROFILES, find_profile_file, list_chat_profiles
from zipka.llm.vision import VISION_PROFILES


def _download_urllib(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    print(f">> {url}")
    print(f"   -> {dest}")

    def _reporthook(block: int, block_size: int, total: int) -> None:
        if total <= 0:
            return
        done = min(block * block_size, total)
        pct = done * 100 // total
        mb = done / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        print(f"\r  {pct:3d}%  {mb:.1f}/{total_mb:.1f} MiB", end="", flush=True)

    try:
        urllib.request.urlretrieve(url, tmp, reporthook=_reporthook)
        print()
        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _download_hf(repo: str, filename: str, dest: Path) -> bool:
    """Попробовать huggingface-cli / hf."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for cmd in (
        ["huggingface-cli", "download", repo, filename, "--local-dir", str(dest.parent)],
        ["hf", "download", repo, filename, "--local-dir", str(dest.parent)],
    ):
        if not shutil.which(cmd[0]):
            continue
        print(f">> {' '.join(cmd)}")
        proc = subprocess.run(cmd, check=False)
        if proc.returncode == 0:
            got = dest.parent / filename
            if got.is_file() and got.resolve() != dest.resolve():
                got.replace(dest)
            return dest.is_file()
    return False


def _download_curl(url: str, dest: Path) -> bool:
    curl = shutil.which("curl")
    if not curl:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    cmd = [
        curl,
        "-L",
        "--fail",
        "--retry",
        "3",
        "--ssl-no-revoke",
        "-o",
        str(tmp),
        url,
    ]
    print(">> curl download …")
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dest)
    return True


def _fetch_file(url: str, dest: Path, *, repo: str | None, hf_file: str | None) -> Path:
    if dest.is_file():
        return dest
    if repo and hf_file and _download_hf(repo, hf_file, dest):
        return dest
    if _download_curl(url, dest):
        return dest
    _download_urllib(url, dest)
    return dest


def download_profile(profile_id: str, *, force: bool = False) -> Path:
    if profile_id in VISION_PROFILES:
        return download_vision_profile(profile_id, force=force)

    profile = CHAT_PROFILES.get(profile_id)
    if not profile:
        known = ", ".join([*CHAT_PROFILES, *VISION_PROFILES])
        raise SystemExit(f"Неизвестный профиль: {profile_id}. Есть: {known}")

    settings = get_settings()
    ensure_data_dirs(settings)
    models_dir = settings.data_dir / "models"
    existing = find_profile_file(models_dir, profile)
    dest = models_dir / str(profile["filename"])
    if existing and not force:
        print(f"OK already present: {existing}")
        return existing

    print(f"Downloading {profile['label']} (~{profile.get('size_hint_gb')} GB)...")
    try:
        _fetch_file(
            str(profile["url"]),
            dest,
            repo=str(profile.get("hf_repo") or ""),
            hf_file=str(profile.get("hf_file") or ""),
        )
    except Exception as exc:
        raise SystemExit(
            f"Failed to download {profile_id}: {exc}\n"
            f"Manual URL:\n  {profile['url']}\n"
            f"Put file into {models_dir}"
        ) from exc
    print(f"OK {dest}")
    return dest


def download_vision_profile(profile_id: str, *, force: bool = False) -> Path:
    profile = VISION_PROFILES[profile_id]
    settings = get_settings()
    ensure_data_dirs(settings)
    models_dir = settings.data_dir / "models"
    text_dest = models_dir / str(profile["filename"])
    mm_dest = models_dir / str(profile["mmproj"])

    if text_dest.is_file() and mm_dest.is_file() and not force:
        print(f"OK already present: {text_dest}")
        print(f"OK already present: {mm_dest}")
        return text_dest

    print(f"Downloading {profile['label']} (~{profile.get('size_hint_gb')} GB)...")
    try:
        if force or not text_dest.is_file():
            _fetch_file(
                str(profile["url"]),
                text_dest,
                repo=str(profile.get("hf_repo") or ""),
                hf_file=str(profile.get("hf_file") or ""),
            )
            print(f"OK {text_dest}")
        else:
            print(f"OK already present: {text_dest}")
        if force or not mm_dest.is_file():
            _fetch_file(
                str(profile["url_mmproj"]),
                mm_dest,
                repo=str(profile.get("hf_repo") or ""),
                hf_file=str(profile.get("hf_mmproj") or ""),
            )
            print(f"OK {mm_dest}")
        else:
            print(f"OK already present: {mm_dest}")
    except Exception as exc:
        raise SystemExit(
            f"Failed to download vision {profile_id}: {exc}\n"
            f"Need both:\n  {profile['url']}\n  {profile['url_mmproj']}\n"
            f"Put into {models_dir}"
        ) from exc
    return text_dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Скачать GGUF Зипки (чат Pathfinder/Qwen + vision Moondream)"
    )
    parser.add_argument(
        "--id",
        choices=["pathfinder", "qwen25", "moondream2", "all", "vision"],
        default="all",
        help="Какой профиль скачать",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перекачать, даже если файл уже есть",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показать профили и наличие файлов",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    ensure_data_dirs(settings)
    models_dir = settings.data_dir / "models"

    if args.list:
        print("=== chat ===")
        for p in list_chat_profiles():
            found = find_profile_file(models_dir, p)
            mark = "+" if found else "-"
            print(f"{mark} {p['id']:12} {p['label']}")
            print(f"    file: {p['filename']}")
            print(f"    path: {found or '(missing)'}")
        print("=== vision ===")
        for p in VISION_PROFILES.values():
            text = models_dir / str(p["filename"])
            mm = models_dir / str(p["mmproj"])
            mark = "+" if text.is_file() and mm.is_file() else "-"
            print(f"{mark} {p['id']:12} {p['label']}")
            print(f"    model:  {text if text.is_file() else '(missing)'}")
            print(f"    mmproj: {mm if mm.is_file() else '(missing)'}")
        return 0

    if args.id == "all":
        ids = ["pathfinder", "qwen25"]
    elif args.id == "vision":
        ids = ["moondream2"]
    else:
        ids = [args.id]
    for mid in ids:
        download_profile(mid, force=args.force)
    print("Done. Vision: models download --id moondream2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
