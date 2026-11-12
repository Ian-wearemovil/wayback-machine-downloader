import unittest

from gui.snapshot import framed_site, resolve_download

_FRAMESET = """
<html>
<head><title>CactusCruisersAMC.org</title></head>
<frameset rows="100%,*" border="0">
  <frame src="http://cactuscruisersamc.org" frameborder="0" />
  <frame frameborder="0" noresize />
</frameset>
</html>
"""

_PASTED = "https://web.archive.org/web/20190719091311/http://www.cactuscruisers.org/"


class SnapshotTargetTest(unittest.TestCase):
    def test_frameset_points_at_the_inner_site(self):
        self.assertEqual(framed_site(_FRAMESET), "http://cactuscruisersamc.org")
        self.assertIsNone(framed_site("<html><a href='http://example.com'>x</a></html>"))

    def test_dated_link_follows_the_frame_and_keeps_the_date(self):
        site, timestamp = resolve_download(_PASTED, fetch=lambda _url: _FRAMESET)
        self.assertEqual(site, "http://cactuscruisersamc.org")
        self.assertEqual(timestamp, "20190719091311")

    def test_same_host_frame_stays_on_the_pasted_site(self):
        html = _FRAMESET.replace("cactuscruisersamc.org", "www.cactuscruisers.org")
        site, timestamp = resolve_download(_PASTED, fetch=lambda _url: html)
        self.assertEqual(site, "http://www.cactuscruisers.org")
        self.assertEqual(timestamp, "20190719091311")

    def test_plain_site_downloads_the_latest_copy(self):
        site, timestamp = resolve_download("http://example.com", fetch=lambda _url: _FRAMESET)
        self.assertEqual(site, "http://example.com")
        self.assertIsNone(timestamp)


if __name__ == "__main__":
    unittest.main()
