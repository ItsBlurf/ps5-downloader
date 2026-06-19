from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ps5_downloader.core.models import PluginResult, PluginResultType
from ps5_downloader.core.utils import host_from_url

from .base import BasePlugin


def parse_size_text(value: str | int | float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    parts = str(value).strip().replace(",", ".").split()
    if not parts:
        return None
    try:
        amount = float(parts[0])
    except ValueError:
        return None
    unit = parts[1].lower() if len(parts) > 1 else "b"
    multipliers = {
        "b": 1,
        "byte": 1,
        "bytes": 1,
        "kb": 1024,
        "kib": 1024,
        "mb": 1024**2,
        "mib": 1024**2,
        "gb": 1024**3,
        "gib": 1024**3,
        "tb": 1024**4,
        "tib": 1024**4,
    }
    return int(amount * multipliers.get(unit, 1))


class AkiraBoxPlugin(BasePlugin):
    name = "akirabox-public"
    supported_domains = ["akirabox.com", "www.akirabox.com", "akirabox.to", "www.akirabox.to"]
    patterns = [r"akirabox\.(?:com|to)/[A-Za-z0-9_-]+/file"]
    priority = 88
    supports_metadata = True

    def resolve(self, url: str) -> PluginResult:
        api_url = "https://akirabox.com/api/files?" + urlencode({"url": url})
        try:
            req = Request(api_url, headers={"User-Agent": "ps5-downloader/0.1", "Accept": "application/json"})
            with urlopen(req, timeout=15) as response:
                data = json.loads(response.read(200_000).decode("utf-8", errors="replace"))
        except Exception as exc:
            return PluginResult(type=PluginResultType.ERROR, original_url=url, plugin=self.name, message=str(exc))

        if int(data.get("status", 0) or 0) != 200:
            return PluginResult(
                type=PluginResultType.MANUAL_ACTION_REQUIRED,
                original_url=url,
                plugin=self.name,
                host=host_from_url(url),
                message=str(data.get("message") or "AkiraBox did not report a public file."),
            )

        filename = data.get("name") or None
        resolved_url = data.get("url") or url
        return PluginResult(
            type=PluginResultType.DIRECT_FILE,
            original_url=url,
            resolved_url=resolved_url,
            filename=filename,
            size=parse_size_text(data.get("size")),
            host=host_from_url(resolved_url),
            plugin=self.name,
        )
