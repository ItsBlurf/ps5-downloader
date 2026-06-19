from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Settings
from .utils import validate_directory_path


def default_home() -> Path:
    override = os.environ.get("PS5_DOWNLOADER_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "ps5-downloader"
    return Path.home() / "Downloads" / "ps5-downloader"


def default_settings(home: Path | None = None) -> Settings:
    root = (home or default_home()).expanduser()
    return Settings(
        download_dir=str(root / "downloads"),
        temp_dir=str(root / "tmp"),
    )


class SettingsStore:
    def __init__(self, home: Path | None = None) -> None:
        self.home = (home or default_home()).expanduser()
        self.path = self.home / "settings.json"
        self.home.mkdir(parents=True, exist_ok=True)

    def load(self) -> Settings:
        settings = default_settings(self.home)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for key, value in data.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
        self._validate(settings)
        return settings

    def save(self, settings: Settings) -> Settings:
        self._validate(settings)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return settings

    def update(self, data: dict) -> Settings:
        settings = self.load()
        for key, value in data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        return self.save(settings)

    @staticmethod
    def _validate(settings: Settings) -> None:
        if settings.max_concurrent_downloads < 1:
            raise ValueError("max_concurrent_downloads must be at least 1")
        if settings.per_download_connections < 1:
            raise ValueError("per_download_connections must be at least 1")
        if settings.conflict_behavior not in {"auto-rename", "overwrite", "skip"}:
            raise ValueError("conflict_behavior must be auto-rename, overwrite, or skip")
        validate_directory_path(settings.download_dir)
        validate_directory_path(settings.temp_dir)
