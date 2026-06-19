from __future__ import annotations

import re
from abc import ABC, abstractmethod

from ps5_downloader.core.models import PluginInfo, PluginResult
from ps5_downloader.core.utils import host_from_url


class BasePlugin(ABC):
    name = "base"
    supported_domains: list[str] = []
    patterns: list[str] = []
    priority = 0
    supports_metadata = False
    supports_folders = False

    def info(self) -> PluginInfo:
        return PluginInfo(
            name=self.name,
            supported_domains=self.supported_domains,
            patterns=self.patterns,
            priority=self.priority,
            supports_metadata=self.supports_metadata,
            supports_folders=self.supports_folders,
        )

    def matches(self, url: str) -> bool:
        host = host_from_url(url)
        domain_match = any(host == domain or host.endswith(f".{domain}") for domain in self.supported_domains)
        pattern_match = any(re.search(pattern, url, re.IGNORECASE) for pattern in self.patterns)
        return domain_match or pattern_match

    @abstractmethod
    def resolve(self, url: str) -> PluginResult:
        raise NotImplementedError
