import unittest
from unittest.mock import patch

from ps5_downloader.core.utils import (
    actionable_urls_from_text,
    dedupe_urls,
    extract_urls,
    is_likely_download_url,
    normalize_url,
    ps5_native_http_url,
)


class ParserTests(unittest.TestCase):
    def test_extract_urls_from_text_and_html(self):
        text = '<a href="https://example.com/a.zip">x</a> and https://example.com/b.zip.'
        self.assertEqual(extract_urls(text), ["https://example.com/a.zip", "https://example.com/b.zip"])

    def test_dedupes_normalized_urls(self):
        urls = ["HTTP://Example.com/file?b=2&a=1", "http://example.com/file?a=1&b=2"]
        self.assertEqual(dedupe_urls(urls), ["http://example.com/file?a=1&b=2"])

    def test_rejects_non_http(self):
        with self.assertRaises(ValueError):
            normalize_url("ftp://example.com/file")

    def test_google_drive_mess_prefers_file_url_and_skips_noise(self):
        text = """
        https://accounts.google.com/signin
        https://www.google.com/url?q=https%3A%2F%2Fnoise.example%2F
        https://drive.google.com/file/d/abc123/view?usp=sharing
        https://ssl.gstatic.com/docs/doclist/images/icon.png
        """
        self.assertEqual(actionable_urls_from_text(text), ["https://drive.google.com/file/d/abc123/view?usp=sharing"])

    def test_likely_download_url_detects_common_file_hosts(self):
        self.assertTrue(is_likely_download_url("https://host.example/game.pkg"))
        self.assertTrue(is_likely_download_url("https://host.example/archive.part01.rar"))
        self.assertTrue(is_likely_download_url("https://host.example/file.7z?download=1"))
        self.assertFalse(is_likely_download_url("https://host.example/folder/page"))

    def test_ps5_native_http_url_adds_host_override_for_mediafire_cdn(self):
        with patch("ps5_downloader.core.utils.socket.gethostbyname", return_value="203.0.113.10"):
            self.assertEqual(
                ps5_native_http_url("https://download123.mediafire.com/path/file.7z"),
                "http://203.0.113.10/path/file.7z?__ps5_host=download123.mediafire.com",
            )

    def test_ps5_native_http_url_downgrades_likely_https_downloads(self):
        with patch("ps5_downloader.core.utils.socket.gethostbyname", return_value="203.0.113.20"):
            self.assertEqual(
                ps5_native_http_url("https://files.example.com/releases/game.pkg?token=abc"),
                "http://203.0.113.20/releases/game.pkg?token=abc&__ps5_host=files.example.com",
            )

    def test_ps5_native_http_url_leaves_non_download_https_pages(self):
        self.assertEqual(
            ps5_native_http_url("https://example.com/folder/page"),
            "https://example.com/folder/page",
        )

    def test_ps5_native_http_url_can_force_plugin_confirmed_https_direct_file(self):
        self.assertTrue(
            ps5_native_http_url("https://example.com/d/opaque-token?v=1", allow_https_direct=True).startswith("http://")
        )


if __name__ == "__main__":
    unittest.main()
