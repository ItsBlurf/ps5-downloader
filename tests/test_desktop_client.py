import unittest

from ps5_downloader.desktop.client import api_base, normalize_download


class DesktopClientTests(unittest.TestCase):
    def test_api_base_accepts_host_or_http_url(self):
        self.assertEqual(api_base("192.168.1.204", 2634), "http://192.168.1.204:2634")
        self.assertEqual(api_base("http://192.168.1.204:2634/", 9999), "http://192.168.1.204:2634")

    def test_normalize_native_download_shape(self):
        row = normalize_download(
            {
                "id": 7,
                "filename": "file.7z",
                "state": "downloading",
                "bytes": 50,
                "content_length": 100,
                "http_status": 206,
                "path": "/data/test/file.7z",
            }
        )
        self.assertEqual(row.id, "7")
        self.assertEqual(row.name, "file.7z")
        self.assertEqual(row.percent, 50.0)
        self.assertEqual(row.total_bytes, 100)

    def test_normalize_python_download_shape(self):
        row = normalize_download(
            {
                "id": "abc",
                "original_url": "https://example.com/file.pkg",
                "state": "waiting",
                "downloaded_bytes": 25,
                "size": 100,
                "percent": 25.0,
                "speed_bps": 2048,
            }
        )
        self.assertEqual(row.id, "abc")
        self.assertEqual(row.name, "https://example.com/file.pkg")
        self.assertEqual(row.speed_bps, 2048)


if __name__ == "__main__":
    unittest.main()
