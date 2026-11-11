import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from gui.preview import PreviewServer


_MENU = """
<ul>
  <li class="page_item page-item-47 page_item_has_children">
    <a href="/products.html"><span class="icon"></span>Products</a>
    <ul class="children">
      <li class="page_item page-item-51"><a href="/assets.html">Asset Tracking</a></li>
      <li class="page_item page-item-53"><a href="/fleettracking.html">Fleet Tracking</a></li>
    </ul>
  </li>
  <li class="page_item page-item-32">
    <a href="/aboutus.html">About Us</a>
  </li>
  <li class="page_item page-item-32">
    <a href="/blog.html">Blog</a>
  </li>
  <li class="page_item page-item-13">
    <a href="https://arcgps.com/contact.html">Contact Us</a>
  </li>
</ul>
"""


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

    def test_follows_saved_pages_when_the_link_uses_another_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "arcgps.com"
            site.mkdir()
            (site / "index.html").write_text(_MENU + "<h1>Home</h1>", encoding="utf-8")
            (site / "blog.html").write_text("<h1>Blog</h1>", encoding="utf-8")
            (site / "contact.html").write_text("<h1>Contact file</h1>", encoding="utf-8")
            about = site / "about"
            about.mkdir()
            (about / "index.html").write_text("<h1>About folder</h1>", encoding="utf-8")
            (site / "plain.html").write_text("<h1>Plain</h1>", encoding="utf-8")
            css = site / "wp-content" / "themes"
            css.mkdir(parents=True)
            (css / "style.css?ver=1.4.4").write_text("body{color:red}", encoding="utf-8")
            for page_id, title in (
                ("47", "Products"),
                ("51", "Asset Tracking"),
                ("53", "Fleet Tracking"),
                ("32", "About Us"),
                ("13", "Contact Us"),
            ):
                folder = site / f"?page_id={page_id}"
                folder.mkdir()
                extra = ""
                if page_id == "47":
                    extra = (
                        '<a href="http://arcgps.com/?page_id=51">Asset Tracking</a>'
                        '<a href="https://siteorigin.com">Out</a>'
                    )
                (folder / "index.html").write_text(
                    f"<h1>{title}</h1>{extra}", encoding="utf-8"
                )
            windows = site / "win"
            windows.mkdir()
            (windows / "style.css%3fver%3d9").write_text("windows-css", encoding="utf-8")

            server = PreviewServer()
            try:
                base = server.serve(site)
                self.assertIn("<h1>Home</h1>", _read(base))
                products = _read(base + "products.html")
                self.assertIn("<h1>Products</h1>", products)
                self.assertIn('href="/?page_id=51"', products)
                self.assertNotIn("http://arcgps.com/", products)
                self.assertIn('href="https://siteorigin.com"', products)
                self.assertEqual(_title(base + "products.html"), "Products")
                self.assertEqual(_title(base + "assets.html"), "Asset Tracking")
                self.assertEqual(_title(base + "fleettracking.html"), "Fleet Tracking")
                self.assertEqual(_title(base + "aboutus.html"), "About Us")
                self.assertEqual(_title(base + "blog.html"), "Blog")
                self.assertEqual(_title(base + "contact.html"), "Contact file")
                self.assertEqual(_title(base + "?page_id=47"), "Products")
                self.assertEqual(_title(base + "about/"), "About folder")
                self.assertEqual(_title(base + "about"), "About folder")
                self.assertEqual(_title(base + "about.html"), "About folder")
                self.assertEqual(_title(base + "plain"), "Plain")
                css_body, css_type = _read_type(base + "wp-content/themes/style.css?ver=1.4.4")
                self.assertEqual(css_body, "body{color:red}")
                self.assertEqual(css_type, "text/css")
                self.assertEqual(_read(base + "wp-content/themes/style.css"), "body{color:red}")
                self.assertEqual(_read(base + "win/style.css?ver=9"), "windows-css")
                self.assertIn(
                    "Nothing matches the given URI",
                    _error(base + "missing.html"),
                )
                self.assertIn("File not found", _error(base + "%2e%2e/%2e%2e/etc/passwd"))
            finally:
                server.stop()


def _read(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _read_type(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8"), response.headers.get_content_type()


def _title(url):
    text = _read(url)
    start = text.index("<h1>") + 4
    return text[start:text.index("</h1>")]


def _error(url):
    try:
        urllib.request.urlopen(url, timeout=5)
    except urllib.error.HTTPError as error:
        return error.read().decode("utf-8")
    raise AssertionError(f"{url} was found")


if __name__ == "__main__":
    unittest.main()
