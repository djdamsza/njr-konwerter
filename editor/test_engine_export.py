#!/usr/bin/env python3
"""Testy konwersji Engine DJ (Python — bez binarki libdjinterop)."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine_generator import (
    beatgrid_to_engine_markers,
    camelot_normalize,
    cues_to_engine_hot,
    engine_genre_for_export,
    track_to_engine_json,
    unified_to_engine_export_doc,
    _rating_to_engine,
)
from engine_smartlist import vdj_filter_to_engine_rules
from unified_model import BeatgridPoint, CuePoint, Playlist, Track, UnifiedDatabase


class TestEngineGenerator(unittest.TestCase):
    def test_camelot(self):
        self.assertEqual(camelot_normalize("8b"), "8B")
        self.assertEqual(camelot_normalize("12A"), "12A")
        self.assertEqual(camelot_normalize(""), "")
        self.assertEqual(camelot_normalize("Am"), "8A")
        self.assertEqual(camelot_normalize("Dm"), "7A")
        self.assertEqual(camelot_normalize("G#m"), "1A")
        self.assertEqual(camelot_normalize("G#"), "4B")
        self.assertEqual(camelot_normalize("G"), "9B")
        self.assertEqual(camelot_normalize("F# Minor"), "11A")

    def test_rating_serato_255_scale(self):
        self.assertEqual(_rating_to_engine(0), 0)
        self.assertEqual(_rating_to_engine(3), 60)
        self.assertEqual(_rating_to_engine(204), 80)
        self.assertEqual(_rating_to_engine(255), 100)

    def test_track_key_export(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"ID3")
            path = f.name
        try:
            row = track_to_engine_json(
                Track(path=path, title="A", key="Am", bpm=120, duration=180),
                engine_dir=Path(tempfile.gettempdir()) / "Engine Library",
            )
            self.assertIsNotNone(row)
            self.assertEqual(row["key_camelot"], "8A")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_beatgrid_markers(self):
        t = Track(
            path="/music/test.mp3",
            bpm=120.0,
            duration=60.0,
            beatgrid=[BeatgridPoint(pos=0.0, bpm=120.0)],
        )
        m = beatgrid_to_engine_markers(t, 44100)
        self.assertEqual(len(m), 2)
        self.assertEqual(m[0]["index"], -4)

    def test_hot_cues(self):
        t = Track(
            path="/music/test.mp3",
            cue_points=[CuePoint(name="Intro", pos=10.0, num=0)],
        )
        hot = cues_to_engine_hot(t, 44100)
        self.assertEqual(len(hot), 1)
        self.assertEqual(hot[0]["slot"], 0)
        self.assertAlmostEqual(hot[0]["sample_offset"], 10.0 * 44100)

    def test_hot_cues_vdj_num_1_to_8(self):
        from engine_generator import _vdj_cue_slot

        self.assertEqual(_vdj_cue_slot(1), 0)
        self.assertEqual(_vdj_cue_slot(8), 7)
        self.assertIsNone(_vdj_cue_slot(9))
        t = Track(
            path="/music/test.mp3",
            cue_points=[CuePoint(name="Cue 1", pos=5.0, num=1)],
        )
        hot = cues_to_engine_hot(t, 44100)
        self.assertEqual(hot[0]["slot"], 0)

    def test_unified_export_doc_playlists(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            engine = Path(td) / "Engine Library"
            engine.mkdir()
            music = Path(td) / "music"
            music.mkdir()
            mp3 = music / "a.mp3"
            mp3.write_bytes(b"ID3")
            db = UnifiedDatabase(
                tracks=[
                    Track(path=str(mp3), title="A", artist="X", bpm=128, duration=200),
                ],
                playlists=[Playlist(name="Party", track_ids=[str(mp3)])],
            )
            doc = unified_to_engine_export_doc(db, engine_dir=engine)
            self.assertEqual(len(doc["tracks"]), 1)
            self.assertIn("music/a.mp3", doc["tracks"][0]["relative_path"])
            self.assertEqual(len(doc["playlists"]), 1)
            self.assertEqual(doc["playlists"][0]["name"], "Party")

    def test_relative_path_desktop_music(self):
        from engine_generator import _to_relative_path

        engine = Path("/Users/test/Music/Engine Library")
        path = "/Users/test/Desktop/muzyka dj/test.mp3"
        rel = _to_relative_path(path, engine_dir=engine)
        self.assertEqual(rel, "../../Desktop/muzyka dj/test.mp3")

    def test_merge_export_doc(self):
        engine = Path("/Users/test/Music/Engine Library")
        db = UnifiedDatabase(
            tracks=[Track(path="/Users/test/Desktop/a.mp3", title="A", bpm=120, duration=180)],
            playlists=[Playlist(name="Set", track_ids=["/Users/test/Desktop/a.mp3"])],
        )
        doc = unified_to_engine_export_doc(
            db,
            engine_dir=engine,
            merge_mode=True,
            playlist_prefix="VDJ / ",
        )
        self.assertTrue(doc["merge_mode"])
        self.assertFalse(doc["clear_existing"])
        self.assertTrue(doc["replace_playlist_tracks"])
        self.assertEqual(doc["playlist_prefix"], "VDJ / ")

    def test_skip_streaming(self):
        row = track_to_engine_json(Track(path="netsearch://td123", title="T"))
        self.assertIsNone(row)

    def test_skip_vdjcache_and_no_extension(self):
        from engine_generator import _is_engine_exportable_path

        self.assertFalse(_is_engine_exportable_path("/cache/foo.vdjcache"))
        self.assertFalse(_is_engine_exportable_path("/editor/td493305"))
        self.assertFalse(_is_engine_exportable_path("/music/foo.zip"))
        self.assertTrue(_is_engine_exportable_path("/Desktop/track.mp3"))
        self.assertIsNone(track_to_engine_json(Track(path="/cache/x.vdjcache", title="T")))

    def test_engine_genre_merges_user_tags(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"ID3")
            path = f.name
        try:
            t = Track(
                path=path,
                genre="#AI",
                tags=["#AI", "#PARTY", "#TANECZNE"],
            )
            self.assertEqual(engine_genre_for_export(t), "#AI #PARTY #TANECZNE")
            row = track_to_engine_json(
                t, engine_dir=Path(tempfile.gettempdir()) / "Engine Library"
            )
            self.assertIsNotNone(row)
            self.assertEqual(row["genre"], "#AI #PARTY #TANECZNE")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_vdj_filter_to_engine_rules(self):
        r = vdj_filter_to_engine_rules("User 1 has tag ballady")
        self.assertEqual(r["match"], "one")
        self.assertEqual(r["rules"][0]["con"], "LIKE")
        self.assertIn("#ballady", r["rules"][0]["param"])

        r2 = vdj_filter_to_engine_rules(
            "User 1 has tag TANECZNE and User 1 has tag 2025"
        )
        self.assertEqual(r2["match"], "all")
        self.assertEqual(len(r2["rules"]), 2)

        r3 = vdj_filter_to_engine_rules(
            "User 1 has tag PARTY or User 1 has tag TANECZNE"
        )
        self.assertEqual(r3["match"], "one")
        self.assertEqual(len(r3["rules"]), 2)

        self.assertIsNone(vdj_filter_to_engine_rules("Bpm Difference <= 4 and Key Difference <= 2"))

    def test_remove_duplicate_playlist_snapshots_for_smartlists(self):
        from engine_smartlist import remove_duplicate_playlist_snapshots_for_smartlists

        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE Playlist (
                id INTEGER PRIMARY KEY,
                title TEXT,
                parentListId INTEGER,
                nextListId INTEGER,
                UNIQUE (parentListId, nextListId)
            );
            CREATE TABLE PlaylistEntity (
                id INTEGER PRIMARY KEY,
                listId INTEGER,
                trackId INTEGER
            );
            CREATE TABLE Smartlist (
                listUuid TEXT PRIMARY KEY,
                title TEXT,
                parentPlaylistPath TEXT
            );
            INSERT INTO Playlist VALUES (1, 'VDJ', NULL, 0);
            INSERT INTO Playlist VALUES (2, 'MyLists', 1, 0);
            INSERT INTO Playlist VALUES (3, 'gatunki', 2, 0);
            INSERT INTO Playlist VALUES (6, 'KEEP', 3, 4);
            INSERT INTO Playlist VALUES (4, 'COVER', 3, 5);
            INSERT INTO Playlist VALUES (5, 'wszystko', 3, 0);
            INSERT INTO PlaylistEntity VALUES (1, 4, 100);
            INSERT INTO PlaylistEntity VALUES (2, 4, 101);
            INSERT INTO PlaylistEntity VALUES (3, 5, 200);
            INSERT INTO Smartlist VALUES ('U1', 'COVER', 'gatunki;MyLists;VDJ;');
            """
        )
        stats = remove_duplicate_playlist_snapshots_for_smartlists(conn)
        self.assertEqual(stats["duplicate_playlists_removed"], 1)
        self.assertEqual(stats["duplicate_playlist_entities_removed"], 2)
        self.assertIsNone(
            conn.execute("SELECT id FROM Playlist WHERE title='COVER'").fetchone()
        )
        self.assertEqual(
            conn.execute("SELECT nextListId FROM Playlist WHERE id=6").fetchone()[0],
            5,
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM PlaylistEntity WHERE listId=5").fetchone()[0],
            1,
        )
        conn.close()


class TestEnginePostMergeRepair(unittest.TestCase):
    def _make_db(self, tmp: Path) -> Path:
        import sqlite3

        dbdir = tmp / "Database2"
        dbdir.mkdir(parents=True)
        mdb = dbdir / "m.db"
        conn = sqlite3.connect(str(mdb))
        conn.executescript(
            """
            CREATE TABLE Track (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                bpm INTEGER,
                bpmAnalyzed REAL,
                isAnalyzed BOOLEAN
            );
            CREATE TABLE PerformanceData (
                trackId INTEGER PRIMARY KEY,
                overviewWaveFormData BLOB,
                beatData BLOB,
                trackData BLOB,
                quickCues BLOB,
                loops BLOB,
                FOREIGN KEY(trackId) REFERENCES Track(id) ON DELETE CASCADE
            );
            CREATE TABLE PlaylistEntity (
                id INTEGER PRIMARY KEY,
                trackId INTEGER,
                listId INTEGER
            );
            INSERT INTO Track VALUES (1, 'a.mp3', 120, 120.0, 1);
            INSERT INTO Track VALUES (2, 'b.mp3', 0, 128.0, 1);
            INSERT INTO PerformanceData VALUES (1, X'0102030405', NULL, NULL, NULL, NULL);
            INSERT INTO PerformanceData VALUES (2, X'0102', NULL, NULL, NULL, NULL);
            INSERT INTO PerformanceData VALUES (99, X'ffff', NULL, NULL, NULL, NULL);
            INSERT INTO PlaylistEntity VALUES (1, 99, 1);
            """
        )
        conn.commit()
        conn.close()
        return tmp

    def test_repair_removes_orphans_and_resets_stub_waveforms(self):
        import tempfile
        from engine_libdjinterop import repair_engine_post_merge

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_db(Path(td))
            stats = repair_engine_post_merge(lib, min_waveform_bytes=4)

            self.assertEqual(stats["orphan_performance_data_removed"], 1)
            self.assertEqual(stats["orphan_playlist_entities_removed"], 1)
            self.assertEqual(stats["stub_analyzed_reset"], 1)

            import sqlite3

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM PerformanceData").fetchone()[0], 2)
            row = conn.execute(
                "SELECT isAnalyzed, bpm FROM Track WHERE path='b.mp3'"
            ).fetchone()
            self.assertEqual(row, (0, 128))
            conn.close()

    def test_repair_remaps_playlist_entity_via_origin_track_id(self):
        """Sync Manager zostawia PE.trackId = Mac ID; remap przez originTrackId."""
        import sqlite3
        import tempfile
        from engine_libdjinterop import repair_engine_post_merge

        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            dbdir = lib / "Database2"
            dbdir.mkdir(parents=True)
            conn = sqlite3.connect(str(dbdir / "m.db"))
            conn.executescript(
                """
                CREATE TABLE Information (id INTEGER PRIMARY KEY, uuid TEXT);
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY,
                    path TEXT UNIQUE,
                    originTrackId INTEGER,
                    originDatabaseUuid TEXT,
                    bpm INTEGER DEFAULT 0,
                    bpmAnalyzed REAL,
                    isAnalyzed BOOLEAN DEFAULT 0,
                    albumArtId INTEGER,
                    albumArtSourceHash TEXT
                );
                CREATE TABLE PerformanceData (
                    trackId INTEGER PRIMARY KEY,
                    overviewWaveFormData BLOB,
                    beatData BLOB,
                    trackData BLOB,
                    quickCues BLOB,
                    loops BLOB
                );
                CREATE TABLE PlaylistEntity (
                    id INTEGER PRIMARY KEY,
                    listId INTEGER,
                    trackId INTEGER,
                    databaseUuid TEXT,
                    nextEntityId INTEGER,
                    membershipReference INTEGER,
                    UNIQUE (listId, databaseUuid, trackId)
                );
                CREATE TABLE AlbumArt (id INTEGER PRIMARY KEY);
                INSERT INTO Information VALUES (1, 'local-uuid-aaa');
                INSERT INTO Track VALUES (1, 'Music/a.mp3', 8599, 'mac-uuid', 0, NULL, 0, NULL, NULL);
                INSERT INTO Track VALUES (2, 'Music/b.mp3', 8600, 'mac-uuid', 0, NULL, 0, NULL, NULL);
                INSERT INTO PerformanceData VALUES (1, X'0102', NULL, NULL, NULL, NULL);
                INSERT INTO PerformanceData VALUES (2, X'0102', NULL, NULL, NULL, NULL);
                INSERT INTO PlaylistEntity VALUES (1, 10, 8599, 'mac-uuid', 0, 0);
                INSERT INTO PlaylistEntity VALUES (2, 10, 8600, 'mac-uuid', 0, 0);
                """
            )
            conn.commit()
            conn.close()

            stats = repair_engine_post_merge(lib, min_waveform_bytes=500)
            self.assertEqual(stats["playlist_entities_remapped"], 2)
            self.assertEqual(stats["orphan_playlist_entities_removed"], 0)

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            rows = conn.execute(
                "SELECT trackId, databaseUuid FROM PlaylistEntity ORDER BY id"
            ).fetchall()
            self.assertEqual(rows, [(1, "local-uuid-aaa"), (2, "local-uuid-aaa")])
            orphans = conn.execute(
                """
                SELECT COUNT(*) FROM PlaylistEntity pe
                LEFT JOIN Track t ON t.id = pe.trackId
                WHERE pe.trackId > 0 AND t.id IS NULL
                """
            ).fetchone()[0]
            self.assertEqual(orphans, 0)
            conn.close()

    def test_remap_unified_db_for_patriot(self):
        import tempfile

        from engine_stems import remap_unified_db_for_patriot

        with tempfile.TemporaryDirectory() as td:
            patriot = Path(td) / "Patriot"
            patriot.mkdir()
            music = patriot / "Music" / "Artist"
            music.mkdir(parents=True)
            mp3 = music / "song.mp3"
            mp3.write_bytes(b"ID3")

            mdb_dir = patriot / "Database2"
            mdb_dir.mkdir()
            conn = sqlite3.connect(str(mdb_dir / "m.db"))
            conn.executescript(
                """
                CREATE TABLE Information (uuid TEXT);
                INSERT INTO Information VALUES ('pat-uuid');
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY, path TEXT, title TEXT, artist TEXT,
                    isAvailable INTEGER, isAnalyzed INTEGER, bitrate INTEGER, fileBytes INTEGER
                );
                INSERT INTO Track VALUES (1, 'Music/Artist/song.mp3', 'Song', 'Artist', 1, 1, 320, 100);
                """
            )
            conn.commit()
            conn.close()

            db = UnifiedDatabase(
                tracks=[
                    Track(
                        path="/Users/mac/Desktop/song.mp3",
                        title="Song",
                        artist="Artist",
                    )
                ],
                playlists=[
                    Playlist(
                        name="Test",
                        track_ids=["/Users/mac/Desktop/song.mp3"],
                    )
                ],
            )
            remapped, stats = remap_unified_db_for_patriot(db, patriot)
            self.assertEqual(stats["tracks_mapped"], 1)
            self.assertEqual(len(remapped.tracks), 1)
            self.assertTrue(remapped.tracks[0].path.endswith("Music/Artist/song.mp3"))
            self.assertEqual(remapped.playlists[0].track_ids[0], remapped.tracks[0].path)

    def test_remap_finds_file_on_disk_not_in_mdb(self):
        """Świeżo skopiowany plik Music/ bez wpisu Track też się mapuje."""
        import tempfile

        from engine_stems import remap_unified_db_for_patriot

        with tempfile.TemporaryDirectory() as td:
            patriot = Path(td) / "Patriot"
            music = patriot / "Music" / "Laback"
            music.mkdir(parents=True)
            mp3 = music / "LABACK - My Heart Will Go On.m4a"
            mp3.write_bytes(b"fake-m4a")

            mdb_dir = patriot / "Database2"
            mdb_dir.mkdir()
            conn = sqlite3.connect(str(mdb_dir / "m.db"))
            conn.executescript(
                """
                CREATE TABLE Information (uuid TEXT);
                INSERT INTO Information VALUES ('pat-uuid');
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY, path TEXT, title TEXT, artist TEXT,
                    isAvailable INTEGER, isAnalyzed INTEGER, bitrate INTEGER, fileBytes INTEGER
                );
                """
            )
            conn.commit()
            conn.close()

            db = UnifiedDatabase(
                tracks=[
                    Track(
                        path="/Users/mac/Music/NJR/LABACK - My Heart Will Go On.m4a",
                        title="Titanic x My Heart Will Go On",
                        artist="Laback",
                    )
                ],
                playlists=[],
            )
            remapped, stats = remap_unified_db_for_patriot(db, patriot)
            self.assertEqual(stats["tracks_mapped"], 1)
            self.assertEqual(stats["tracks_mapped_from_disk_only"], 1)
            self.assertTrue(
                remapped.tracks[0].path.endswith("LABACK - My Heart Will Go On.m4a")
            )

    def test_remap_matches_unicode_nfd_filenames(self):
        """macOS NFD (ę) vs NFC (ę) — ta sama nazwa pliku."""
        import tempfile
        import unicodedata

        from engine_stems import remap_unified_db_for_patriot

        with tempfile.TemporaryDirectory() as td:
            patriot = Path(td) / "Patriot"
            music = patriot / "Music" / "Baciary"
            music.mkdir(parents=True)
            # Zapisz w NFD jak HFS+/APFS
            nfd_name = unicodedata.normalize("NFD", "Baciary - Ja Cię Kocham.m4a")
            (music / nfd_name).write_bytes(b"fake")

            mdb_dir = patriot / "Database2"
            mdb_dir.mkdir()
            conn = sqlite3.connect(str(mdb_dir / "m.db"))
            conn.executescript(
                """
                CREATE TABLE Information (uuid TEXT);
                INSERT INTO Information VALUES ('pat-uuid');
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY, path TEXT, title TEXT, artist TEXT,
                    isAvailable INTEGER, isAnalyzed INTEGER, bitrate INTEGER, fileBytes INTEGER
                );
                """
            )
            conn.commit()
            conn.close()

            nfc_src = "/Users/mac/Music/NJR/" + unicodedata.normalize(
                "NFC", "Baciary - Ja Cię Kocham.m4a"
            )
            db = UnifiedDatabase(
                tracks=[Track(path=nfc_src, title="Ja Cię Kocham", artist="Baciary")],
                playlists=[],
            )
            remapped, stats = remap_unified_db_for_patriot(db, patriot)
            self.assertEqual(stats["tracks_mapped"], 1)

    def test_repair_syncs_bpm_from_analyzed(self):
        import tempfile
        from engine_libdjinterop import repair_engine_post_merge

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_db(Path(td))
            import sqlite3

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            blob = b"x" * 600
            conn.execute(
                "UPDATE PerformanceData SET overviewWaveFormData=? WHERE trackId=2",
                (blob,),
            )
            conn.commit()
            conn.close()

            stats = repair_engine_post_merge(lib, min_waveform_bytes=500)
            self.assertEqual(stats["bpm_synced_from_analyzed"], 1)

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            bpm = conn.execute("SELECT bpm FROM Track WHERE path='b.mp3'").fetchone()[0]
            self.assertEqual(bpm, 128)
            conn.close()

    def test_snapshot_and_restore_preserves_waveforms(self):
        import tempfile
        from engine_libdjinterop import (
            restore_engine_performance,
            snapshot_engine_performance,
        )

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_db(Path(td))
            import sqlite3

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            good_wave = b"x" * 600
            conn.execute(
                "UPDATE PerformanceData SET overviewWaveFormData=? WHERE trackId=1",
                (good_wave,),
            )
            conn.commit()
            conn.close()

            snaps = snapshot_engine_performance(lib, {"a.mp3"}, min_waveform_bytes=500)
            self.assertIn("a.mp3", snaps)

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            conn.execute(
                "UPDATE PerformanceData SET overviewWaveFormData=X'0102' WHERE trackId=1"
            )
            conn.execute("UPDATE Track SET isAnalyzed=1 WHERE id=1")
            conn.commit()
            conn.close()

            stats = restore_engine_performance(lib, snaps, min_waveform_bytes=500)
            self.assertEqual(stats["waveforms_restored"], 1)

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            wave_len = conn.execute(
                "SELECT length(overviewWaveFormData) FROM PerformanceData WHERE trackId=1"
            ).fetchone()[0]
            self.assertEqual(wave_len, 600)
            conn.close()

    def test_snapshot_and_restore_preserves_cues_when_waveform_ok(self):
        import tempfile
        from engine_libdjinterop import (
            _ENGINE_STUB_CUE_BYTES,
            restore_engine_performance,
            snapshot_engine_performance,
        )

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_db(Path(td))
            import sqlite3

            good_cues = b"x" * (_ENGINE_STUB_CUE_BYTES + 40)
            good_wave = b"w" * 600
            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            conn.execute(
                """
                UPDATE PerformanceData
                SET overviewWaveFormData=?, quickCues=?
                WHERE trackId=1
                """,
                (good_wave, good_cues),
            )
            conn.commit()
            conn.close()

            snaps = snapshot_engine_performance(lib, {"a.mp3"}, min_waveform_bytes=500)
            self.assertTrue(snaps["a.mp3"]["had_cues"])

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            conn.execute(
                "UPDATE PerformanceData SET quickCues=? WHERE trackId=1",
                (b"\x00" * _ENGINE_STUB_CUE_BYTES,),
            )
            conn.commit()
            conn.close()

            stats = restore_engine_performance(lib, snaps, min_waveform_bytes=500)
            self.assertEqual(stats["cues_restored"], 1)
            self.assertEqual(stats["waveforms_restored"], 0)

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            cue_len = conn.execute(
                "SELECT length(quickCues) FROM PerformanceData WHERE trackId=1"
            ).fetchone()[0]
            self.assertGreater(cue_len, _ENGINE_STUB_CUE_BYTES)
            conn.close()

    def test_restore_cues_from_reference(self):
        import tempfile
        from engine_cues import restore_engine_cues_from_reference

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_db(Path(td))
            import sqlite3

            ref_mdb = Path(td) / "ref.db"
            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            good_cues = b"c" * 80
            conn.execute(
                "UPDATE PerformanceData SET quickCues=? WHERE trackId=1",
                (good_cues,),
            )
            conn.commit()
            conn.close()

            import shutil

            shutil.copy(lib / "Database2" / "m.db", ref_mdb)

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            conn.execute(
                "UPDATE PerformanceData SET quickCues=? WHERE trackId=1",
                (b"\x00" * 28,),
            )
            conn.commit()
            conn.close()

            stats = restore_engine_cues_from_reference(lib, ref_mdb)
            self.assertEqual(stats["cues_restored_from_reference"], 1)

            conn = sqlite3.connect(str(lib / "Database2" / "m.db"))
            cue_len = conn.execute(
                "SELECT length(quickCues) FROM PerformanceData WHERE trackId=1"
            ).fetchone()[0]
            self.assertEqual(cue_len, 80)
            conn.close()


class TestEngineAlbumArt(unittest.TestCase):
    def test_cover_hashes(self):
        from engine_album_art import _cover_hashes

        blob = b"fake-jpeg-data"
        bin_h, hex_h = _cover_hashes(blob)
        self.assertEqual(len(bin_h), 20)
        self.assertEqual(len(hex_h), 40)
        self.assertEqual(hex_h, bin_h.hex())

    def test_sync_clears_broken_shared_art(self):
        import tempfile
        from unittest.mock import patch
        from engine_album_art import sync_engine_album_art

        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            dbdir = lib / "Database2"
            dbdir.mkdir()
            mdb = dbdir / "m.db"
            conn = sqlite3.connect(str(mdb))
            conn.executescript(
                """
                CREATE TABLE AlbumArt (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hash TEXT,
                    albumArt BLOB
                );
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY,
                    path TEXT UNIQUE,
                    albumArtId INTEGER,
                    albumArtSourceHash TEXT
                );
                INSERT INTO AlbumArt (id, hash, albumArt) VALUES (1, X'aa', NULL);
                INSERT INTO Track (id, path, albumArtId) VALUES (10, 'a.mp3', 1);
                INSERT INTO Track (id, path, albumArtId) VALUES (11, 'b.mp3', 1);
                """
            )
            conn.commit()
            conn.close()

            cover_a = b"jpeg-a-bytes"
            cover_b = b"jpeg-b-bytes"

            def fake_extract(path: Path):
                if path.name == "a.mp3":
                    return cover_a
                if path.name == "b.mp3":
                    return cover_b
                return None

            with patch("engine_album_art.extract_embedded_cover", side_effect=fake_extract):
                stats = sync_engine_album_art(lib, {"a.mp3", "b.mp3"})

            self.assertEqual(stats["album_art_unique_added"], 2)
            self.assertGreaterEqual(stats["album_art_tracks_linked"], 2)

            conn = sqlite3.connect(str(mdb))
            self.assertIsNone(
                conn.execute("SELECT id FROM AlbumArt WHERE id=1").fetchone()
            )
            arts = conn.execute("SELECT COUNT(*) FROM AlbumArt").fetchone()[0]
            self.assertEqual(arts, 2)
            ids = conn.execute(
                "SELECT albumArtId FROM Track ORDER BY id"
            ).fetchall()
            self.assertNotEqual(ids[0][0], ids[1][0])
            conn.close()


class TestEngineFileInfo(unittest.TestCase):
    def test_probe_audio_file_info(self):
        from engine_file_info import probe_audio_file_info

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.mp3"
            p.write_bytes(b"\x00" * 12345)
            with patch("engine_file_info._get_bitrate", return_value=320):
                br, fb = probe_audio_file_info(p)
            self.assertEqual(br, 320)
            self.assertEqual(fb, 12345)

    def test_sync_engine_file_info(self):
        from engine_file_info import sync_engine_file_info

        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "Engine Library"
            dbdir = lib / "Database2"
            dbdir.mkdir(parents=True)
            mdb = dbdir / "m.db"
            (lib / "song.mp3").write_bytes(b"x" * 5000)
            conn = sqlite3.connect(str(mdb))
            conn.executescript(
                """
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY,
                    path TEXT UNIQUE,
                    bitrate INTEGER,
                    fileBytes INTEGER,
                    isAvailable INTEGER
                );
                INSERT INTO Track VALUES (1, 'song.mp3', 0, NULL, 1);
                """
            )
            conn.commit()
            conn.close()
            with patch("engine_file_info._get_bitrate", return_value=256):
                stats = sync_engine_file_info(lib, {"song.mp3"})
            self.assertEqual(stats["file_info_updated"], 1)
            conn = sqlite3.connect(str(mdb))
            row = conn.execute(
                "SELECT bitrate, fileBytes FROM Track WHERE id=1"
            ).fetchone()
            self.assertEqual(row, (256, 5000))
            conn.close()

    def test_track_export_includes_file_info(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.mp3"
            p.write_bytes(b"\x00" * 8000)
            with patch("engine_generator._guess_file_info", return_value=(192, 8000)):
                row = track_to_engine_json(
                    Track(path=str(p), title="A", bpm=120, duration=180),
                    engine_dir=Path(td) / "Engine Library",
                )
            self.assertEqual(row["bitrate"], 192)
            self.assertEqual(row["file_bytes"], 8000)


class TestEngineStems(unittest.TestCase):
    def _mini_engine(self, tmp: Path, uuid: str, tracks: list[tuple]) -> Path:
        """tracks: (id, path, title, artist)"""
        import sqlite3

        lib = tmp
        dbdir = lib / "Database2"
        stems = lib / "Stems"
        dbdir.mkdir(parents=True)
        stems.mkdir(parents=True)
        mdb = dbdir / "m.db"
        conn = sqlite3.connect(str(mdb))
        conn.executescript(
            f"""
            CREATE TABLE Information (id INTEGER PRIMARY KEY, uuid TEXT);
            INSERT INTO Information (id, uuid) VALUES (1, '{uuid}');
            CREATE TABLE Track (
                id INTEGER PRIMARY KEY, path TEXT, title TEXT, artist TEXT,
                isAvailable INTEGER DEFAULT 1, isAnalyzed INTEGER DEFAULT 1,
                bitrate INTEGER DEFAULT 320, fileBytes INTEGER DEFAULT 1000
            );
            CREATE TABLE Playlist (
                id INTEGER PRIMARY KEY, title TEXT, parentListId INTEGER,
                isPersisted INTEGER, nextListId INTEGER, lastEditTime INTEGER,
                isExplicitlyExported INTEGER
            );
            CREATE TABLE PlaylistEntity (
                id INTEGER PRIMARY KEY, listId INTEGER, trackId INTEGER,
                databaseUuid TEXT, nextEntityId INTEGER, membershipReference INTEGER
            );
            CREATE TABLE PerformanceData (trackId INTEGER PRIMARY KEY);
            """
        )
        for tid, path, title, artist in tracks:
            conn.execute(
                "INSERT INTO Track (id, path, title, artist) VALUES (?,?,?,?)",
                (tid, path, title, artist),
            )
        conn.commit()
        conn.close()
        return lib

    def test_migrate_stems_renames_track_id(self):
        import tempfile
        from unittest.mock import patch
        from engine_stems import list_stem_files, migrate_stems_to_patriot

        uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with tempfile.TemporaryDirectory() as td:
            mac = self._mini_engine(
                Path(td) / "mac",
                uuid,
                [(10, "Music/a.mp3", "Song A", "Artist")],
            )
            pat = self._mini_engine(
                Path(td) / "pat",
                "other-uuid-0000-0000-0000-000000000001",
                [(99, "Music/a.mp3", "Song A", "Artist")],
            )
            stem = mac / "Stems" / f"10 {uuid}.stems"
            stem.write_bytes(b"fake-stem-data" * 100)

            with patch("engine_stems.is_engine_desktop_running", return_value=False):
                stats = migrate_stems_to_patriot(mac, pat, delete_mac=True)
            self.assertEqual(stats["migrated"], 1)
            self.assertFalse(stem.exists())
            dest = pat / "Stems" / f"99 {uuid}.stems"
            self.assertTrue(dest.is_file())
            self.assertIn(99, list_stem_files(pat, library_uuid=uuid))

    def test_prepare_batch_playlist(self):
        import tempfile
        from engine_stems import STEMS_BATCH_PLAYLIST, prepare_stems_batch_playlist
        from engine_libdjinterop import is_engine_desktop_running

        if is_engine_desktop_running():
            self.skipTest("Engine DJ uruchomiony")

        uuid = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        with tempfile.TemporaryDirectory() as td:
            mac = self._mini_engine(
                Path(td) / "mac",
                uuid,
                [(1, "Music/x.mp3", "X", "Y"), (2, "Music/y.mp3", "Z", "W")],
            )
            pat = self._mini_engine(
                Path(td) / "pat",
                "pat-uuid",
                [(50, "Music/x.mp3", "X", "Y")],
            )
            out = prepare_stems_batch_playlist(mac, pat, batch_size=5)
            self.assertTrue(out.get("ok"))
            self.assertGreaterEqual(out.get("track_count", 0), 1)

            import sqlite3

            conn = sqlite3.connect(str(mac / "Database2" / "m.db"))
            lid = conn.execute(
                "SELECT id FROM Playlist WHERE title = ?", (STEMS_BATCH_PLAYLIST,)
            ).fetchone()
            self.assertIsNotNone(lid)
            cnt = conn.execute(
                "SELECT COUNT(*) FROM PlaylistEntity WHERE listId = ?", (lid[0],)
            ).fetchone()[0]
            self.assertGreater(cnt, 0)
            conn.close()


    def test_migrate_only_stable(self):
        import tempfile
        from unittest.mock import patch

        from engine_stems import _stem_file_stable, migrate_stems_to_patriot

        uuid = "dddddddd-eeee-ffff-0000-111111111111"
        with tempfile.TemporaryDirectory() as td:
            mac = self._mini_engine(
                Path(td) / "mac",
                uuid,
                [(10, "Music/a.mp3", "Song A", "Artist")],
            )
            pat = self._mini_engine(
                Path(td) / "pat",
                "other-uuid",
                [(99, "Music/a.mp3", "Song A", "Artist")],
            )
            stem = mac / "Stems" / f"10 {uuid}.stems"
            stem.write_bytes(b"x" * 200_000)
            stable_sizes: dict[str, int] = {}
            with patch("engine_stems.is_engine_desktop_running", return_value=True):
                first = migrate_stems_to_patriot(
                    mac,
                    pat,
                    allow_engine_running=True,
                    only_stable=True,
                    stable_sizes=stable_sizes,
                )
                self.assertEqual(first["migrated"], 0)
                second = migrate_stems_to_patriot(
                    mac,
                    pat,
                    allow_engine_running=True,
                    only_stable=True,
                    stable_sizes=stable_sizes,
                    delete_mac=True,
                )
            self.assertEqual(second["migrated"], 1)
            self.assertFalse(stem.exists())
            stable, _ = _stem_file_stable(stem, last_size=200_000)
            self.assertFalse(stable)


class TestEngineStemsRender(unittest.TestCase):
    def test_compute_auto_batch_size(self):
        from engine_stems_render import compute_auto_batch_size

        self.assertEqual(compute_auto_batch_size(30), 25)
        self.assertEqual(compute_auto_batch_size(22), 20)
        self.assertEqual(compute_auto_batch_size(18), 15)
        self.assertEqual(compute_auto_batch_size(14), 15)
        self.assertEqual(compute_auto_batch_size(8), 5)
        self.assertEqual(compute_auto_batch_size(4.9), 3)
        self.assertEqual(compute_auto_batch_size(None), 10)

    def test_resolve_batch_size(self):
        from engine_stems_render import resolve_batch_size

        self.assertEqual(resolve_batch_size(250, 4.9), 3)
        self.assertEqual(resolve_batch_size(250, 4.9, force=True), 250)
        self.assertEqual(resolve_batch_size(None, 14), 15)

    def test_wait_for_stems_files(self):
        import tempfile
        from unittest.mock import patch

        from engine_stems_render import wait_for_stems_files

        uuid = "cccccccc-dddd-eeee-ffff-000000000001"
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            stems = lib / "Stems"
            stems.mkdir()
            mdb_dir = lib / "Database2"
            mdb_dir.mkdir()
            import sqlite3

            conn = sqlite3.connect(str(mdb_dir / "m.db"))
            conn.execute("CREATE TABLE Information (id INTEGER PRIMARY KEY, uuid TEXT)")
            conn.execute("INSERT INTO Information (id, uuid) VALUES (1, ?)", (uuid,))
            conn.commit()
            conn.close()

            path = stems / f"42 {uuid}.stems"
            path.write_bytes(b"x" * 200_000)

            with patch("engine_stems_render.STEM_SIZE_STABLE_CHECKS", 1), patch(
                "engine_stems_render.STEM_SIZE_STABLE_INTERVAL_SEC", 0.01
            ):
                out = wait_for_stems_files(
                    lib, [42], library_uuid=uuid, timeout_sec=5, poll_sec=0.01
                )
            self.assertTrue(out["ok"])
            self.assertEqual(out["ready_count"], 1)


class TestEngineSchemaValidation(unittest.TestCase):
    def _make_db(self, tmp: Path, major: int, minor: int, patch: int) -> Path:
        lib = tmp / "Engine Library"
        dbdir = lib / "Database2"
        dbdir.mkdir(parents=True)
        mdb = dbdir / "m.db"
        conn = sqlite3.connect(mdb)
        conn.execute(
            """
            CREATE TABLE Information (
                id INTEGER PRIMARY KEY,
                uuid TEXT,
                schemaVersionMajor INTEGER,
                schemaVersionMinor INTEGER,
                schemaVersionPatch INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO Information
            (id, uuid, schemaVersionMajor, schemaVersionMinor, schemaVersionPatch)
            VALUES (1, 'test-uuid', ?, ?, ?)
            """,
            (major, minor, patch),
        )
        conn.execute("CREATE TABLE Track (id INTEGER PRIMARY KEY, path TEXT)")
        conn.commit()
        conn.close()
        return lib

    def test_new_library_ok(self):
        from engine_libdjinterop import validate_engine_schema

        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "Engine Library"
            lib.mkdir()
            r = validate_engine_schema(lib)
            self.assertTrue(r["ok"])
            self.assertTrue(r["new_library"])

    def test_schema_3_0_2_ok(self):
        from engine_libdjinterop import validate_engine_schema

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_db(Path(td), 3, 0, 2)
            r = validate_engine_schema(lib)
            self.assertTrue(r["ok"])
            self.assertEqual(r["schema"], "3.0.2")

    def test_schema_too_new_blocked(self):
        from engine_libdjinterop import assert_engine_schema_compatible

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_db(Path(td), 4, 0, 0)
            with self.assertRaises(RuntimeError) as ctx:
                assert_engine_schema_compatible(lib)
            self.assertIn("nowszy", str(ctx.exception).lower())

    def test_schema_too_old_blocked(self):
        from engine_libdjinterop import validate_engine_schema

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_db(Path(td), 2, 17, 0)
            r = validate_engine_schema(lib)
            self.assertFalse(r["ok"])
            self.assertTrue(any("za stary" in e for e in r["errors"]))

    def test_missing_auxiliary_warns(self):
        from engine_libdjinterop import validate_engine_schema

        with tempfile.TemporaryDirectory() as td:
            lib = self._make_db(Path(td), 3, 0, 2)
            mdb = lib / "Database2" / "m.db"
            mdb.write_bytes(mdb.read_bytes() + b"\0" * (2 * 1024 * 1024))
            r = validate_engine_schema(lib)
            self.assertTrue(r["ok"])
            self.assertTrue(
                any("hm.db" in w for w in r["warnings"]),
                r["warnings"],
            )


if __name__ == "__main__":
    unittest.main()
