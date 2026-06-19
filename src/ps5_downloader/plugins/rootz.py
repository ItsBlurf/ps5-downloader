from __future__ import annotations

import html
import json
import re
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from ps5_downloader.core.models import PluginResult, PluginResultType
from ps5_downloader.core.utils import host_from_url, sanitize_filename

from .base import BasePlugin


def parse_rootz_short_id(url: str) -> str | None:
    match = re.search(r"/d/([A-Za-z0-9_-]+)", urlsplit(url).path)
    return match.group(1) if match else None


def parse_rootz_page_token(body: str) -> str | None:
    patterns = [
        r'pageToken\\?["\']\s*:\s*\\?["\']([^"\'\\]+)',
        r'pageToken&quot;\s*:\s*&quot;([^&]+)&quot;',
    ]
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            return html.unescape(match.group(1))
    return None


def parse_rootz_title(body: str) -> str | None:
    match = re.search(r"<title>\s*([^<]+?)\s*</title>", body, re.IGNORECASE)
    if not match:
        return None
    title = html.unescape(match.group(1)).strip()
    if not title or title.lower() in {"rootz", "rootz.so"}:
        return None
    return sanitize_filename(title)


class RootzPlugin(BasePlugin):
    name = "rootz-public"
    supported_domains = ["rootz.so", "www.rootz.so"]
    patterns = [r"rootz\.so/d/[A-Za-z0-9_-]+"]
    priority = 89
    supports_metadata = True

    def resolve(self, url: str) -> PluginResult:
        short_id = parse_rootz_short_id(url)
        if not short_id:
            return PluginResult(type=PluginResultType.UNSUPPORTED, original_url=url, plugin=self.name)

        page_body = ""
        filename = None
        page_token = None
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as response:
                page_body = response.read(512_000).decode("utf-8", errors="replace")
            filename = parse_rootz_title(page_body)
            page_token = parse_rootz_page_token(page_body)
        except Exception:
            # The proxy endpoint can still work for simple public files; keep the resolver useful.
            pass

        api_result = self._resolve_metadata(url, short_id, page_token)
        if api_result:
            if not api_result.filename:
                api_result.filename = filename
            return api_result

        resolved_url = f"https://www.rootz.so/api/files/proxy-download/{quote(short_id, safe='')}"
        return PluginResult(
            type=PluginResultType.DIRECT_FILE,
            original_url=url,
            resolved_url=resolved_url,
            filename=filename,
            host=host_from_url(resolved_url),
            plugin=self.name,
        )

    def _resolve_metadata(self, original_url: str, short_id: str, page_token: str | None) -> PluginResult | None:
        if not page_token:
            return None
        api_url = f"https://www.rootz.so/api/files/download-by-short?shortId={quote(short_id, safe='')}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "X-Page-Token": page_token,
        }
        try:
            req = Request(api_url, headers=headers)
            with urlopen(req, timeout=15) as response:
                data = json.loads(response.read(200_000).decode("utf-8", errors="replace"))
        except Exception:
            return None

        if not data.get("success"):
            return PluginResult(
                type=PluginResultType.MANUAL_ACTION_REQUIRED,
                original_url=original_url,
                plugin=self.name,
                host=host_from_url(original_url),
                message=str(data.get("error") or "Rootz did not allow this public download."),
            )

        file_data = data.get("data") or {}
        if file_data.get("passwordProtected"):
            return PluginResult(
                type=PluginResultType.MANUAL_ACTION_REQUIRED,
                original_url=original_url,
                plugin=self.name,
                host=host_from_url(original_url),
                message="Rootz file is password protected.",
            )
        if file_data.get("downloadAllowed") is False:
            return PluginResult(
                type=PluginResultType.MANUAL_ACTION_REQUIRED,
                original_url=original_url,
                plugin=self.name,
                host=host_from_url(original_url),
                message="Rootz temporarily did not allow this download.",
            )
        if str(file_data.get("status") or "").lower() == "deleted":
            return PluginResult(
                type=PluginResultType.MANUAL_ACTION_REQUIRED,
                original_url=original_url,
                plugin=self.name,
                host=host_from_url(original_url),
                message="Rootz file is deleted.",
            )

        file_id = str(file_data.get("fileId") or short_id)
        resolved_url = f"https://www.rootz.so/api/files/proxy-download/{quote(file_id, safe='')}"
        size = file_data.get("size")
        return PluginResult(
            type=PluginResultType.DIRECT_FILE,
            original_url=original_url,
            resolved_url=resolved_url,
            filename=sanitize_filename(str(file_data.get("fileName") or "")) if file_data.get("fileName") else None,
            size=int(size) if isinstance(size, int) or (isinstance(size, str) and size.isdigit()) else None,
            host=host_from_url(resolved_url),
            plugin=self.name,
        )
