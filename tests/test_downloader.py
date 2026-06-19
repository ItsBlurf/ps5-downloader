import http.server
import tempfile
import threading
import unittest
from pathlib import Path
import threading as threading_module

from ps5_downloader.core.downloader import DownloadEngine, range_header_for_existing_size
from ps5_downloader.core.models import DownloadItem, DownloadState, Settings
from ps5_downloader.core.storage import Storage
from ps5_downloader.plugins.direct_http import DirectHttpPlugin


class _Handler(http.server.BaseHTTPRequestHandler):
    payload = b"0123456789" * 100

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()

    def do_GET(self):
        range_header = self.headers.get("Range")
        if range_header:
            start = int(range_header.split("=", 1)[1].split("-", 1)[0])
            body = self.payload[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(self.payload)-1}/{len(self.payload)}")
        else:
            body = self.payload
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DownloaderTests(unittest.TestCase):
    def test_range_header(self):
        self.assertEqual(range_header_for_existing_size(10), {"Range": "bytes=10-"})
        self.assertEqual(range_header_for_existing_size(0), {})

    def test_direct_http_resolution_local_server(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/file.bin"
            result = DirectHttpPlugin().resolve(url)
            self.assertEqual(result.size, len(_Handler.payload))
            self.assertEqual(result.filename, "file.bin")
        finally:
            server.shutdown()
            server.server_close()

    def test_download_engine_resumes_part_file(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "state.sqlite3")
            try:
                settings = Settings(download_dir=str(root / "downloads"), temp_dir=str(root / "tmp"))
                engine = DownloadEngine(settings, storage)
                item = DownloadItem(
                    id="item-1",
                    original_url=f"http://127.0.0.1:{server.server_port}/file.bin",
                    resolved_url=f"http://127.0.0.1:{server.server_port}/file.bin",
                    filename="file.bin",
                )
                storage.add_download(item)
                part = root / "tmp" / "file.bin.part"
                part.parent.mkdir(parents=True)
                part.write_bytes(_Handler.payload[:100])
                done = engine.download(item, threading_module.Event(), threading_module.Event())
                self.assertEqual(done.state, DownloadState.COMPLETED)
                self.assertEqual((root / "downloads" / "file.bin").read_bytes(), _Handler.payload)
            finally:
                storage.close()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    unittest.main()
