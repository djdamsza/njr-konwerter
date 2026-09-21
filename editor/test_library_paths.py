#!/usr/bin/env python3
"""Wykrywanie ścieżek Engine/Patriot/VDJ na Windows vs macOS."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import library_paths as lp


def _fake_engine_lib(root: Path) -> Path:
    lib = root / "Engine Library"
    (lib / "Database2").mkdir(parents=True)
    (lib / "Database2" / "m.db").write_bytes(b"sqlite")
    return lib


class TestPatriotDetection(unittest.TestCase):
    def test_env_njr_patriot_engine_wins(self):
        with tempfile.TemporaryDirectory() as td:
            lib = _fake_engine_lib(Path(td) / "Patriot")
            with patch.dict(os.environ, {"NJR_PATRIOT_ENGINE": str(lib)}):
                self.assertEqual(lp.detect_patriot_engine_library(), lib.resolve())
                self.assertTrue(lp.is_engine_library_dir(lib))

    def test_windows_never_defaults_to_macos_volumes(self):
        os.environ.pop("NJR_PATRIOT_ENGINE", None)
        with patch.object(lp.platform, "system", return_value="Windows"):
            with patch.object(lp, "detect_patriot_engine_library", return_value=None):
                out = lp.default_patriot_engine()
        self.assertEqual(out, lp.WINDOWS_PATRIOT_FALLBACK)
        self.assertFalse(str(out).replace("\\", "/").startswith("/Volumes/"))

    def test_macos_fallback_is_volumes_patriot(self):
        os.environ.pop("NJR_PATRIOT_ENGINE", None)
        with patch.object(lp.platform, "system", return_value="Darwin"):
            with patch.object(lp, "detect_patriot_engine_library", return_value=None):
                self.assertEqual(lp.default_patriot_engine(), lp.MACOS_PATRIOT_ENGINE)

    def test_windows_prefers_patriot_volume_label(self):
        with tempfile.TemporaryDirectory() as td:
            patriot = _fake_engine_lib(Path(td) / "P")
            other = _fake_engine_lib(Path(td) / "O")
            pairs = [
                (other, "Data"),
                (patriot, "Patriot"),
            ]
            desktop = Path(td) / "Music" / "Engine Library"
            with patch.object(lp.platform, "system", return_value="Windows"):
                with patch.object(lp, "default_engine_desktop_library", return_value=desktop):
                    with patch.object(lp, "_windows_volume_candidates", return_value=pairs):
                        found = lp.list_patriot_engine_candidates(require_database=True)
            self.assertEqual(found[0], patriot.resolve())

    def test_skips_desktop_library(self):
        with tempfile.TemporaryDirectory() as td:
            desktop = _fake_engine_lib(Path(td) / "Music")
            with patch.object(lp.platform, "system", return_value="Darwin"):
                with patch.object(lp, "default_engine_desktop_library", return_value=desktop):
                    with patch.object(
                        lp,
                        "_macos_volume_candidates",
                        return_value=[(desktop, "Macintosh HD")],
                    ):
                        self.assertEqual(
                            lp.list_patriot_engine_candidates(require_database=True),
                            [],
                        )

    def test_resolve_explicit_path(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "Engine Library"
            p.mkdir()
            self.assertEqual(lp.resolve_patriot_engine(p), p.resolve())

    def test_runtime_payload_keys(self):
        payload = lp.runtime_library_paths()
        for key in (
            "platform",
            "engine_desktop",
            "patriot_engine",
            "patriot_mounted",
            "vdj_database",
            "serato_dir",
            "close_engine_hint",
            "close_all_dj_hint",
        ):
            self.assertIn(key, payload)

    def test_windows_vdj_prefers_documents(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            docs = home / "Documents" / "VirtualDJ"
            docs.mkdir(parents=True)
            (docs / "database.xml").write_text("<VirtualDJ_Database />", encoding="utf-8")
            env = {"LOCALAPPDATA": str(home / "AppData" / "Local")}
            with patch.object(lp.platform, "system", return_value="Windows"):
                with patch.object(lp.Path, "home", return_value=home):
                    with patch.dict(os.environ, env, clear=False):
                        self.assertEqual(lp.default_vdj_base(), docs)

    def test_close_hint_windows(self):
        with patch.object(lp.platform, "system", return_value="Windows"):
            hint = lp.close_engine_hint()
            self.assertIn("Menedżer zadań", hint)
            self.assertNotIn("Cmd+Q", hint)


class TestLibraryPathsApi(unittest.TestCase):
    def test_api_library_paths(self):
        from app import app

        client = app.test_client()
        r = client.get("/api/library-paths")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertIn("patriot_engine", d)
        self.assertIn("engine_desktop", d)
        self.assertIn("version", d)

    def test_api_diagnose_patriot_missing_drive(self):
        from app import app

        client = app.test_client()
        r = client.get("/api/diagnose-patriot-library?patriotEngine=/tmp/njr-no-such-patriot")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertIn("patriot_mounted", d)
        self.assertFalse(d.get("patriot_mounted"))


if __name__ == "__main__":
    unittest.main()
