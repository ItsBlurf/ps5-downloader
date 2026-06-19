import tempfile
import unittest
from pathlib import Path

from ps5_downloader.core.downloader import QueueManager
from ps5_downloader.core.models import DownloadState, PluginResult, PluginResultType, Settings
from ps5_downloader.core.storage import Storage


class QueueTests(unittest.TestCase):
    def test_state_transitions_pause_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "state.sqlite3")
            try:
                settings = Settings(download_dir=str(Path(tmp) / "downloads"), temp_dir=str(Path(tmp) / "tmp"))
                queue = QueueManager(storage, settings)
                result = PluginResult(
                    type=PluginResultType.DIRECT_FILE,
                    original_url="http://example.com/file.bin",
                    resolved_url="http://example.com/file.bin",
                    plugin="test",
                )
                item = queue.add_result(result)[0]
                self.assertEqual(item.state, DownloadState.WAITING)
                paused = queue.pause(item.id)
                self.assertEqual(paused.state, DownloadState.PAUSED)
                cancelled = queue.cancel(item.id)
                self.assertEqual(cancelled.state, DownloadState.CANCELLED)
            finally:
                storage.close()

    def test_delete_removes_final_and_partial_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "state.sqlite3")
            try:
                download_dir = root / "downloads"
                temp_dir = root / "tmp"
                settings = Settings(download_dir=str(download_dir), temp_dir=str(temp_dir))
                queue = QueueManager(storage, settings)
                result = PluginResult(
                    type=PluginResultType.DIRECT_FILE,
                    original_url="http://example.com/file.bin",
                    resolved_url="http://example.com/file.bin",
                    filename="file.bin",
                    plugin="test",
                )
                item = queue.add_result(result)[0]
                download_dir.mkdir()
                temp_dir.mkdir()
                final_path = download_dir / "file.bin"
                part_path = temp_dir / "file.bin.part"
                final_path.write_bytes(b"complete")
                part_path.write_bytes(b"partial")

                self.assertTrue(queue.delete(item.id))
                self.assertFalse(final_path.exists())
                self.assertFalse(part_path.exists())
                self.assertIsNone(storage.get_download(item.id))
            finally:
                storage.close()

    def test_cancel_completed_item_keeps_completed_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "state.sqlite3")
            try:
                settings = Settings(download_dir=str(Path(tmp) / "downloads"), temp_dir=str(Path(tmp) / "tmp"))
                queue = QueueManager(storage, settings)
                result = PluginResult(
                    type=PluginResultType.DIRECT_FILE,
                    original_url="http://example.com/file.bin",
                    resolved_url="http://example.com/file.bin",
                    filename="file.bin",
                    plugin="test",
                )
                item = queue.add_result(result)[0]
                item.state = DownloadState.COMPLETED
                storage.update_download(item)

                cancelled = queue.cancel(item.id)
                self.assertEqual(cancelled.state, DownloadState.COMPLETED)
                self.assertIn("already completed", cancelled.error or "")
            finally:
                storage.close()


if __name__ == "__main__":
    unittest.main()
