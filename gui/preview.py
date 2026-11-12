"""Serve one downloaded site on localhost for a live view.

Archived pages are not always stored at the address used in the HTML.
Extension-less URLs become ``path/index.html``, query strings stay in the
file name (``style.css?ver=1`` or, on Windows, ``style.css%3fver%3d1``), and
WordPress menus often link to ``/products.html`` while the only capture is
``/?page_id=47``, saved as a folder named ``?page_id=47``.
"""

import io
import os
import posixpath
import re
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

_PAGE_ITEM_HREF = re.compile(
    r"page-item-(\d+)\b[^>]*>\s*<a\b[^>]*?\bhref\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_ANCHOR = re.compile(r"<a\b([^>]*)>", re.IGNORECASE)
_HREF_ATTR = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_PAGE_ITEM_ATTR = re.compile(r"page-item-(\d+)\b", re.IGNORECASE)
_QUERY_IN_NAME = re.compile(r"\?|%3f", re.IGNORECASE)
_ATTR_URL = re.compile(
    r"""(?P<attr>\b(?:href|src|action)\s*=\s*)(?P<q>["'])(?P<url>.*?)(?P=q)""",
    re.IGNORECASE | re.DOTALL,
)
_SPECIAL = ":*?&=<>\\|"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


def _encode_special(text):
    """Match the downloader's Windows file-name encoding."""
    return "".join(f"%{ord(char):x}" if char in _SPECIAL else char for char in text)


def _safe_relative(url_path):
    """Return a relative path, or None when it would leave the site folder."""
    try:
        raw = unquote(url_path, errors="surrogatepass")
    except UnicodeDecodeError:
        raw = unquote(url_path)
    if "\x00" in raw:
        return None
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    return "/".join(parts)


def _inside(root, candidate):
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _join(root, relative):
    if not relative:
        return root
    return root.joinpath(*relative.split("/"))


def _index_file(directory):
    if not directory.is_dir():
        return None
    for name in ("index.html", "index.htm"):
        candidate = directory / name
        if candidate.is_file() and _inside(directory, candidate):
            return candidate
    return None


def _query_names(query):
    names = []
    for variant in (query, unquote(query)):
        raw = "?" + variant
        encoded = _encode_special(raw)
        for name in (raw, encoded):
            if name not in names:
                names.append(name)
    return names


def _match_query(root, relative, query):
    """Find the file or folder saved from a URL that included ``?query``."""
    for name in _query_names(query):
        candidate = _join(root, f"{relative}{name}" if relative else name)
        if not _inside(root, candidate):
            continue
        if candidate.is_file() or _index_file(candidate) is not None:
            return candidate
    return None


def _query_filename(root, relative, query):
    """Find ``style.css?ver=1`` when the browser asked for ``style.css``."""
    if not relative:
        return None
    parent_rel, _, name = relative.rpartition("/")
    parent = _join(root, parent_rel)
    if not parent.is_dir():
        return None
    prefix = name.lower()
    matches = []
    try:
        entries = list(parent.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.is_file() or not _inside(root, entry):
            continue
        lowered = entry.name.lower()
        if not lowered.startswith(prefix):
            continue
        if _QUERY_IN_NAME.match(lowered[len(prefix):]):
            matches.append(entry)
    if query:
        wanted = {suffix.lower() for suffix in _query_names(query)}
        exact = [entry for entry in matches if entry.name[len(name):].lower() in wanted]
        if exact:
            matches = exact
    if not matches:
        return None
    matches.sort(key=lambda entry: entry.name)
    return matches[-1]


def _href_key(href):
    href = href.strip()
    if not href or href.startswith(("#", "mailto:", "javascript:", "data:")):
        return None
    parsed = urlsplit(href)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return None
    return _safe_relative(parsed.path)


def _html_files(root):
    found = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for name in filenames:
            if found >= 4000:
                return
            if name.lower().endswith((".html", ".htm")):
                found += 1
                yield Path(dirpath) / name


def _page_links(text):
    for match in _PAGE_ITEM_HREF.finditer(text):
        yield match.group(1), match.group(2)
    for match in _ANCHOR.finditer(text):
        attrs = match.group(1)
        item = _PAGE_ITEM_ATTR.search(attrs)
        href = _HREF_ATTR.search(attrs)
        if item and href:
            yield item.group(1), href.group(1)


def _saved_page(root, page_id):
    for name in _query_names(f"page_id={page_id}"):
        folder = root / name
        index = _index_file(folder)
        if index is not None and _inside(root, index):
            return index
    return None


def build_page_aliases(root):
    """Map menu links onto the ``?page_id=`` capture when that is all that exists.

    WordPress ``wp_list_pages`` writes ``page-item-47`` on the list item and
    ``href="/products.html"`` on the link. The archive often has
    ``/?page_id=47`` and never captured ``/products.html``.
    """
    root = Path(root)
    aliases = {}
    for html in _html_files(root):
        try:
            with html.open("r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read(1_000_000)
        except OSError:
            continue
        if "page-item-" not in text:
            continue
        for page_id, href in _page_links(text):
            key = _href_key(href)
            if not key or key in aliases:
                continue
            target = _join(root, key)
            if target.exists():
                continue
            saved = _saved_page(root, page_id)
            if saved is not None:
                aliases[key] = saved
    return aliases


def resolve_preview_path(root, request_target, aliases):
    """Return the saved file or directory for one browser request, or None."""
    root = Path(root)
    parsed = urlsplit(request_target)
    relative = _safe_relative(parsed.path)
    if relative is None:
        return None

    if parsed.query:
        matched = _match_query(root, relative, parsed.query)
        if matched is not None:
            return matched

    if relative == "":
        return root

    candidate = _join(root, relative)
    if not _inside(root, candidate):
        return None
    if candidate.is_file() or candidate.is_dir():
        return candidate

    for extension in (".html", ".htm"):
        if relative.lower().endswith(extension):
            continue
        sibling = _join(root, relative + extension)
        if sibling.is_file() and _inside(root, sibling):
            return sibling

    variant = _query_filename(root, relative, parsed.query)
    if variant is not None:
        return variant

    aliased = aliases.get(relative.rstrip("/"))
    if aliased is not None and aliased.is_file() and _inside(root, aliased):
        return aliased

    for extension in (".html", ".htm"):
        if relative.lower().endswith(extension):
            stem = relative[: -len(extension)].rstrip("/")
            index = _index_file(_join(root, stem))
            if index is not None and _inside(root, index):
                return index
    return None


def site_hosts(directory):
    """Host names whose links should stay on the localhost preview."""
    bare = Path(directory).name.lower().split(":", 1)[0]
    hosts = {bare}
    if bare.startswith("www."):
        hosts.add(bare[4:])
    elif bare:
        hosts.add("www." + bare)
    return hosts


def _localize(url, hosts):
    stripped = url.strip()
    if stripped.startswith("//"):
        parsed = urlsplit("http:" + stripped)
    else:
        parsed = urlsplit(stripped)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in hosts:
        return None
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return path + query + fragment


def rewrite_local_links(text, hosts):
    """Point same-site absolute links at this preview instead of the live host."""

    def replace(match):
        localized = _localize(match.group("url"), hosts)
        if localized is None:
            return match.group(0)
        quote = match.group("q")
        return f"{match.group('attr')}{quote}{localized}{quote}"

    return _ATTR_URL.sub(replace, text)


def _handler_for(directory):
    root = str(directory)
    aliases = build_page_aliases(directory)
    hosts = site_hosts(directory)

    class Handler(_QuietHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=root, **kwargs)

        def translate_path(self, path):
            resolved = resolve_preview_path(self.directory, path, aliases)
            if resolved is None:
                return os.path.join(self.directory, ".wayback-preview-missing")
            return str(resolved)

        def guess_type(self, path):
            name = posixpath.basename(path)
            name = _QUERY_IN_NAME.split(name, maxsplit=1)[0]
            return super().guess_type(name)

        def send_head(self):
            path = self.translate_path(self.path)
            if os.path.isdir(path):
                parts = urlsplit(self.path)
                if not parts.path.endswith("/"):
                    return super().send_head()
                for index in ("index.html", "index.htm"):
                    index_path = os.path.join(path, index)
                    if os.path.isfile(index_path):
                        path = index_path
                        break
                else:
                    return super().send_head()
            if path.lower().endswith((".html", ".htm")) and os.path.isfile(path):
                return self._send_html(path)
            return super().send_head()

        def _send_html(self, path):
            try:
                with open(path, "rb") as handle:
                    data = handle.read()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                return None
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is not None and "http" in text:
                data = rewrite_local_links(text, hosts).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return io.BytesIO(data)

    return Handler


class PreviewServer:
    """One local server. Starting a different site replaces the previous one."""

    def __init__(self):
        self._httpd = None
        self._thread = None
        self._directory = None
        self.url = None

    def serve(self, directory):
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise FileNotFoundError(f"No downloaded site at {directory}")
        if self._httpd is not None and self._directory == directory and self.url:
            return self.url
        self.stop()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(directory))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self._httpd = httpd
        self._thread = thread
        self._directory = directory
        host, port = httpd.server_address
        self.url = f"http://{host}:{port}/"
        return self.url

    def stop(self):
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None
        self._directory = None
        self.url = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=3)
