import tempfile
import unittest
from pathlib import Path

from scripts.dev import read_dotenv


class ReadDotenvTests(unittest.TestCase):
    def test_reads_comments_plain_values_and_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('# comment\nMIMO_API_KEY="secret=value"\nKAIROS_DB_PATH=var/test.sqlite3\n', encoding="utf-8")
            self.assertEqual(read_dotenv(path), {
                "MIMO_API_KEY": "secret=value",
                "KAIROS_DB_PATH": "var/test.sqlite3",
            })

    def test_rejects_malformed_entries_without_echoing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("not-an-assignment\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 1"):
                read_dotenv(path)

    def test_missing_file_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(read_dotenv(Path(directory) / "absent.env"), {})


if __name__ == "__main__":
    unittest.main()
