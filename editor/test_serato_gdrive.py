#!/usr/bin/env python3
"""Remap ścieżek Serato (Mac / Desktop) → pliki na Dysku Google, bez kopiowania."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from serato_gdrive import (
    absolute_to_serato_portable,
    remap_serato_library_to_google_drive,
    strip_serato_machine_prefix,
    _google_drive_join_candidates,
    _search_keys,
)
from serato_parser import (
    _encode_utf16be,
    _write_serato_record,
    load_serato_crate,
    load_serato_database_v2,
    map_stale_serato_path_to_desktop,
    save_serato_crate,
)


def _otrk(path: str) -> bytes:
    buf = BytesIO()
    _write_serato_record(buf, "pfil", _encode_utf16be(path))
    _write_serato_record(buf, "tsng", _encode_utf16be("Song"))
    return buf.getvalue()


def _db(*otrks: bytes) -> bytes:
    buf = BytesIO()
    _write_serato_record(buf, "vrsn", _encode_utf16be("2.0/Serato Scratch LIVE Database"))
    for o in otrks:
        _write_serato_record(buf, "otrk", o)
    return buf.getvalue()


def _crate_paths(raw: bytes) -> list[str]:
    pl = load_serato_crate(raw, "t")
    return [p.replace("\\", "/") for p in (pl.track_ids or [])]


class TestStripAndLookup(unittest.TestCase):
    def test_strip_machine_prefixes(self):
        self.assertEqual(
            strip_serato_machine_prefix("Users/mac/Library/CloudStorage/GoogleDrive-abc/My Drive/muzyka dj/a.mp3"),
            "muzyka dj/a.mp3",
        )
        self.assertEqual(
            strip_serato_machine_prefix("G:/Inne komputery/MacBook/Desktop/muzyka dj/a.mp3"),
            "Desktop/muzyka dj/a.mp3",
        )
        self.assertEqual(
            strip_serato_machine_prefix("Volumes/osx/Users/mac/Desktop/muzyka dj/a.mp3"),
            "Users/mac/Desktop/muzyka dj/a.mp3",
        )

    def test_search_keys_longest_first(self):
        keys = _search_keys("Users/mac/Desktop/muzyka dj/track.mp3")
        self.assertEqual(keys[0], "users/mac/desktop/muzyka dj/track.mp3")
        self.assertIn("muzyka dj/track.mp3", keys)
        self.assertEqual(keys[-1], "track.mp3")

    def test_join_candidates_no_double_moj_dysk(self):
        root = Path("/tmp/Mój dysk")
        cands = _google_drive_join_candidates(root, "Mój dysk/muzyka dj/a.mp3")
        as_str = [str(p).replace("\\", "/") for p in cands]
        self.assertTrue(any(s.endswith("Mój dysk/muzyka dj/a.mp3") for s in as_str))
        self.assertFalse(any("Mój dysk/Mój dysk/" in s for s in as_str))

    def test_absolute_to_portable_strips_drive_letter(self):
        self.assertEqual(
            absolute_to_serato_portable("G:/Mój dysk/muzyka dj/a.mp3"),
            "Mój dysk/muzyka dj/a.mp3",
        )

    def test_moj_dysk_not_remapped_to_desktop(self):
        mapped = map_stale_serato_path_to_desktop("Mój dysk/muzyka dj/ghost.mp3")
        self.assertIsNone(mapped)


class TestRemapLibrary(unittest.TestCase):
    def test_mac_paths_rewrite_to_gdrive_without_copy(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            gdrive = td_path / "Mój dysk"
            audio_dir = gdrive / "muzyka dj"
            audio_dir.mkdir(parents=True)
            audio = audio_dir / "track.mp3"
            audio.write_bytes(b"ID3FAKE")

            desktop_copy = td_path / "Desktop" / "muzyka dj"
            desktop_copy.mkdir(parents=True)
            (desktop_copy / "track.mp3").write_bytes(b"DESKTOP")

            serato = td_path / "_Serato_"
            sub = serato / "Subcrates"
            sub.mkdir(parents=True)
            mac_path = "Users/macuser/Desktop/muzyka dj/track.mp3"
            (serato / "database V2").write_bytes(_db(_otrk(mac_path)))
            (sub / "Set.crate").write_bytes(
                save_serato_crate([mac_path], "Set", "/", existing_files_only=False)
            )

            sqlite_dir = td_path / "SeratoLibrary"
            sqlite_dir.mkdir()
            con = sqlite3.connect(str(sqlite_dir / "root.sqlite"))
            con.execute(
                "CREATE TABLE asset (id INTEGER PRIMARY KEY, portable_id TEXT, "
                "file_name TEXT, is_missing INTEGER, file_size INTEGER, revision INTEGER DEFAULT 0)"
            )
            con.execute(
                "INSERT INTO asset (portable_id, file_name, is_missing, file_size, revision) "
                "VALUES (?, ?, 1, 0, 0)",
                (mac_path, "track.mp3"),
            )
            con.commit()
            con.close()

            with patch("dj_apps_guard.is_serato_running", return_value=(False, "")):
                with patch("dj_apps_guard.serato_db_likely_locked", return_value=(False, "")):
                    stats = remap_serato_library_to_google_drive(
                        serato,
                        google_drive=gdrive,
                        dry_run=False,
                        include_sqlite=True,
                        sqlite_dir=sqlite_dir,
                    )

            self.assertTrue(stats.get("ok"), stats)
            self.assertGreaterEqual(stats.get("db_rewrites") or 0, 1)
            self.assertGreaterEqual(stats.get("crate_rewrites") or 0, 1)
            self.assertEqual((stats.get("sqlite") or {}).get("updated"), 1)

            db = load_serato_database_v2((serato / "database V2").read_bytes())
            new_path = db.tracks[0].path.replace("\\", "/").lstrip("/")
            self.assertIn("muzyka dj/track.mp3", new_path)
            self.assertNotIn("Users/macuser/Desktop", new_path)
            self.assertTrue(new_path.lower().endswith("muzyka dj/track.mp3"))

            crate_paths = _crate_paths((sub / "Set.crate").read_bytes())
            self.assertTrue(crate_paths)
            self.assertNotIn("Users/macuser/Desktop", crate_paths[0])

            con = sqlite3.connect(str(sqlite_dir / "root.sqlite"))
            pid, missing = con.execute("SELECT portable_id, is_missing FROM asset").fetchone()
            con.close()
            self.assertNotIn("Users/macuser/Desktop", pid)
            self.assertEqual(missing, 0)

            # Muzyka zostaje na GDrive; kopia Desktop nie jest źródłem.
            self.assertTrue(audio.is_file())
            self.assertEqual(audio.read_bytes(), b"ID3FAKE")
            self.assertEqual((desktop_copy / "track.mp3").read_bytes(), b"DESKTOP")
            backups = stats.get("backups") or []
            self.assertTrue(any("database V2" in b for b in backups))

    def test_lookup_prefers_unique_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            gdrive = Path(td) / "Google Drive"
            (gdrive / "muzyka dj").mkdir(parents=True)
            (gdrive / "muzyka dj" / "unique.mp3").write_bytes(b"x")
            from serato_gdrive import GoogleDriveAudioIndex

            idx = GoogleDriveAudioIndex([gdrive])
            hit = idx.lookup("Users/damsza/Desktop/muzyka dj/unique.mp3")
            self.assertIsNotNone(hit)
            self.assertTrue(hit.replace("\\", "/").endswith("muzyka dj/unique.mp3"))
            self.assertNotIn("Users/damsza", hit)


class TestRemapApi(unittest.TestCase):
    def test_api_dry_run(self):
        from app import app

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            gdrive = td_path / "My Drive"
            (gdrive / "muzyka dj").mkdir(parents=True)
            (gdrive / "muzyka dj" / "a.mp3").write_bytes(b"x")
            serato = td_path / "_Serato_"
            serato.mkdir()
            (serato / "database V2").write_bytes(
                _db(_otrk("Users/mac/Desktop/muzyka dj/a.mp3"))
            )
            client = app.test_client()
            with patch("dj_apps_guard.is_serato_running", return_value=(False, "")):
                with patch("dj_apps_guard.serato_db_likely_locked", return_value=(False, "")):
                    with patch("app.sync_guard_blockers", return_value=(False, "", [])):
                        r = client.post(
                            "/api/remap-serato-google-drive",
                            json={
                                "seratoDir": str(serato),
                                "googleDrive": str(gdrive),
                                "dryRun": True,
                                "includeSqlite": False,
                            },
                        )
            self.assertEqual(r.status_code, 200, r.get_json())
            d = r.get_json()
            self.assertTrue(d.get("ok"))
            self.assertTrue(d.get("dry_run"))
            self.assertGreaterEqual(d.get("db_rewrites") or 0, 1)
            # Dry-run nie nadpisuje bazy
            raw = (serato / "database V2").read_bytes()
            db = load_serato_database_v2(raw)
            self.assertIn("Users/mac/Desktop", db.tracks[0].path.replace("\\", "/"))


class TestGoogleDriveEnv(unittest.TestCase):
    def test_njr_google_drive_env(self):
        import library_paths as lp

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "GDrive"
            root.mkdir()
            with patch.dict(os.environ, {"NJR_GOOGLE_DRIVE": str(root)}):
                roots = lp.google_drive_roots()
            self.assertTrue(any(p.resolve() == root.resolve() for p in roots))


if __name__ == "__main__":
    unittest.main()
