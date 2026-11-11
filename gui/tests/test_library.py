import tempfile
import unittest
from pathlib import Path

from gui.library import (
    discover_sites,
    load_records,
    remember_download,
    save_records,
    visible_sites,
)


class LibraryTest(unittest.TestCase):
    def test_discover_finds_a_domain_folder_with_an_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            site = parent / "arcgps.com"
            site.mkdir()
            (site / "index.html").write_text("<title>Arc</title>", encoding="utf-8")
            (parent / "notes").mkdir()
            (parent / "notes" / "index.html").write_text("nope", encoding="utf-8")

            found = discover_sites(parent)

        self.assertEqual([item["name"] for item in found], ["arcgps.com"])
        self.assertTrue(found[0]["path"].endswith("/arcgps.com"))

    def test_visible_sites_keep_saved_downloads_and_add_existing_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            older = parent / "example.com"
            older.mkdir()
            (older / "index.html").write_text("old", encoding="utf-8")
            saved = parent / "arcgps.com"
            saved.mkdir()
            (saved / "index.html").write_text("saved", encoding="utf-8")
            records = remember_download([], "arcgps.com", "http://arcgps.com", saved)
            library = parent / "downloads.json"
            save_records(library, records)

            sites = visible_sites(load_records(library), parent)

        self.assertEqual([site["name"] for site in sites], ["arcgps.com", "example.com"])

    def test_missing_folders_are_hidden(self):
        records = [
            {"name": "gone.example", "path": "/tmp/does-not-exist-wayback", "url": "http://gone.example"}
        ]
        self.assertEqual(visible_sites(records, "/tmp"), [])


if __name__ == "__main__":
    unittest.main()
