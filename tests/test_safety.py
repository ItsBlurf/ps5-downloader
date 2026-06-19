import tempfile
import unittest
from pathlib import Path

from ps5_downloader.core.utils import ensure_safe_child, sanitize_filename


class SafetyTests(unittest.TestCase):
    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("../bad:name?.zip"), "_bad_name_.zip")
        self.assertEqual(sanitize_filename("CON"), "_CON")

    def test_path_traversal_prevention(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = ensure_safe_child(tmp, "../../evil.bin")
            self.assertTrue(str(path).startswith(str(Path(tmp).resolve())))
            self.assertNotIn("evil/..", str(path))


if __name__ == "__main__":
    unittest.main()
