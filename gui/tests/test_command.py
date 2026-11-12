import subprocess
import unittest
from pathlib import Path

from gui.command import DOWNLOADER_SCRIPT, download_command, ruby_command


class RubyCommandTest(unittest.TestCase):
    def test_download_command_passes_the_site_and_directory(self):
        argv = download_command("http://example.com", Path("/tmp/archived-site"))
        self.assertEqual(argv[1], "-e")
        self.assertIn("STDOUT.sync=true", argv[2])
        self.assertEqual(argv[3], str(DOWNLOADER_SCRIPT))
        self.assertEqual(
            argv[4:],
            ["--directory", "/tmp/archived-site/example.com", "http://example.com"],
        )

    def test_dated_archive_link_stops_at_that_snapshot(self):
        argv = download_command(
            "http://cactuscruisersamc.org",
            Path("/tmp/archived-site"),
            to_timestamp="20190719091311",
        )
        self.assertEqual(
            argv[4:],
            [
                "--directory",
                "/tmp/archived-site/cactuscruisersamc.org",
                "--to",
                "20190719091311",
                "http://cactuscruisersamc.org",
            ],
        )

    def test_version_command_runs_the_downloader(self):
        completed = subprocess.run(
            ruby_command(["--version"]),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stdout.strip(), "2.3.2")


if __name__ == "__main__":
    unittest.main()
