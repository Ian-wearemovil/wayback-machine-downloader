"""GTK window for downloading an archived website."""

import codecs
import os
import re
import signal
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from gui.command import download_command
from gui.url_normalize import UrlError, destination_directory, normalize_site_url

APP_ID = "org.hartator.WaybackMachineDownloader"
_PROGRESS = re.compile(r"\((\d+)/(\d+)\)")


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Wayback Machine Downloader")
        self.set_default_size(720, 560)
        self._job = None
        self._pulse_id = 0
        self._kill_id = 0
        self._pending = ""
        self._outcome = None
        self._user_stopped = False

        header = Gtk.HeaderBar()
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_top(16)
        root.set_margin_bottom(16)
        root.set_margin_start(16)
        root.set_margin_end(16)
        self.set_child(root)

        url_label = Gtk.Label(label="_Website URL", use_underline=True, xalign=0)
        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text(
            "Paste a site URL or a link from web.archive.org"
        )
        self.url_entry.set_hexpand(True)
        url_label.set_mnemonic_widget(self.url_entry)
        self.url_entry.connect("changed", self._on_url_changed)
        self.url_entry.connect("activate", lambda *_: self._on_primary_clicked(None))

        self.hint = Gtk.Label(xalign=0, wrap=True)
        self.hint.add_css_class("dim-label")
        self.hint.set_text("Paste a site URL or a Wayback Machine link.")

        folder_label = Gtk.Label(label="Save _to", use_underline=True, xalign=0)
        self.folder_entry = Gtk.Entry()
        self.folder_entry.set_hexpand(True)
        self.folder_entry.set_text(_default_folder())
        self.folder_entry.connect("changed", self._on_url_changed)
        folder_label.set_mnemonic_widget(self.folder_entry)
        browse = Gtk.Button(label="_Browse")
        browse.set_use_underline(True)
        browse.connect("clicked", self._on_browse)
        folder_row = Gtk.Box(spacing=8)
        folder_row.append(self.folder_entry)
        folder_row.append(browse)
        self.browse_button = browse

        self.action_button = Gtk.Button(label="_Download")
        self.action_button.set_use_underline(True)
        self.action_button.add_css_class("suggested-action")
        self.action_button.connect("clicked", self._on_primary_clicked)

        self.progress = Gtk.ProgressBar()
        self.progress.set_hexpand(True)
        self.progress.set_show_text(True)
        self.progress.set_text("Ready")
        action_row = Gtk.Box(spacing=12)
        action_row.append(self.action_button)
        action_row.append(self.progress)

        self.log = Gtk.TextView()
        self.log.set_editable(False)
        self.log.set_cursor_visible(False)
        self.log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log.set_monospace(True)
        self.log.add_css_class("log")
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self.log)

        for child in (
            url_label,
            self.url_entry,
            self.hint,
            folder_label,
            folder_row,
            action_row,
            scrolled,
        ):
            root.append(child)

        self.connect("close-request", self._on_close_request)
        self._refresh_hint()

    def _on_url_changed(self, *_args):
        self._refresh_hint()

    def _refresh_hint(self):
        try:
            site = normalize_site_url(self.url_entry.get_text())
        except UrlError as exc:
            self.hint.set_text(str(exc))
            self.hint.remove_css_class("success")
            return None
        destination = destination_directory(self._folder_path(), site)
        self.hint.set_text(f"Saves files in {destination}")
        return site

    def _on_browse(self, _button):
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose download folder")
        dialog.set_modal(True)
        current = self._folder_path()
        start = current if current.is_dir() else current.parent
        if start.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(start)))
        dialog.select_folder(self, None, self._on_folder_selected)

    def _on_folder_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if folder is not None and folder.get_path():
            self.folder_entry.set_text(folder.get_path())

    def _on_primary_clicked(self, _button):
        if self._job is not None:
            self._stop_download()
        else:
            self._start_download()

    def _start_download(self):
        site = self._refresh_hint()
        if site is None:
            self._alert("Check the URL", self.hint.get_text())
            return
        folder = self._folder_path()
        parent = folder if folder.exists() else folder.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            self._alert("Check the folder", f"Cannot save files in {folder}")
            return
        try:
            argv = download_command(site, folder)
        except RuntimeError as exc:
            self._alert("Ruby is required", str(exc))
            return

        self._user_stopped = False
        self._outcome = None
        self._pending = ""
        self.log.get_buffer().set_text("")
        self.progress.set_fraction(0)
        self.progress.set_text("Looking up snapshots…")
        self._set_running(True)
        self._pulse_id = GLib.timeout_add(120, self._pulse)
        self._job = _DownloadJob(argv, self._on_output, self._on_exit)

    def _stop_download(self):
        job = self._job
        if job is None:
            return
        self._user_stopped = True
        self.progress.set_text("Stopping…")
        job.terminate()
        if self._kill_id:
            GLib.source_remove(self._kill_id)
        self._kill_id = GLib.timeout_add(3000, self._force_kill)

    def _force_kill(self):
        self._kill_id = 0
        if self._job is not None:
            self._job.kill()
        return False

    def _pulse(self):
        if self._job is None or self._outcome == "files":
            self._pulse_id = 0
            return False
        self.progress.pulse()
        return True

    def _on_output(self, text):
        if not text:
            return False
        buffer = self.log.get_buffer()
        buffer.insert(buffer.get_end_iter(), text)
        buffer.place_cursor(buffer.get_end_iter())
        self.log.scroll_to_mark(buffer.get_insert(), 0, True, 0, 1)

        self._pending += text
        parts = self._pending.splitlines(keepends=True)
        if parts and not parts[-1].endswith(("\n", "\r")):
            self._pending = parts.pop()
        else:
            self._pending = ""
        for line in parts:
            self._note_line(line.strip())
        return False

    def _note_line(self, line):
        match = _PROGRESS.search(line)
        if match:
            done = int(match.group(1))
            total = int(match.group(2))
            self._outcome = "files"
            if self._pulse_id:
                GLib.source_remove(self._pulse_id)
                self._pulse_id = 0
            self.progress.set_fraction(0 if total == 0 else done / total)
            self.progress.set_text(f"{done} of {total} files")
        if line.startswith("No files to download."):
            self._outcome = "empty"
        elif line.startswith("Download completed"):
            self._outcome = "finished"
            self.progress.set_fraction(1)
            self.progress.set_text("Finished")

    def _on_exit(self, code):
        if self._kill_id:
            GLib.source_remove(self._kill_id)
            self._kill_id = 0
        if self._pulse_id:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = 0
        self._job = None
        if self._user_stopped:
            self.progress.set_text("Stopped")
        elif code == 0 and self._outcome == "empty":
            self.progress.set_fraction(0)
            self.progress.set_text("No archived files found")
        elif code == 0:
            self.progress.set_fraction(1)
            self.progress.set_text("Finished")
        else:
            self.progress.set_text("Download failed")
        self._set_running(False)
        return False

    def _set_running(self, running):
        if running:
            self.action_button.grab_focus()
        self.url_entry.set_sensitive(not running)
        self.folder_entry.set_sensitive(not running)
        self.browse_button.set_sensitive(not running)
        self.action_button.set_label("_Stop" if running else "_Download")
        if running:
            self.action_button.remove_css_class("suggested-action")
            self.action_button.add_css_class("destructive-action")
        else:
            self.action_button.remove_css_class("destructive-action")
            self.action_button.add_css_class("suggested-action")

    def _folder_path(self):
        text = self.folder_entry.get_text().strip() or str(Path.home())
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = Path.home() / path
        return path

    def _alert(self, message, detail):
        dialog = Gtk.AlertDialog()
        dialog.set_message(message)
        dialog.set_detail(detail)
        dialog.show(self)

    def _on_close_request(self, *_args):
        if self._job is not None:
            self._user_stopped = True
            self._job.kill()
        return False


class _DownloadJob:
    def __init__(self, argv, on_output, on_exit):
        self.proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            bufsize=0,
        )
        self._on_output = on_output
        self._on_exit = on_exit
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        stream = self.proc.stdout
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            text = decoder.decode(chunk)
            if text:
                GLib.idle_add(self._on_output, text)
        tail = decoder.decode(b"", final=True)
        if tail:
            GLib.idle_add(self._on_output, tail)
        code = self.proc.wait()
        GLib.idle_add(self._on_exit, code)

    def terminate(self):
        self._signal(signal.SIGTERM)

    def kill(self):
        self._signal(signal.SIGKILL)

    def _signal(self, sig):
        if self.proc.poll() is not None:
            return
        try:
            os.killpg(self.proc.pid, sig)
        except ProcessLookupError:
            pass


class WaybackApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()


def _default_folder():
    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        return str(downloads)
    return str(Path.home())


def _install_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(b"textview.log { font-size: 12pt; }\n", -1)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


def main():
    app = WaybackApplication()
    app.connect("startup", lambda *_: _install_css())
    raise SystemExit(app.run(None))
