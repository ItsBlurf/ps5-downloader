from __future__ import annotations

import re
from html import unescape
from urllib.request import Request, urlopen

from ps5_downloader.core.models import PluginResult, PluginResultType
from ps5_downloader.core.utils import filename_from_url, host_from_url

from .base import BasePlugin

DOWNLOAD_RE = re.compile(
    r"""href=["'](?P<url>https?://download[^"']+mediafire\.com/[^"']+)["']""",
    re.IGNORECASE,
)


def parse_mediafire_public_html(html: str) -> str | None:
    match = DOWNLOAD_RE.search(html)
    if not match:
        return None
    return unescape(match.group("url"))


class MediaFirePlugin(BasePlugin):
    name = "mediafire-public"
    supported_domains = ["mediafire.com"]
    patterns = [r"mediafire\.com/(file|download)/"]
    priority = 100
    supports_metadata = True

    def resolve(self, url: str) -> PluginResult:
        try:
            req = Request(url, headers={"User-Agent": "ps5-downloader/0.1"})
            with urlopen(req, timeout=12) as response:
                html = response.read(800_000).decode("utf-8", errors="replace")
        except Exception as exc:
            return PluginResult(type=PluginResultType.ERROR, original_url=url, plugin=self.name, message=str(exc))

        direct_url = parse_mediafire_public_html(html)
        if not direct_url:
            return PluginResult(
                type=PluginResultType.MANUAL_ACTION_REQUIRED,
                original_url=url,
                plugin=self.name,
                host=host_from_url(url),
                message="No public direct MediaFire download link found; login/captcha/anti-abuse flow may be required.",
            )
        return PluginResult(
            type=PluginResultType.DIRECT_FILE,
            original_url=url,
            resolved_url=direct_url,
            filename=filename_from_url(direct_url),
            host=host_from_url(url),
            plugin=self.name,
        )
