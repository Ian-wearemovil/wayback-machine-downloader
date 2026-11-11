"""Build the Ruby command the desktop app runs."""

import shutil
from pathlib import Path

from gui.url_normalize import destination_directory

REPO_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADER_SCRIPT = REPO_ROOT / "bin" / "wayback_machine_downloader"

# Force line-by-line output when the CLI is not attached to a terminal.
_SYNC_LOAD = "STDOUT.sync=true; STDERR.sync=true; load ARGV.shift"


def ruby_executable():
    ruby = shutil.which("ruby")
    if not ruby:
        raise RuntimeError("Ruby is not installed. On CachyOS, install it with: sudo pacman -S ruby")
    return ruby


def ruby_command(args):
    """Return argv that runs the downloader script with the given arguments."""
    return [
        ruby_executable(),
        "-e",
        _SYNC_LOAD,
        str(DOWNLOADER_SCRIPT),
        *args,
    ]


def download_command(site_url, parent_directory):
    """Download the site into a folder named after its domain."""
    directory = destination_directory(parent_directory, site_url)
    return ruby_command([site_url, "--directory", str(directory)])
