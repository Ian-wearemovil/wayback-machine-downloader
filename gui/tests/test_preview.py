import tempfile
import unittest
import urllib.request
from pathlib import Path

from gui.preview import PreviewServer


class PreviewServerTest(unittest.TestCase):
    def test_serves_the_site_on_localhost_and_switches_sites(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "arcgps.com"
            second = Path(tmp) / "example.com"
            first.mkdir()
            second.mkdir()
            (first / "index.html").write_text("arcgps-home", encoding="utf-8")
            (second / "index.html").write_text("example-home", encoding="utf-8")
            server = PreviewServer()
            try:
                first_url = server.serve(first)
                self.assertTrue(first_url.startswith("http://127.0.0.1:"))
                self.assertEqual(_read(first_url), "arcgps-home")
                self.assertEqual(server.serve(first), first_url)

                second_url = server.serve(second)
                self.assertNotEqual(second_url, first_url)
                self.assertEqual(_read(second_url), "example-home")
            finally:
                server.stop()

    def test_missing_directory_raises(self):
        server = PreviewServer()
        with self.assertRaises(FileNotFoundError):
            server.serve("/tmp/wayback-preview-missing")


def _read(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


if __name__ == "__main__":
    unittest.main()
