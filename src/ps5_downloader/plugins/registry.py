from __future__ import annotations

from ps5_downloader.core.models import PluginResult, PluginResultType

from .base import BasePlugin
from .akirabox import AkiraBoxPlugin
from .buzzheavier import BuzzHeavierPlugin
from .direct_http import DirectHttpPlugin, RedirectResolverPlugin
from .generic_html import GenericHtmlPlugin
from .github import GitHubReleasePlugin
from .mediafire import MediaFirePlugin
from .onefichier import OneFichierPlugin
from .rootz import RootzPlugin


class PluginRegistry:
    def __init__(self, plugins: list[BasePlugin] | None = None) -> None:
        self.plugins = sorted(
            plugins
            or [
                MediaFirePlugin(),
                RootzPlugin(),
                AkiraBoxPlugin(),
                OneFichierPlugin(),
                BuzzHeavierPlugin(),
                GitHubReleasePlugin(),
                RedirectResolverPlugin(),
                DirectHttpPlugin(),
                GenericHtmlPlugin(),
            ],
            key=lambda plugin: plugin.priority,
            reverse=True,
        )

    def matching_plugins(self, url: str) -> list[BasePlugin]:
        return [plugin for plugin in self.plugins if plugin.matches(url)]

    def resolve(self, url: str) -> PluginResult:
        last_error: PluginResult | None = None
        for plugin in self.matching_plugins(url):
            result = plugin.resolve(url)
            if result.type in {
                PluginResultType.DIRECT_FILE,
                PluginResultType.PACKAGE,
                PluginResultType.REDIRECT,
                PluginResultType.MANUAL_ACTION_REQUIRED,
            }:
                return result
            if result.type == PluginResultType.ERROR:
                last_error = result
        return last_error or PluginResult(type=PluginResultType.UNSUPPORTED, original_url=url, plugin="registry")

    def list_plugins(self) -> list[dict]:
        return [plugin.info().__dict__ for plugin in self.plugins]
