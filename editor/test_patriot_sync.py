"""Testy diagnostyki duplikatów Patriot i export doc bez kopiowania plików."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from unified_model import Playlist, Track, UnifiedDatabase


class TestPatriotDuplicateDiagnosis(unittest.TestCase):
    def test_diagnose_finds_filename_dupes(self):
        from engine_patriot_sync import diagnose_engine_track_duplicates

        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "Engine Library"
            db2 = lib / "Database2"
            db2.mkdir(parents=True)
            mdb = db2 / "m.db"
            conn = sqlite3.connect(mdb)
            conn.execute(
                """
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY,
                    path TEXT, filename TEXT, title TEXT, artist TEXT,
                    fileBytes INTEGER, isAvailable INTEGER DEFAULT 1
                )
                """
            )
            conn.executemany(
                "INSERT INTO Track (path, filename, title, artist, fileBytes) VALUES (?,?,?,?,?)",
                [
                    ("Music/A/Unknown Album/song.mp3", "song.mp3", "Song", "A", 1000),
                    ("Music/B/Unknown Album/song.mp3", "song.mp3", "Song", "B", 1000),
                ],
            )
            conn.commit()
            conn.close()

            out = diagnose_engine_track_duplicates(lib)
            self.assertEqual(out["track_count"], 2)
            self.assertEqual(out["duplicate_filename_groups"], 1)
            self.assertEqual(out["duplicate_filename_extra_rows"], 1)


class TestPatriotMetadataExport(unittest.TestCase):
    def test_build_export_uses_existing_patriot_paths(self):
        from engine_patriot_sync import build_patriot_metadata_export_doc

        with tempfile.TemporaryDirectory() as td:
            patriot = Path(td) / "Patriot"
            music = patriot / "Music" / "Artist" / "Album"
            music.mkdir(parents=True)
            audio = music / "track.mp3"
            audio.write_bytes(b"fake")

            db2 = patriot / "Database2"
            db2.mkdir()
            mdb = db2 / "m.db"
            conn = sqlite3.connect(mdb)
            conn.execute(
                """
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY, path TEXT, filename TEXT,
                    title TEXT, artist TEXT, isAvailable INTEGER DEFAULT 1,
                    isAnalyzed INTEGER DEFAULT 0, bitrate INTEGER, fileBytes INTEGER
                )
                """
            )
            conn.execute(
                "INSERT INTO Track (id, path, filename, title, artist, fileBytes) "
                "VALUES (1, ?, ?, ?, ?, ?)",
                (
                    "Music/Artist/Album/track.mp3",
                    "track.mp3",
                    "My Track",
                    "Artist",
                    len(b"fake"),
                ),
            )
            conn.commit()
            conn.close()

            mac_path = str(Path(td) / "elsewhere" / "track.mp3")
            Path(mac_path).parent.mkdir(parents=True)
            Path(mac_path).write_bytes(b"fake")

            db = UnifiedDatabase(
                tracks=[
                    Track(
                        path=mac_path,
                        title="My Track",
                        artist="Artist",
                        album="Album",
                    )
                ],
                playlists=[
                    Playlist(name="Serato", track_ids=[mac_path], is_folder=True, children=[
                        Playlist(name="Test", track_ids=[mac_path]),
                    ]),
                ],
                source="serato",
            )

            export_doc, stats = build_patriot_metadata_export_doc(db, patriot)
            self.assertEqual(stats["tracks_mapped"], 1)
            self.assertEqual(len(export_doc["tracks"]), 1)
            self.assertEqual(
                export_doc["tracks"][0]["relative_path"],
                "Music/Artist/Album/track.mp3",
            )
            self.assertFalse(export_doc.get("engine_music_layout"))


class TestPatriotDedupe(unittest.TestCase):
    def _make_lib(self, td: str) -> Path:
        lib = Path(td) / "Patriot"
        music = lib / "Music" / "A" / "Album"
        music.mkdir(parents=True)
        f1 = music / "song.mp3"
        f2 = lib / "Music" / "A" / "Unknown Album" / "song.mp3"
        f2.parent.mkdir(parents=True)
        f1.write_bytes(b"x" * 100)
        f2.write_bytes(b"x" * 100)

        db2 = lib / "Database2"
        db2.mkdir()
        conn = sqlite3.connect(db2 / "m.db")
        conn.execute(
            """
            CREATE TABLE Track (
                id INTEGER PRIMARY KEY, path TEXT, filename TEXT,
                title TEXT, artist TEXT, fileBytes INTEGER,
                isAvailable INTEGER DEFAULT 1, isAnalyzed INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE PerformanceData (id INTEGER PRIMARY KEY, trackId INTEGER)
            """
        )
        conn.execute(
            """
            CREATE TABLE PlaylistEntity (
                id INTEGER PRIMARY KEY, listId INTEGER, trackId INTEGER,
                databaseUuid TEXT, nextEntityId INTEGER
            )
            """
        )
        conn.execute("CREATE TABLE Information (uuid TEXT)")
        conn.execute("INSERT INTO Information (uuid) VALUES ('test-uuid')")
        conn.executemany(
            "INSERT INTO Track (id, path, filename, title, artist, fileBytes, isAnalyzed) VALUES (?,?,?,?,?,?,?)",
            [
                (1, "Music/A/Album/song.mp3", "song.mp3", "Song", "A", 100, 1),
                (2, "Music/A/Unknown Album/song.mp3", "song.mp3", "Song", "A", 100, 0),
            ],
        )
        conn.execute("INSERT INTO PlaylistEntity (listId, trackId, databaseUuid) VALUES (1, 2, 'test-uuid')")
        conn.commit()
        conn.close()
        return lib

    def test_plan_finds_duplicate(self):
        from engine_patriot_sync import plan_patriot_dedupe

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_lib(td)
            plan = plan_patriot_dedupe(lib)
            self.assertEqual(plan["tracks_to_remove"], 1)
            self.assertEqual(plan["track_count_after"], 1)

    def test_dedupe_removes_duplicate_row(self):
        from engine_patriot_sync import dedupe_patriot_library

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_lib(td)
            with unittest.mock.patch(
                "engine_patriot_sync.assert_engine_library_safe_for_write",
            ), unittest.mock.patch(
                "engine_patriot_sync.backup_engine_database2",
                return_value={"skipped": True},
            ), unittest.mock.patch(
                "engine_patriot_sync.repair_engine_post_merge",
                return_value={},
            ):
                out = dedupe_patriot_library(lib, dry_run=False, delete_files=False)
            self.assertEqual(out["tracks_removed"], 1)
            conn = sqlite3.connect(lib / "Database2" / "m.db")
            n = conn.execute("SELECT COUNT(*) FROM Track").fetchone()[0]
            conn.close()
            self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
