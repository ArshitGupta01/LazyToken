import tempfile
import unittest
from pathlib import Path
from notebook import Notebook


class NotebookTests(unittest.TestCase):
    def test_add_find_and_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            book = Notebook(Path(temp) / "notes.json")
            entry = book.add("First", "A useful note", ["work"])
            self.assertEqual(book.find("useful")[0]["id"], entry["id"])
            self.assertTrue(book.archive(entry["id"]))
            self.assertTrue(book.load()[0]["archived"])


if __name__ == "__main__":
    unittest.main()
