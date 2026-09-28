from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "my_qwen:latest"
    ollama_vision_model: str = ""
    zipka_data_dir: str = "data"
    zipka_reflect_every: int = 8
    zipka_net_allowlist: str = (
        "ru.wikipedia.org,en.wikipedia.org,docs.python.org,"
        "raw.githubusercontent.com,github.com"
    )
    zipka_net_max_bytes: int = 500_000
    zipka_whisper_model: str = "base"

    @property
    def data_dir(self) -> Path:
        path = Path(self.zipka_data_dir)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path

    @property
    def package_dir(self) -> Path:
        return Path(__file__).resolve().parent

    @property
    def web_dir(self) -> Path:
        return ROOT_DIR / "web"

    @property
    def net_allowlist(self) -> list[str]:
        return [x.strip() for x in self.zipka_net_allowlist.split(",") if x.strip()]

    @property
    def vision_model(self) -> str:
        return self.ollama_vision_model or self.ollama_model


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_data_dirs(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    base = settings.data_dir
    for sub in (
        "persona",
        "memory",
        "books",
        "books/notes",
        "snapshots",
        "patches",
        "mind",
    ):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base
