"""Скачать чатовые GGUF: Pathfinder + Qwen2.5-7B-Instruct Q5_K_M."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from zipka.config import ensure_data_dirs, get_settings
from zipka.llm.chat_models import CHAT_PROFILES, find_profile_file, list_chat_profiles


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
            # hf кладёт файл рядом; переименуем если нужно
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
    print(f">> curl download …")
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dest)
    return True


def download_profile(profile_id: str, *, force: bool = False) -> Path:
    profile = CHAT_PROFILES.get(profile_id)
    if not profile:
        raise SystemExit(f"Неизвестный профиль: {profile_id}. Есть: {', '.join(CHAT_PROFILES)}")

    settings = get_settings()
    ensure_data_dirs(settings)
    models_dir = settings.data_dir / "models"
    existing = find_profile_file(models_dir, profile)
    dest = models_dir / str(profile["filename"])
    if existing and not force:
        print(f"OK already present: {existing}")
        return existing

    print(f"Downloading {profile['label']} (~{profile.get('size_hint_gb')} GB)...")
    if _download_hf(str(profile["hf_repo"]), str(profile["hf_file"]), dest):
        print(f"OK {dest}")
        return dest
    if _download_curl(str(profile["url"]), dest):
        print(f"OK {dest}")
        return dest
    try:
        _download_urllib(str(profile["url"]), dest)
        print(f"OK {dest}")
        return dest
    except Exception as exc:
        raise SystemExit(
            f"Failed to download {profile_id}: {exc}\n"
            f"Manual URL:\n  {profile['url']}\n"
            f"Put file into {models_dir}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Скачать чатовые GGUF Зипки (Pathfinder + Qwen2.5)"
    )
    parser.add_argument(
        "--id",
        choices=["pathfinder", "qwen25", "all"],
        default="all",
        help="Какой профиль скачать (по умолчанию оба)",
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
        for p in list_chat_profiles():
            found = find_profile_file(models_dir, p)
            mark = "+" if found else "-"
            print(f"{mark} {p['id']:12} {p['label']}")
            print(f"    file: {p['filename']}")
            print(f"    path: {found or '(missing)'}")
            print(f"    url:  {p['url']}")
        return 0

    ids = ["pathfinder", "qwen25"] if args.id == "all" else [args.id]
    for mid in ids:
        download_profile(mid, force=args.force)
    print("Done. UI: Settings -> chat model -> Pathfinder / Qwen2.5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
