"""Turn a pasted site or Wayback Machine link into the site the CLI downloads."""

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


def _original_from_wayback(parsed):
    path = parsed.path or ""
    prefix = "/web/"
    if not path.startswith(prefix):
        raise UrlError("That Wayback link does not include a website.")

    rest = path[len(prefix):]
    head, sep, tail = rest.partition("/")
    timestamp = head[:-3] if head.endswith("id_") else head
    if sep and (timestamp.isdigit() or head == "*"):
        original = tail
    elif rest.startswith("http://") or rest.startswith("https://"):
        original = rest
    else:
        raise UrlError("That Wayback link does not include a website.")

    if original.startswith("http://") or original.startswith("https://"):
        return original
    if original.startswith("//"):
        return "http:" + original
    return "http://" + original


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
