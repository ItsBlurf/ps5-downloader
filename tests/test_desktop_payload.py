import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ps5_downloader.desktop.payload import send_payload_file


class FakeSocket:
    sent = b""
    connected = None

    def __init__(self, *_args, **_kwargs):
        self.closed = False

    def settimeout(self, _timeout):
        pass

    def connect(self, address):
        FakeSocket.connected = address

    def sendall(self, data):
        FakeSocket.sent += data

    def close(self):
        self.closed = True


class DesktopPayloadTests(unittest.TestCase):
    def test_send_payload_sends_bytes_and_reports_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            elf = Path(tmp) / "payload.elf"
            elf.write_bytes(b"ELF")
            FakeSocket.sent = b""
            FakeSocket.connected = None

            with patch("ps5_downloader.desktop.payload.daemon_status", return_value=None), patch(
                "ps5_downloader.desktop.payload.wait_for_daemon_up", return_value={"ok": True}
            ), patch("ps5_downloader.desktop.payload.socket.socket", FakeSocket):
                result = send_payload_file(elf, "192.168.1.204", 9021, 2634)

        self.assertEqual(FakeSocket.connected, ("192.168.1.204", 9021))
        self.assertEqual(FakeSocket.sent, b"ELF")
        self.assertEqual(result.sha256, hashlib.sha256(b"ELF").hexdigest())
        self.assertEqual(result.status, {"ok": True})


if __name__ == "__main__":
    unittest.main()
