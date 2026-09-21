#!/usr/bin/env python3
"""Otwieranie biblioteki Serato z folderu / database V2 — bez ZIP."""
from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from serato_parser import (
    _encode_utf16be,
    _write_serato_record,
    default_serato_drive_root,
    load_serato_folder,
    looks_like_serato_database_v2,
    resolve_serato_library_dir,
    save_serato_crate,
    save_serato_database_v2,
)


def _db_bytes(path: str = "Users/test/Desktop/a.mp3") -> bytes:
    return save_serato_database_v2(
        [{"FilePath": "/" + path, "Tags.Title": "A", "Tags.Author": "DJ"}],
        drive_root="/",
        path_style="relative",
    )


def _write_library(root: Path, crate: bool = True) -> Path:
    serato = root / "_Serato_"
    (serato / "Subcrates").mkdir(parents=True)
    (serato / "database V2").write_bytes(_db_bytes())
    if crate:
        raw = save_serato_crate(
            ["/Users/test/Desktop/a.mp3"],
            "Warmup",
            drive_root="/",
            existing_files_only=False,
        )
        (serato / "Subcrates" / "Warmup.crate").write_bytes(raw)
    return serato


class TestLooksLikeSeratoDatabaseV2(unittest.TestCase):
    def test_database_magic(self):
        self.assertTrue(looks_like_serato_database_v2(_db_bytes()))

    def test_crate_is_not_database(self):
        crate = save_serato_crate(
            ["/Users/test/Desktop/a.mp3"],
            "x",
            existing_files_only=False,
        )
        self.assertTrue(crate.startswith(b"vrsn"))
        self.assertFalse(looks_like_serato_database_v2(crate))

    def test_zip_header_is_not_database(self):
        self.assertFalse(looks_like_serato_database_v2(b"PK\x03\x04not-serato"))

    def test_empty(self):
        self.assertFalse(looks_like_serato_database_v2(b""))
        self.assertFalse(looks_like_serato_database_v2(b"vrsn"))


class TestResolveSeratoLibraryDir(unittest.TestCase):
    def test_from_serato_folder_parent_and_file(self):
        with tempfile.TemporaryDirectory() as td:
            music = Path(td) / "Music"
            serato = _write_library(music)
            db_file = serato / "database V2"
            self.assertEqual(resolve_serato_library_dir(serato), serato)
            self.assertEqual(resolve_serato_library_dir(music), serato)
            self.assertEqual(resolve_serato_library_dir(db_file), serato)

    def test_explicit_path_does_not_fall_back_to_default(self):
        with tempfile.TemporaryDirectory() as td:
            default = _write_library(Path(td) / "default_music")
            other = Path(td) / "other"
            other.mkdir()
            (other / "readme.txt").write_text("no serato", encoding="utf-8")
            with patch("library_paths.default_serato_dir", return_value=default):
                self.assertIsNone(resolve_serato_library_dir(other))
                self.assertIsNone(resolve_serato_library_dir(other / "readme.txt"))
                self.assertEqual(resolve_serato_library_dir(None), default)

    def test_zip_file_is_not_serato(self):
        with tempfile.TemporaryDirectory() as td:
            default = _write_library(Path(td) / "Music")
            zpath = Path(td) / "backup.zip"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("database.xml", "<VirtualDJ_Database Version='8'/>")
            with patch("library_paths.default_serato_dir", return_value=default):
                self.assertIsNone(resolve_serato_library_dir(zpath))

    def test_drive_root_windows_letter(self):
        p = Path("C:/Users/dj/Music/_Serato_")
        self.assertEqual(default_serato_drive_root(p), "C:/")

    def test_drive_root_posix(self):
        self.assertEqual(default_serato_drive_root(Path("/Users/dj/Music/_Serato_")), "/")


class TestLoadSeratoFolder(unittest.TestCase):
    def test_loads_tracks_and_crates(self):
        with tempfile.TemporaryDirectory() as td:
            music = Path(td) / "Music"
            serato = _write_library(music)
            db = load_serato_folder(music, drive_root="/")
            self.assertEqual(len(db.tracks), 1)
            self.assertEqual(db.source, "serato")
            names = [pl.name for pl in db.playlists]
            self.assertIn("Warmup", names)

    def test_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            db = load_serato_folder(Path(td) / "nope")
            self.assertEqual(db.tracks, [])
            self.assertEqual(db.playlists, [])


class TestSeratoOpenApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app

        cls.client = app.test_client()

    def test_load_folder_and_database_file(self):
        with tempfile.TemporaryDirectory() as td:
            music = Path(td) / "Music"
            serato = _write_library(music)
            r = self.client.post("/api/load", json={"path": str(serato)})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            d = r.get_json()
            self.assertEqual(d["source"], "serato")
            self.assertGreaterEqual(d["count"], 1)
            self.assertGreaterEqual(d["playlists"], 1)

            r2 = self.client.post("/api/load", json={"path": str(serato / "database V2")})
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.get_json()["source"], "serato")

            r3 = self.client.post("/api/load", json={"path": str(music)})
            self.assertEqual(r3.status_code, 200)
            self.assertEqual(r3.get_json()["source"], "serato")

    def test_load_source_serato_uses_default(self):
        with tempfile.TemporaryDirectory() as td:
            serato = _write_library(Path(td) / "Music")
            with patch("library_paths.default_serato_dir", return_value=serato):
                r = self.client.post("/api/load", json={"source": "serato"})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertEqual(r.get_json()["source"], "serato")

    def test_load_source_serato_missing(self):
        missing = Path(tempfile.gettempdir()) / "njr-no-serato-lib"
        with patch("library_paths.default_serato_dir", return_value=missing):
            r = self.client.post("/api/load", json={"source": "serato"})
        self.assertEqual(r.status_code, 404)
        self.assertIn("Otwórz folder", r.get_json()["error"])

    def test_load_zip_does_not_steal_default_serato(self):
        with tempfile.TemporaryDirectory() as td:
            default = _write_library(Path(td) / "Music")
            zpath = Path(td) / "vdj-backup.zip"
            xml = "<VirtualDJ_Database Version='8.5'></VirtualDJ_Database>"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("database.xml", xml)
            with patch("library_paths.default_serato_dir", return_value=default):
                r = self.client.post("/api/load", json={"path": str(zpath)})
            d = r.get_json() or {}
            self.assertNotEqual(d.get("source"), "serato")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(d.get("source"), "vdj")

    def test_load_universal_database_v2_filename(self):
        raw = _db_bytes()
        r = self.client.post(
            "/api/load-universal",
            data={"file": (io.BytesIO(raw), "database V2")},
        )
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = r.get_json()
        self.assertEqual(d["source"], "serato")
        self.assertGreaterEqual(d["count"], 1)
        self.assertIn("Otwórz folder", d["message"])

    def test_load_universal_crate_is_not_database(self):
        crate = save_serato_crate(
            ["/Users/test/Desktop/a.mp3"],
            "Warmup",
            existing_files_only=False,
        )
        r = self.client.post(
            "/api/load-universal",
            data={"file": (io.BytesIO(crate), "Warmup.crate")},
        )
        self.assertEqual(r.status_code, 400)
        err = (r.get_json() or {}).get("error", "")
        self.assertIn("Otwórz folder", err)


class TestSeratoVrsnHelper(unittest.TestCase):
    """vrsn bez słowa Database nie jest bazą (np. obcięty nagłówek)."""

    def test_vrsn_without_database_text(self):
        buf = io.BytesIO()
        _write_serato_record(buf, "vrsn", _encode_utf16be("1.0/Serato ScratchLive Crate"))
        self.assertFalse(looks_like_serato_database_v2(buf.getvalue()))


if __name__ == "__main__":
    unittest.main()
