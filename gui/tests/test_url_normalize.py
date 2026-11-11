import unittest

from gui.url_normalize import UrlError, normalize_site_url


class NormalizeSiteUrlTest(unittest.TestCase):
    def test_plain_site_url_keeps_the_origin(self):
        self.assertEqual(normalize_site_url("http://example.com"), "http://example.com")

    def test_https_site_with_a_path_downloads_the_whole_origin(self):
        self.assertEqual(
            normalize_site_url("https://example.com/docs/page"),
            "https://example.com",
        )

    def test_missing_scheme_defaults_to_http(self):
        self.assertEqual(normalize_site_url("example.com"), "http://example.com")

    def test_wayback_timestamp_link(self):
        pasted = "https://web.archive.org/web/20100916231334/http://example.com/index.html"
        self.assertEqual(normalize_site_url(pasted), "http://example.com")

    def test_wayback_identity_link_and_https_origin(self):
        pasted = "https://web.archive.org/web/20201101000000id_/https://example.com/a/b"
        self.assertEqual(normalize_site_url(pasted), "https://example.com")

    def test_wayback_wildcard_link(self):
        pasted = "https://web.archive.org/web/*/http://blog.example.com/posts/1"
        self.assertEqual(normalize_site_url(pasted), "http://blog.example.com")

    def test_wayback_link_without_a_timestamp(self):
        pasted = "https://web.archive.org/web/http://example.com"
        self.assertEqual(normalize_site_url(pasted), "http://example.com")

    def test_nondefault_port_is_kept(self):
        pasted = "https://web.archive.org/web/2020/http://example.com:8080/app"
        self.assertEqual(normalize_site_url(pasted), "http://example.com:8080")

    def test_default_port_is_dropped(self):
        self.assertEqual(normalize_site_url("https://example.com:443/x"), "https://example.com")

    def test_surrounding_whitespace(self):
        self.assertEqual(normalize_site_url("  http://example.com/  "), "http://example.com")

    def test_empty_text(self):
        with self.assertRaises(UrlError):
            normalize_site_url("   ")

    def test_wayback_link_without_a_site(self):
        with self.assertRaises(UrlError):
            normalize_site_url("https://web.archive.org/web/20100916231334/")

    def test_unsupported_scheme(self):
        with self.assertRaises(UrlError):
            normalize_site_url("ftp://example.com")


if __name__ == "__main__":
    unittest.main()
