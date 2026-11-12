"""Turn a pasted site or Wayback Machine link into the site the CLI downloads."""

from pathlib import Path
from urllib.parse import urlparse

WAYBACK_HOSTS = frozenset(
    {
        "web.archive.org",
        "www.web.archive.org",
        "archive.org",
        "www.archive.org",
    }
)


class UrlError(ValueError):
    """The pasted text is not a site URL or a Wayback Machine link."""


def normalize_site_url(raw):
    """Return the http(s) origin that should be downloaded in full.

    A Wayback Machine link such as
    ``https://web.archive.org/web/20100916231334/http://example.com/index.html``
    becomes ``http://example.com``. A plain site URL is reduced to its origin
    so the downloader retrieves the whole archived site.
    """
    text = (raw or "").strip()
    if not text:
        raise UrlError("Paste a site URL or a Wayback Machine link.")

    if "://" not in text:
        text = "http://" + text

    parsed = urlparse(text)
    host = _hostname(parsed)
    if host in WAYBACK_HOSTS:
        original = _original_from_wayback(parsed)
        parsed = urlparse(original)
        host = _hostname(parsed)

    return _origin(parsed, host)


def _hostname(parsed):
    host = (parsed.hostname or "").lower().rstrip(".")
    return host


def snapshot_timestamp(raw):
    """Return the Wayback timestamp from a pasted link, or None.

    ``https://web.archive.org/web/20190719091311/http://www.cactuscruisers.org/``
    returns ``20190719091311``. A plain site URL has no snapshot time.
    """
    text = (raw or "").strip()
    if "://" not in text:
        text = "http://" + text
    parsed = urlparse(text)
    if _hostname(parsed) not in WAYBACK_HOSTS:
        return None
    _original, timestamp = _wayback_target(parsed)
    return timestamp


def format_snapshot(timestamp):
    """Return a readable date for a Wayback timestamp, such as ``July 19, 2019``."""
    months = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    if len(timestamp) >= 8 and timestamp[:8].isdigit():
        year, month, day = int(timestamp[:4]), int(timestamp[4:6]), int(timestamp[6:8])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{months[month - 1]} {day}, {year}"
    if len(timestamp) >= 6 and timestamp[:6].isdigit():
        year, month = int(timestamp[:4]), int(timestamp[4:6])
        if 1 <= month <= 12:
            return f"{months[month - 1]} {year}"
    if len(timestamp) >= 4 and timestamp[:4].isdigit():
        return timestamp[:4]
    return timestamp


def snapshot_page_url(raw):
    """Return the original-content URL for a timestamped Wayback link."""
    text = (raw or "").strip()
    if "://" not in text:
        text = "http://" + text
    parsed = urlparse(text)
    if _hostname(parsed) not in WAYBACK_HOSTS:
        return None
    original, timestamp = _wayback_target(parsed)
    if not original or not timestamp:
        return None
    return f"https://web.archive.org/web/{timestamp}id_/{original}"


def _wayback_target(parsed):
    """Return ``(original_url, timestamp_or_none)`` from a Wayback path."""
    path = parsed.path or ""
    prefix = "/web/"
    if not path.startswith(prefix):
        raise UrlError("That Wayback link does not include a website.")

    rest = path[len(prefix):]
    head, sep, tail = rest.partition("/")
    timestamp = head[:-3] if head.endswith("id_") else head
    if sep and (timestamp.isdigit() or head == "*"):
        original = tail
        stamp = timestamp if timestamp.isdigit() else None
    elif rest.startswith("http://") or rest.startswith("https://"):
        original = rest
        stamp = None
    else:
        raise UrlError("That Wayback link does not include a website.")

    if original.startswith("//"):
        original = "http:" + original
    elif not original.startswith("http://") and not original.startswith("https://"):
        original = "http://" + original
    return original, stamp


def _original_from_wayback(parsed):
    original, _timestamp = _wayback_target(parsed)
    return original


def _origin(parsed, host):
    if parsed.scheme not in ("http", "https") or not host:
        raise UrlError("Enter an http or https website URL.")

    port = parsed.port
    default_port = 80 if parsed.scheme == "http" else 443
    if port and port != default_port:
        netloc = f"{host}:{port}"
    else:
        netloc = host
    return f"{parsed.scheme}://{netloc}"


def site_folder_name(site_url):
    """Directory name for a normalized site URL, such as ``arcgps.com``."""
    name = urlparse(site_url).netloc
    if not name:
        raise UrlError("Enter an http or https website URL.")
    return name


def destination_directory(parent, site_url):
    """Return ``parent/arcgps.com`` for a site URL and a chosen parent folder."""
    return Path(parent) / site_folder_name(site_url)
