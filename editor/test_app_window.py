"""Build ma własne okno. Zapis pliku idzie do Pobranych, obcy link nie startuje przeglądarki sam z siebie."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_window


class AppWindowTests(unittest.TestCase):
    def test_source_run_stays_in_the_browser(self):
        with patch.object(app_window.sys, "frozen", False, create=True):
            os.environ.pop("NJR_WINDOW", None)
            os.environ.pop("NJR_NO_BROWSER", None)
            self.assertFalse(app_window.use_own_window())

    def test_build_uses_its_own_window(self):
        with patch.object(app_window.sys, "frozen", True, create=True):
            os.environ.pop("NJR_WINDOW", None)
            os.environ.pop("NJR_NO_BROWSER", None)
            self.assertTrue(app_window.use_own_window())

    def test_save_writes_the_file_in_downloads(self):
        api = app_window.WindowApi()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with patch.object(Path, "home", return_value=Path(folder.name)):
            with patch.object(app_window, "_reveal"):
                path = api.begin_save("lista.xml")
                api.write_chunk("aGVsbG8=")
                api.finish_save()
        written = Path(path)
        self.assertEqual(written.name, "lista.xml")
        self.assertEqual(written.read_text(encoding="utf-8"), "hello")
        self.assertTrue(str(written).startswith(folder.name))

    def test_external_link_must_be_http(self):
        api = app_window.WindowApi()
        with patch("app_window.webbrowser.open") as opened:
            self.assertFalse(api.open_external("file:///etc/passwd"))
            self.assertFalse(opened.called)
            self.assertTrue(api.open_external("https://nowajakoscrozrywki.pl/moje-konto/"))
            opened.assert_called_once()


if __name__ == "__main__":
    unittest.main()
