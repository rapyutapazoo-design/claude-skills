"""取りに行く URL が http / https に限られることを検査する（claude skills での追加）。"""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(f"urlsafety_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load("fetch")
watch = load("watch")

UNSAFE = (
    "",
    "file:///etc/passwd",
    "ftp://example.test/a",
    "--exec=touch /tmp/x #youtube.com/watch?v=x",
    "--exec=id#youtube.com/watch?v=x",
    "-o /tmp/x https://youtube.com/watch?v=x",
    "https://example.test/a b",
    "https://example.test/a\n--exec=x",
    "https:///no-host",
    "javascript:alert(1)",
)


class UrlSafetyTests(unittest.TestCase):
    def test_safe_url_accepts_http_and_https(self):
        for module in (fetch, watch):
            for url in ("https://example.test/a", "http://example.test/a?q=1#x",
                        "https://www.youtube.com/watch?v=abc"):
                with self.subTest(module=module.__name__, url=url):
                    self.assertTrue(module.safe_url(url))

    def test_safe_url_rejects_other_schemes_and_option_like_strings(self):
        for module in (fetch, watch):
            for url in UNSAFE:
                with self.subTest(module=module.__name__, url=url):
                    self.assertFalse(module.safe_url(url))

    def test_fetch_source_fails_before_any_command_or_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources = Path(tmp)
            for url in UNSAFE:
                with self.subTest(url=url), \
                        patch.object(fetch, "download") as download, \
                        patch.object(fetch.subprocess, "run") as run, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(fetch.fetch_source(sources, "paper", url, sources), 1)
                    self.assertIn("FAIL\t", output.getvalue())
                    download.assert_not_called()
                    run.assert_not_called()

    def test_download_and_watch_fetch_refuse_unsafe_urls(self):
        for func in (fetch.download, watch.fetch):
            with self.subTest(func=func.__module__), \
                    patch.object(fetch._OPENER, "open") as fopen, \
                    patch.object(watch._OPENER, "open") as wopen:
                with self.assertRaises(ValueError):
                    func("file:///etc/passwd")
                fopen.assert_not_called()
                wopen.assert_not_called()

    def test_redirect_to_non_http_is_refused(self):
        for module in (fetch, watch):
            handler = module._Redirect308()
            with self.subTest(module=module.__name__):
                with self.assertRaises(module.urllib.error.HTTPError):
                    handler.redirect_request(None, None, 302, "Found", {}, "file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
