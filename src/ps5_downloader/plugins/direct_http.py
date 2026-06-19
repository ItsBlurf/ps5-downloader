from __future__ import annotations

import re
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from ps5_downloader.core.models import PluginResult, PluginResultType
from ps5_downloader.core.utils import filename_from_url, host_from_url, is_likely_download_url

from .base import BasePlugin


class DirectHttpPlugin(BasePlugin):
    name = "direct-http"
    patterns = [r"^https?://"]
    priority = 10
    supports_metadata = True

    def resolve(self, url: str) -> PluginResult:
        filename = filename_from_url(url)
        size = None
        resolved_url = url
        try:
            req = Request(url, method="HEAD", headers={"User-Agent": "ps5-downloader/0.1"})
            with urlopen(req, timeout=10) as response:
                resolved_url = response.geturl()
                content_type = response.headers.get("Content-Type", "")
                if "html" in content_type.lower() and not self._looks_like_download(resolved_url):
                    return PluginResult(type=PluginResultType.UNSUPPORTED, original_url=url, plugin=self.name)
                length = response.headers.get("Content-Length")
                cd = response.headers.get("Content-Disposition")
                if length and length.isdigit():
                    size = int(length)
                filename = filename_from_content_disposition(cd) or filename
        except HTTPError as exc:
            try:
                if not self._looks_like_download(url):
                    return PluginResult(
                        type=PluginResultType.UNSUPPORTED,
                        original_url=url,
                        plugin=self.name,
                        message=f"HEAD returned status {exc.code}",
                    )
            finally:
                exc.close()
        except Exception as exc:
            if not self._looks_like_download(url):
                return PluginResult(
                    type=PluginResultType.UNSUPPORTED,
                    original_url=url,
                    plugin=self.name,
                    message=str(exc),
                )
        if not urlsplit(resolved_url).path.endswith("/"):
            filename = filename_from_url(filename or resolved_url)
        return PluginResult(
            type=PluginResultType.DIRECT_FILE,
            original_url=url,
            resolved_url=resolved_url,
            filename=filename,
            size=size,
            host=host_from_url(resolved_url),
            plugin=self.name,
        )

    @staticmethod
    def _looks_like_download(url: str) -> bool:
        return is_likely_download_url(url)


class RedirectResolverPlugin(BasePlugin):
    name = "generic-redirect"
    patterns = [r"^https?://"]
    priority = 20
    supports_metadata = True

    def resolve(self, url: str) -> PluginResult:
        req = Request(url, method="HEAD", headers={"User-Agent": "ps5-downloader/0.1"})
        try:
            with urlopen(req, timeout=10) as response:
                final_url = response.geturl()
                if final_url != url:
                    return PluginResult(
                        type=PluginResultType.REDIRECT,
                        original_url=url,
                        resolved_url=final_url,
                        filename=filename_from_url(final_url),
                        host=host_from_url(final_url),
                        plugin=self.name,
                    )
        except HTTPError as exc:
            try:
                return PluginResult(
                    type=PluginResultType.ERROR,
                    original_url=url,
                    plugin=self.name,
                    message=str(exc),
                )
            finally:
                exc.close()
        except Exception as exc:
            return PluginResult(
                type=PluginResultType.ERROR,
                original_url=url,
                plugin=self.name,
                message=str(exc),
            )
        return PluginResult(type=PluginResultType.UNSUPPORTED, original_url=url, plugin=self.name)


def filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    ext_match = re.search(r"filename\*\s*=\s*(?:UTF-8''|utf-8'')?([^;\r\n]+)", value)
    if ext_match:
        return unquote(ext_match.group(1).strip().strip("\"'"))
    match = re.search(r"filename\s*=\s*([^;\r\n]+)", value)
    if match:
        return match.group(1).strip().strip("\"'")
    return None
