from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from ps5_downloader.core.models import PluginResult, PluginResultType
from ps5_downloader.core.utils import filename_from_url, host_from_url

from .base import BasePlugin


HX_GET_RE = re.compile(
    r"""<a\b[^>]*\bhx-get=["'](?P<hx_get>[^"']*/download[^"']*)["'][^>]*>""",
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<(?:h1|span)[^>]*>(?P<title>[^<]+)</(?:h1|span)>", re.IGNORECASE)


def parse_buzzheavier_download_endpoint(html: str, page_url: str) -> str | None:
    match = HX_GET_RE.search(html)
    if not match:
        return None
    return urljoin(page_url, unescape(match.group("hx_get")))


def parse_buzzheavier_filename(html: str, fallback_url: str) -> str:
    match = TITLE_RE.search(html)
    if match:
        return unescape(match.group("title")).strip()
    return filename_from_url(fallback_url)


def is_cloudflare_challenge(status: int, headers: object, body: str = "") -> bool:
    header_get = getattr(headers, "get", lambda _key, _default=None: None)
    mitigated = str(header_get("cf-mitigated", "")).lower()
    server = str(header_get("server", "")).lower()
    return mitigated == "challenge" or (status == 403 and "cloudflare" in server) or "Just a moment..." in body


class BuzzHeavierPlugin(BasePlugin):
    name = "buzzheavier-public"
    supported_domains = ["buzzheavier.com", "bzzhr.co"]
    patterns = [r"buzzheavier\.com/[A-Za-z0-9]+", r"bzzhr\.co/[A-Za-z0-9]+"]
    priority = 90
    supports_metadata = True

    def resolve(self, url: str) -> PluginResult:
        page_url = self._canonical_page_url(url)
        page_html = ""
        filename = filename_from_url(page_url)
        try:
            page_req = Request(page_url, headers=self._page_headers(page_url))
            with urlopen(page_req, timeout=15) as response:
                page_html = response.read(800_000).decode("utf-8", errors="replace")
                if is_cloudflare_challenge(getattr(response, "status", 200), response.headers, page_html):
                    return self._cloudflare_result(url)
        except Exception as exc:
            message = str(exc)
            if "HTTP Error 403" in message:
                return self._cloudflare_result(url)
            return PluginResult(type=PluginResultType.ERROR, original_url=url, plugin=self.name, message=message)

        filename = parse_buzzheavier_filename(page_html, page_url)
        endpoint = parse_buzzheavier_download_endpoint(page_html, page_url) or f"{page_url}/download"
        try:
            download_req = Request(endpoint, headers=self._download_headers(page_url))
            with urlopen(download_req, timeout=20) as response:
                if is_cloudflare_challenge(getattr(response, "status", 200), response.headers):
                    return self._cloudflare_result(url)
                direct_url = response.headers.get("HX-Redirect") or response.headers.get("Hx-Redirect")
                if not direct_url:
                    return PluginResult(
                        type=PluginResultType.MANUAL_ACTION_REQUIRED,
                        original_url=url,
                        plugin=self.name,
                        host=host_from_url(url),
                        message="Buzzheavier did not return an HX-Redirect direct download URL.",
                    )
                direct_url = urljoin(page_url, direct_url)
        except Exception as exc:
            message = str(exc)
            if "HTTP Error 403" in message:
                return self._cloudflare_result(url)
            return PluginResult(type=PluginResultType.ERROR, original_url=url, plugin=self.name, message=message)

        return PluginResult(
            type=PluginResultType.DIRECT_FILE,
            original_url=url,
            resolved_url=direct_url,
            filename=filename_from_url(filename or direct_url),
            host=host_from_url(direct_url),
            plugin=self.name,
        )

    @staticmethod
    def _canonical_page_url(url: str) -> str:
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if path.endswith("/download"):
            path = path[: -len("/download")]
        return f"https://{parts.netloc}{path}"

    @staticmethod
    def _page_headers(page_url: str) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": page_url,
        }

    @staticmethod
    def _download_headers(page_url: str) -> dict[str, str]:
        return {
            **BuzzHeavierPlugin._page_headers(page_url),
            "HX-Request": "true",
            "HX-Current-URL": page_url,
            "Priority": "u=1, i",
        }

    def _cloudflare_result(self, url: str) -> PluginResult:
        return PluginResult(
            type=PluginResultType.MANUAL_ACTION_REQUIRED,
            original_url=url,
            plugin=self.name,
            host=host_from_url(url),
            message=(
                "Buzzheavier returned a Cloudflare browser challenge. Open the link in a browser and send/copy the "
                "direct download URL, or use a resolver helper with a browser session."
            ),
        )
