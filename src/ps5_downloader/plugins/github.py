from __future__ import annotations

from ps5_downloader.core.models import PluginResult, PluginResultType
from ps5_downloader.core.utils import filename_from_url, host_from_url

from .base import BasePlugin


class GitHubReleasePlugin(BasePlugin):
    name = "github-release-asset"
    supported_domains = ["github.com"]
    patterns = [r"github\.com/.+/.+/releases/download/"]
    priority = 80
    supports_metadata = True

    def resolve(self, url: str) -> PluginResult:
        return PluginResult(
            type=PluginResultType.DIRECT_FILE,
            original_url=url,
            resolved_url=url,
            filename=filename_from_url(url),
            host=host_from_url(url),
            plugin=self.name,
        )
