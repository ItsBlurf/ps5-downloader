from __future__ import annotations

import html
import re
from urllib.request import Request, urlopen

from ps5_downloader.core.models import PluginResult, PluginResultType
from ps5_downloader.core.utils import host_from_url, sanitize_filename

from .akirabox import parse_size_text
from .base import BasePlugin


def parse_1fichier_file_info(body: str) -> tuple[str | None, int | None]:
    name_match = re.search(r'<span[^>]*font-weight\s*:\s*bold[^>]*>\s*([^<]+?)\s*</span>', body, re.I)
    size_match = re.search(r'<span[^>]*font-size\s*:\s*0\.9em[^>]*>\s*([^<]+?)\s*</span>', body, re.I)
    filename = sanitize_filename(html.unescape(name_match.group(1))) if name_match else None
    size = parse_size_text(html.unescape(size_match.group(1))) if size_match else None
    return filename, size


def parse_1fichier_wait_seconds(body: str) -> int | None:
    match = re.search(r"\bct\s*=\s*(\d+)\s*;", body)
    return int(match.group(1)) if match else None


class OneFichierPlugin(BasePlugin):
    name = "1fichier-public"
    supported_domains = ["1fichier.com", "www.1fichier.com"]
    patterns = [r"1fichier\.com/\?[A-Za-z0-9_-]+"]
    priority = 87
    supports_metadata = True

    def resolve(self, url: str) -> PluginResult:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as response:
                body = response.read(512_000).decode("utf-8", errors="replace")
        except Exception as exc:
            return PluginResult(type=PluginResultType.ERROR, original_url=url, plugin=self.name, message=str(exc))

        filename, size = parse_1fichier_file_info(body)
        wait_seconds = parse_1fichier_wait_seconds(body)
        if "name=\"dl_no_ssl\"" in body and wait_seconds is not None:
            return PluginResult(
                type=PluginResultType.MANUAL_ACTION_REQUIRED,
                original_url=url,
                filename=filename,
                size=size,
                host=host_from_url(url),
                plugin=self.name,
                message=(
                    f"1fichier free downloads require a timed interactive flow "
                    f"({wait_seconds}s wait, possible captcha/IP/account limits)."
                ),
            )
        if "password" in body.lower():
            return PluginResult(
                type=PluginResultType.MANUAL_ACTION_REQUIRED,
                original_url=url,
                filename=filename,
                size=size,
                host=host_from_url(url),
                plugin=self.name,
                message="1fichier file requires manual browser action.",
            )
        return PluginResult(
            type=PluginResultType.MANUAL_ACTION_REQUIRED,
            original_url=url,
            filename=filename,
            size=size,
            host=host_from_url(url),
            plugin=self.name,
            message="1fichier did not expose a direct public download URL.",
        )
