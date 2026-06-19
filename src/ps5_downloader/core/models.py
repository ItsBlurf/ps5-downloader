from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from time import time
from typing import Any


class DownloadState(StrEnum):
    WAITING = "waiting"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    MANUAL_ACTION_REQUIRED = "manual-action-required"
    CANCELLED = "cancelled"


class PluginResultType(StrEnum):
    DIRECT_FILE = "direct-file"
    PACKAGE = "package"
    REDIRECT = "redirect"
    UNSUPPORTED = "unsupported"
    MANUAL_ACTION_REQUIRED = "manual-action-required"
    ERROR = "error"


@dataclass
class PluginInfo:
    name: str
    supported_domains: list[str]
    patterns: list[str]
    priority: int
    supports_metadata: bool = False
    supports_folders: bool = False


@dataclass
class PluginResult:
    type: PluginResultType
    original_url: str
    plugin: str
    resolved_url: str | None = None
    filename: str | None = None
    size: int | None = None
    checksum: str | None = None
    host: str | None = None
    children: list["PluginResult"] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = str(self.type)
        return data


@dataclass
class Settings:
    download_dir: str
    temp_dir: str
    max_concurrent_downloads: int = 2
    per_download_connections: int = 1
    speed_limit_bytes: int = 0
    user_agent: str = "ps5-downloader/0.1"
    conflict_behavior: str = "auto-rename"
    request_timeout: int = 20
    max_redirects: int = 8

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DownloadItem:
    id: str
    original_url: str
    resolved_url: str | None = None
    host: str | None = None
    filename: str | None = None
    size: int | None = None
    checksum: str | None = None
    state: DownloadState = DownloadState.WAITING
    downloaded_bytes: int = 0
    speed_bps: float = 0.0
    eta_seconds: float | None = None
    error: str | None = None
    plugin: str | None = None
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)

    @property
    def percent(self) -> float:
        if not self.size:
            return 0.0
        return min(100.0, (self.downloaded_bytes / self.size) * 100.0)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = str(self.state)
        data["percent"] = self.percent
        return data
