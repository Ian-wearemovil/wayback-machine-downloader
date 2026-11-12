"""Choose the site and date a pasted Wayback link should download."""

import re
import urllib.error
import urllib.request

from gui.url_normalize import (
    UrlError,
    normalize_site_url,
    snapshot_page_url,
    snapshot_timestamp,
)

_FRAME_SRC = re.compile(
    r"""<frame\b[^>]*\bsrc\s*=\s*(["'])(.*?)\1""",
    re.IGNORECASE | re.DOTALL,
)


def framed_site(html):
    """Return the other site shown inside a full-page frameset, if any."""
    if not html or not re.search(r"<frameset\b", html, re.IGNORECASE):
        return None
    match = _FRAME_SRC.search(html)
    if not match:
        return None
    src = match.group(2).strip()
    if src.startswith("http://") or src.startswith("https://"):
        return src
    return None


def fetch_snapshot_html(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "wayback-machine-downloader"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(500_000).decode("utf-8", "replace")


def resolve_download(raw, fetch=None):
    """Return ``(site_url, timestamp_or_none)`` for a pasted URL.

    A dated Wayback link keeps that timestamp. When that exact page is only
    a frame around another site, the framed site is what gets downloaded.
    """
    site = normalize_site_url(raw)
    timestamp = snapshot_timestamp(raw)
    page = snapshot_page_url(raw) if timestamp and fetch is not None else None
    if page:
        try:
            html = fetch(page)
        except (OSError, urllib.error.URLError, TimeoutError, ValueError):
            html = ""
        framed = framed_site(html)
        if framed:
            try:
                framed_origin = normalize_site_url(framed)
            except UrlError:
                framed_origin = None
            if framed_origin and framed_origin != site:
                site = framed_origin
    return site, timestamp
