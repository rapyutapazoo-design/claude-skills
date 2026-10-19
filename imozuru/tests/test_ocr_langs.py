"""OCR の言語指定（jpn があれば eng+jpn、無ければ eng）を検査する（claude skills での追加）。"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(f"ocrlangs_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load("fetch")

WITH_JPN = "List of available languages in \"/x\" (3):\neng\njpn\nosd\n"
NO_JPN = "List of available languages in \"/x\" (2):\neng\nosd\n"


def langs_with(run):
    fetch._OCR_LANGS = None
    with patch.object(fetch.subprocess, "run", run):
        return fetch.ocr_langs()


def ok(out):
    return lambda *a, **k: SimpleNamespace(returncode=0, stdout=out, stderr="")


class OcrLangsTests(unittest.TestCase):
    def tearDown(self):
        fetch._OCR_LANGS = None

    def test_jpn_present(self):
        self.assertEqual(langs_with(ok(WITH_JPN)), "eng+jpn")

    def test_jpn_absent(self):
        self.assertEqual(langs_with(ok(NO_JPN)), "eng")

    def test_nonzero_exit(self):
        run = lambda *a, **k: SimpleNamespace(returncode=1, stdout=WITH_JPN, stderr="")
        self.assertEqual(langs_with(run), "eng")

    def test_exception(self):
        def run(*a, **k):
            raise FileNotFoundError("tesseract")
        self.assertEqual(langs_with(run), "eng")

    def test_jpn_vert_only(self):
        out = "List of available languages in \"/x\" (2):\neng\njpn_vert\n"
        self.assertEqual(langs_with(ok(out)), "eng")

    def test_cached_single_call(self):
        fetch._OCR_LANGS = None
        calls = []

        def run(*a, **k):
            calls.append(a)
            return SimpleNamespace(returncode=0, stdout=WITH_JPN, stderr="")

        with patch.object(fetch.subprocess, "run", run):
            self.assertEqual(fetch.ocr_langs(), "eng+jpn")
            self.assertEqual(fetch.ocr_langs(), "eng+jpn")
        self.assertEqual(len(calls), 1)

    def test_ocr_passes_lang_to_tesseract(self):
        for out, expected in ((WITH_JPN, "eng+jpn"), (NO_JPN, "eng")):
            fetch._OCR_LANGS = None
            calls = []
            with tempfile.TemporaryDirectory() as d:
                pdf = Path(d) / "a.pdf"
                pdf.write_bytes(b"%PDF")

                def run(cmd, *a, **k):
                    calls.append(cmd)
                    if cmd[0] == "pdftoppm":
                        Path(cmd[-1] + "-1.png").write_bytes(b"x")
                    return SimpleNamespace(returncode=0, stdout=out if "--list-langs" in cmd
                                           else "text", stderr="")

                with patch.object(fetch, "missing", lambda *c: []), \
                        patch.object(fetch.subprocess, "run", run):
                    fetch.ocr_pdf(pdf)
            ocr = [c for c in calls if c[0] == "tesseract" and "--list-langs" not in c]
            self.assertEqual(len(ocr), 1)
            self.assertEqual(ocr[0][ocr[0].index("-l") + 1], expected)


if __name__ == "__main__":
    unittest.main()
