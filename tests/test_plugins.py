import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from ps5_downloader.core.models import PluginResult, PluginResultType
from ps5_downloader.core.resolver import LinkResolver
from ps5_downloader.plugins.base import BasePlugin
from ps5_downloader.plugins.akirabox import AkiraBoxPlugin, parse_size_text
from ps5_downloader.plugins.buzzheavier import (
    BuzzHeavierPlugin,
    parse_buzzheavier_download_endpoint,
)
from ps5_downloader.plugins.direct_http import DirectHttpPlugin, filename_from_content_disposition
from ps5_downloader.plugins.generic_html import GenericHtmlPlugin
from ps5_downloader.plugins.mediafire import parse_mediafire_public_html
from ps5_downloader.plugins.onefichier import OneFichierPlugin, parse_1fichier_file_info, parse_1fichier_wait_seconds
from ps5_downloader.plugins.registry import PluginRegistry
from ps5_downloader.plugins.rootz import RootzPlugin, parse_rootz_page_token, parse_rootz_short_id, parse_rootz_title


class PluginTests(unittest.TestCase):
    def test_plugin_matching_prefers_mediafire(self):
        registry = PluginRegistry()
        matches = registry.matching_plugins("https://www.mediafire.com/file/abc/name.zip/file")
        self.assertEqual(matches[0].name, "mediafire-public")

    def test_plugin_matching_prefers_buzzheavier(self):
        registry = PluginRegistry()
        matches = registry.matching_plugins("https://buzzheavier.com/e20qiwzajbrq")
        self.assertEqual(matches[0].name, "buzzheavier-public")

    def test_plugin_matching_prefers_akirabox(self):
        registry = PluginRegistry()
        matches = registry.matching_plugins("https://akirabox.com/N2p3DQ1kzMa5/file")
        self.assertEqual(matches[0].name, "akirabox-public")

    def test_plugin_matching_prefers_akirabox_to(self):
        registry = PluginRegistry()
        matches = registry.matching_plugins("https://akirabox.to/gXeGOobwPGAa/file")
        self.assertEqual(matches[0].name, "akirabox-public")

    def test_plugin_matching_prefers_rootz(self):
        registry = PluginRegistry()
        matches = registry.matching_plugins("https://www.rootz.so/d/1zJYQK")
        self.assertEqual(matches[0].name, "rootz-public")

    def test_plugin_matching_prefers_1fichier(self):
        registry = PluginRegistry()
        matches = registry.matching_plugins("https://1fichier.com/?eb6ooyk6tu3y5pkbhgwb")
        self.assertEqual(matches[0].name, "1fichier-public")

    def test_akirabox_plugin_uses_file_status_api(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return b'{"status":200,"name":"sample.7z","size":"1.5 GB","url":"https://akirabox.com/abc/file"}'

        with patch("ps5_downloader.plugins.akirabox.urlopen", return_value=FakeResponse()):
            result = AkiraBoxPlugin().resolve("https://akirabox.com/abc/file")

        self.assertEqual(result.type, PluginResultType.DIRECT_FILE)
        self.assertEqual(result.filename, "sample.7z")
        self.assertEqual(result.size, 1610612736)

    def test_parse_size_text(self):
        self.assertEqual(parse_size_text("1.25 MB"), 1310720)

    def test_rootz_parser_helpers(self):
        html = '<title>nnssaw.7z</title><script>self.__next_f.push([1,"{\\"pageToken\\":\\"abc.123\\"}"])</script>'
        self.assertEqual(parse_rootz_short_id("https://www.rootz.so/d/1zJYQK"), "1zJYQK")
        self.assertEqual(parse_rootz_page_token(html), "abc.123")
        self.assertEqual(parse_rootz_title(html), "nnssaw.7z")

    def test_rootz_plugin_uses_public_proxy_download(self):
        page_html = '<title>nnssaw.7z</title><script>self.__next_f.push([1,"{\\"pageToken\\":\\"tok\\"}"])</script>'

        class FakePageResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return page_html.encode()

        class FakeApiResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return b'{"success":true,"data":{"fileId":"1zJYQK","fileName":"nnssaw.7z","size":96405553,"downloadAllowed":true}}'

        with patch("ps5_downloader.plugins.rootz.urlopen", side_effect=[FakePageResponse(), FakeApiResponse()]):
            result = RootzPlugin().resolve("https://www.rootz.so/d/1zJYQK")

        self.assertEqual(result.type, PluginResultType.DIRECT_FILE)
        self.assertEqual(result.filename, "nnssaw.7z")
        self.assertEqual(result.size, 96405553)
        self.assertEqual(result.resolved_url, "https://www.rootz.so/api/files/proxy-download/1zJYQK")

    def test_1fichier_parser_reports_wait_flow(self):
        html = """
        <script>var ct = 60;</script>
        <span style="font-weight:bold">nnssaw.7z</span>
        <span style="font-size:0.9em;font-style:italic">96.41 MB</span>
        <input type="checkbox" name="dl_no_ssl" />
        """
        filename, size = parse_1fichier_file_info(html)
        self.assertEqual(filename, "nnssaw.7z")
        self.assertEqual(size, 101093212)
        self.assertEqual(parse_1fichier_wait_seconds(html), 60)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return html.encode()

        with patch("ps5_downloader.plugins.onefichier.urlopen", return_value=FakeResponse()):
            result = OneFichierPlugin().resolve("https://1fichier.com/?eb6ooyk6tu3y5pkbhgwb")

        self.assertEqual(result.type, PluginResultType.MANUAL_ACTION_REQUIRED)
        self.assertEqual(result.filename, "nnssaw.7z")
        self.assertIn("60s wait", result.message or "")

    def test_content_disposition_filename_parser(self):
        self.assertEqual(filename_from_content_disposition("attachment;filename=nnssaw.7z"), "nnssaw.7z")
        self.assertEqual(filename_from_content_disposition("attachment; filename*=UTF-8''My%20File.pkg"), "My File.pkg")

    def test_direct_http_does_not_guess_non_file_pages_after_head_failure(self):
        with patch(
            "ps5_downloader.plugins.direct_http.urlopen",
            side_effect=HTTPError("https://host.example/file", 403, "Forbidden", {}, BytesIO()),
        ):
            result = DirectHttpPlugin().resolve("https://host.example/file")

        self.assertEqual(result.type, PluginResultType.UNSUPPORTED)

    def test_direct_http_keeps_file_extension_urls_after_head_failure(self):
        with patch(
            "ps5_downloader.plugins.direct_http.urlopen",
            side_effect=HTTPError("https://host.example/game.pkg", 403, "Forbidden", {}, BytesIO()),
        ):
            result = DirectHttpPlugin().resolve("https://host.example/game.pkg")

        self.assertEqual(result.type, PluginResultType.DIRECT_FILE)

    def test_buzzheavier_parser_finds_hx_download_endpoint(self):
        html = '<a class="link-button gay-button" hx-get="/e20qiwzajbrq/download">Download</a>'
        self.assertEqual(
            parse_buzzheavier_download_endpoint(html, "https://buzzheavier.com/e20qiwzajbrq"),
            "https://buzzheavier.com/e20qiwzajbrq/download",
        )

    def test_buzzheavier_plugin_uses_hx_redirect(self):
        html = """
        <h1>sample.pkg</h1>
        <a class="link-button gay-button" hx-get="/e20qiwzajbrq/download">Download File</a>
        """

        class FakePageResponse:
            status = 200
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return html.encode()

        class FakeDownloadResponse:
            status = 200
            headers = {"HX-Redirect": "https://dl.buzzheavier.com/file/sample.pkg"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("ps5_downloader.plugins.buzzheavier.urlopen", side_effect=[FakePageResponse(), FakeDownloadResponse()]):
            result = BuzzHeavierPlugin().resolve("https://buzzheavier.com/e20qiwzajbrq")

        self.assertEqual(result.type, PluginResultType.DIRECT_FILE)
        self.assertEqual(result.resolved_url, "https://dl.buzzheavier.com/file/sample.pkg")

    def test_buzzheavier_plugin_reports_cloudflare_challenge(self):
        class FakeResponse:
            status = 403
            headers = {"cf-mitigated": "challenge", "server": "cloudflare"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return b"Just a moment..."

        with patch("ps5_downloader.plugins.buzzheavier.urlopen", return_value=FakeResponse()):
            result = BuzzHeavierPlugin().resolve("https://buzzheavier.com/e20qiwzajbrq")

        self.assertEqual(result.type, PluginResultType.MANUAL_ACTION_REQUIRED)
        self.assertIn("Cloudflare", result.message or "")

    def test_mediafire_fixture_parser(self):
        html = Path("tests/fixtures/mediafire_public.html").read_text()
        self.assertEqual(
            parse_mediafire_public_html(html),
            "https://download1234.mediafire.com/abc123/example/My%20File.zip",
        )

    def test_github_release_plugin(self):
        result = PluginRegistry().resolve("https://github.com/owner/repo/releases/download/v1/app.zip")
        self.assertEqual(result.type, PluginResultType.DIRECT_FILE)
        self.assertEqual(result.plugin, "github-release-asset")

    def test_generic_html_keeps_likely_download_links_only(self):
        html = """
        <a href="/about">About</a>
        <a href="https://files.example/game.pkg">PKG</a>
        <script src="/app.js"></script>
        https://cdn.example/archive.part01.rar
        """

        class FakeResponse:
            headers = {"Content-Type": "text/html; charset=utf-8"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return html.encode()

        with patch("ps5_downloader.plugins.generic_html.urlopen", return_value=FakeResponse()):
            result = GenericHtmlPlugin().resolve("https://page.example/download")

        self.assertEqual(result.type, PluginResultType.PACKAGE)
        self.assertEqual([child.resolved_url for child in result.children], [
            "https://files.example/game.pkg",
            "https://cdn.example/archive.part01.rar",
        ])

    def test_generic_html_ignores_page_asset_links(self):
        html = """
        <link rel="icon" href="https://img.example/favicon.png" />
        <img src="https://img.example/logo.png" />
        <a href="/terms">Terms</a>
        """

        class FakeResponse:
            headers = {"Content-Type": "text/html; charset=utf-8"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, _limit):
                return html.encode()

        with patch("ps5_downloader.plugins.generic_html.urlopen", return_value=FakeResponse()):
            result = GenericHtmlPlugin().resolve("https://page.example/download")

        self.assertEqual(result.type, PluginResultType.MANUAL_ACTION_REQUIRED)

    def test_recursive_resolver_expands_generic_html_package(self):
        class PagePlugin(BasePlugin):
            name = "fake-page"
            patterns = [r"page\.example"]
            priority = 20

            def resolve(self, url: str):
                return PluginResult(
                    type=PluginResultType.PACKAGE,
                    original_url=url,
                    plugin=self.name,
                    children=[
                        PluginResult(
                            type=PluginResultType.REDIRECT,
                            original_url=url,
                            resolved_url="https://files.example/game.pkg",
                            plugin=self.name,
                        )
                    ],
                )

        class FilePlugin(BasePlugin):
            name = "fake-file"
            patterns = [r"files\.example"]
            priority = 10

            def resolve(self, url: str):
                return PluginResult(
                    type=PluginResultType.DIRECT_FILE,
                    original_url=url,
                    resolved_url=url,
                    filename="game.pkg",
                    plugin=self.name,
                )

        registry = PluginRegistry(plugins=[PagePlugin(), FilePlugin()])
        results = LinkResolver(registry=registry, max_depth=2).resolve_text("https://page.example/download")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].type, PluginResultType.DIRECT_FILE)
        self.assertEqual(results[0].resolved_url, "https://files.example/game.pkg")


if __name__ == "__main__":
    unittest.main()
