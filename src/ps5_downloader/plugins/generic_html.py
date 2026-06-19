from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from ps5_downloader.core.models import PluginResult, PluginResultType
from ps5_downloader.core.utils import dedupe_urls, extract_urls, host_from_url, is_likely_download_url

from .base import BasePlugin


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.anchor_links: list[str] = []
        self.attribute_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key.lower() in {"href", "src"} and value:
                joined = urljoin(self.base_url, value)
                self.attribute_links.append(joined)
                if tag.lower() == "a" and key.lower() == "href":
                    self.anchor_links.append(joined)


class GenericHtmlPlugin(BasePlugin):
    name = "generic-html"
    patterns = [r"^https?://"]
    priority = -10
    supports_folders = True

    def resolve(self, url: str) -> PluginResult:
        req = Request(url, headers={"User-Agent": "ps5-downloader/0.1"})
        try:
            with urlopen(req, timeout=10) as response:
                content_type = response.headers.get("Content-Type", "")
                if "html" not in content_type:
                    return PluginResult(type=PluginResultType.UNSUPPORTED, original_url=url, plugin=self.name)
                body = response.read(512_000).decode("utf-8", errors="replace")
        except Exception as exc:
            return PluginResult(type=PluginResultType.ERROR, original_url=url, plugin=self.name, message=str(exc))

        parser = _LinkParser(url)
        parser.feed(body)
        attribute_links = set(dedupe_urls(parser.attribute_links))
        raw_urls = [child for child in extract_urls(body) if child not in attribute_links]
        urls = dedupe_urls(parser.anchor_links + raw_urls)
        download_urls = [child for child in urls if child != url and is_likely_download_url(child)]
        children = [
            PluginResult(
                type=PluginResultType.REDIRECT,
                original_url=url,
                resolved_url=child,
                host=host_from_url(child),
                plugin=self.name,
            )
            for child in download_urls[:64]
        ]
        if not children:
            return PluginResult(
                type=PluginResultType.MANUAL_ACTION_REQUIRED,
                original_url=url,
                plugin=self.name,
                host=host_from_url(url),
                message=f"found {len(urls)} page links, but no obvious downloadable file links",
            )
        return PluginResult(
            type=PluginResultType.PACKAGE,
            original_url=url,
            plugin=self.name,
            host=host_from_url(url),
            children=children,
            message=f"found {len(children)} likely downloadable links from {len(urls)} page links",
        )
