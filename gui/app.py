"""GTK window for downloading an archived website."""

import codecs
import os
import re
import signal
import subprocess
import threading
import webbrowser
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from gui.command import download_command
from gui.library import library_file, load_records, remember_download, save_records, visible_sites
from gui.preview import PreviewServer
from gui.snapshot import fetch_snapshot_html, resolve_download
from gui.url_normalize import (
    UrlError,
    destination_directory,
    format_snapshot,
    normalize_site_url,
    site_folder_name,
    snapshot_timestamp,
)

APP_ID = "org.hartator.WaybackMachineDownloader"
_PROGRESS = re.compile(r"\((\d+)/(\d+)\)")


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title="Wayback Machine Downloader")
        self.set_default_size(720, 700)
        self._job = None
        self._pulse_id = 0
        self._kill_id = 0
        self._pending = ""
        self._outcome = None
        self._user_stopped = False
        self._active_site = None
        self._active_destination = None
        self._resolving = False
        self._resolve_token = None
        self._preview = PreviewServer()
        self.site_list = None

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
        self.folder_entry.connect("changed", self._on_folder_changed)
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
        scrolled.set_min_content_height(120)
        scrolled.set_child(self.log)

        sites_label = Gtk.Label(label="Downloaded websites", xalign=0)
        sites_label.add_css_class("heading")
        self.site_list = Gtk.ListBox()
        self.site_list.set_selection_mode(Gtk.SelectionMode.NONE)
        sites_scroll = Gtk.ScrolledWindow()
        sites_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sites_scroll.set_vexpand(True)
        sites_scroll.set_min_content_height(140)
        sites_scroll.set_child(self.site_list)
        self.preview_status = Gtk.Label(xalign=0, wrap=True)
        self.preview_status.add_css_class("dim-label")

        for child in (
            url_label,
            self.url_entry,
            self.hint,
            folder_label,
            folder_row,
            action_row,
            sites_label,
            sites_scroll,
            self.preview_status,
            scrolled,
        ):
            root.append(child)

        self.connect("close-request", self._on_close_request)
        self._refresh_hint()
        self._refresh_sites()

    def _on_url_changed(self, *_args):
        self._refresh_hint()

    def _on_folder_changed(self, *_args):
        self._refresh_hint()
        self._refresh_sites()

    def _refresh_hint(self):
        try:
            site = normalize_site_url(self.url_entry.get_text())
        except UrlError as exc:
            self.hint.set_text(str(exc))
            self.hint.remove_css_class("success")
            return None
        destination = destination_directory(self._folder_path(), site)
        timestamp = snapshot_timestamp(self.url_entry.get_text())
        if timestamp:
            self.hint.set_text(
                f"Saves the {format_snapshot(timestamp)} snapshot in {destination}"
            )
        else:
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
        if self._job is not None or self._resolving:
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
        self._user_stopped = False
        self._outcome = None
        self._pending = ""
        self.log.get_buffer().set_text("")
        self.progress.set_fraction(0)
        self.progress.set_text("Checking the snapshot…")
        self._resolving = True
        self._resolve_token = object()
        self._set_running(True)
        self._pulse_id = GLib.timeout_add(120, self._pulse)
        threading.Thread(
            target=self._resolve_then_launch,
            args=(self.url_entry.get_text(), folder, self._resolve_token),
            daemon=True,
        ).start()

    def _resolve_then_launch(self, raw, folder, token):
        try:
            site, timestamp = resolve_download(raw, fetch=fetch_snapshot_html)
            error = None
        except (UrlError, RuntimeError) as exc:
            site, timestamp, error = None, None, str(exc)
        GLib.idle_add(self._launch_resolved, site, timestamp, folder, token, error)

    def _launch_resolved(self, site, timestamp, folder, token, error):
        if token is not self._resolve_token:
            return False
        self._resolving = False
        if self._user_stopped:
            return False
        if error or not site:
            self._set_running(False)
            self.progress.set_text("")
            self._alert("Check the URL", error or "Enter an http or https website URL.")
            return False
        try:
            argv = download_command(site, folder, to_timestamp=timestamp)
        except RuntimeError as exc:
            self._set_running(False)
            self.progress.set_text("")
            self._alert("Ruby is required", str(exc))
            return False
        destination = destination_directory(folder, site)
        self._active_site = site
        self._active_destination = destination
        if timestamp:
            self.hint.set_text(
                f"Saves the {format_snapshot(timestamp)} snapshot in {destination}"
            )
        self.progress.set_text("Looking up snapshots…")
        self._job = _DownloadJob(argv, self._on_output, self._on_exit)
        return False

    def _stop_download(self):
        self._user_stopped = True
        self._resolve_token = None
        job = self._job
        if job is None:
            self._resolving = False
            if self._pulse_id:
                GLib.source_remove(self._pulse_id)
                self._pulse_id = 0
            self.progress.set_text("Stopped")
            self._set_running(False)
            return
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
        if self._outcome == "files" or (self._job is None and not self._resolving):
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
        if code == 0 and self._outcome != "empty" and self._active_destination is not None:
            self._remember_finished_download()
        self._set_running(False)
        return False

    def _remember_finished_download(self):
        folder = self._active_destination
        if folder is None or not (folder / "index.html").is_file():
            return
        path = library_file()
        records = remember_download(
            load_records(path),
            site_folder_name(self._active_site),
            self._active_site,
            folder,
        )
        save_records(path, records)
        self._refresh_sites()

    def _refresh_sites(self):
        if self.site_list is None:
            return
        while (child := self.site_list.get_first_child()) is not None:
            self.site_list.remove(child)
        sites = visible_sites(load_records(library_file()), self._folder_path())
        if not sites:
            self.site_list.append(self._message_row("Websites you download appear here."))
            return
        for site in sites:
            self.site_list.append(self._site_row(site))

    def _message_row(self, text):
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)
        label = Gtk.Label(label=text, xalign=0)
        label.set_margin_top(8)
        label.set_margin_bottom(8)
        label.set_margin_start(8)
        label.set_margin_end(8)
        label.add_css_class("dim-label")
        row.set_child(label)
        return row

    def _site_row(self, site):
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)
        box = Gtk.Box(spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        title = Gtk.Label(label=site["name"], xalign=0)
        path = Gtk.Label(label=site["path"], xalign=0)
        path.add_css_class("dim-label")
        path.set_ellipsize(Pango.EllipsizeMode.START)
        path.set_max_width_chars(48)
        text.append(title)
        text.append(path)
        button = Gtk.Button(label="Live view")
        button.connect("clicked", self._on_live_view, site["path"])
        box.append(text)
        box.append(button)
        row.set_child(box)
        return row

    def _on_live_view(self, _button, folder):
        try:
            url = self._preview.serve(folder)
        except OSError as exc:
            self._alert("Could not open the site", str(exc))
            return
        self.preview_status.set_text(f"Live view at {url}")
        webbrowser.open(url)

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
        self._preview.stop()
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
