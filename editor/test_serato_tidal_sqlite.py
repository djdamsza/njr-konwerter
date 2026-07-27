"""Testy ścieżek Serato Tidal: streaming://tidal/ID + stem → części kontenera."""
import unittest


class TestSeratoTidalStreamingPaths(unittest.TestCase):
    def test_vdj_to_streaming_uri(self):
        from vdj_streaming import (
            extract_tidal_id,
            is_serato_tidal_path,
            vdj_to_serato_tidal_path,
        )

        self.assertEqual(
            vdj_to_serato_tidal_path("netsearch://td348969829"),
            "streaming://tidal/348969829",
        )
        self.assertEqual(extract_tidal_id("streaming://tidal/99"), "99")
        self.assertEqual(extract_tidal_id("tidal:tracks:99"), "99")
        self.assertTrue(is_serato_tidal_path("streaming://tidal/1"))
        self.assertTrue(is_serato_tidal_path("tidal:tracks:1"))

    def test_crate_stem_to_parts(self):
        from serato_library_sqlite import _crate_stem_to_parts

        self.assertEqual(
            _crate_stem_to_parts("VDJ%%MyLists%%wesele bez DP"),
            ["wesele bez DP"],
        )
        self.assertEqual(
            _crate_stem_to_parts("MyLists%%18 07 26 wesele%%pierwszy taniec"),
            ["18 07 26 wesele", "pierwszy taniec"],
        )

    def test_prepare_splits_njr_and_streaming(self):
        import tempfile
        from pathlib import Path

        from unified_model import Playlist
        from serato_parser import _prepare_serato_crate_entries
        from vdjfolder import normalize_path

        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
            tmp.write(b"\x00" * 32)
            njr = tmp.name

        try:
            pl = Playlist(
                name="VDJ",
                track_ids=[],
                is_folder=True,
                children=[
                    Playlist(
                        name="MyLists",
                        track_ids=[],
                        is_folder=True,
                        children=[
                            Playlist(
                                name="testlista",
                                track_ids=[
                                    "netsearch://td111",
                                    "netsearch://td222",
                                ],
                                is_folder=False,
                            )
                        ],
                    )
                ],
            )
            subs = {normalize_path("netsearch://td111"): njr}
            prepared, streaming, njr_tids = _prepare_serato_crate_entries(
                [pl], path_substitutes=subs
            )
            hit = [t for s, t in prepared if s.endswith("testlista")]
            self.assertTrue(hit)
            local_tracks = hit[0]
            self.assertEqual(len(local_tracks), 1)
            stream_hit = [t for s, t in streaming if s.endswith("testlista")]
            self.assertTrue(stream_hit)
            self.assertEqual(stream_hit[0], ["streaming://tidal/222"])
            self.assertEqual(njr_tids, {"111"})
        finally:
            Path(njr).unlink(missing_ok=True)

    def test_normalize_mylists_stem(self):
        from serato_parser import normalize_serato_mylists_stem

        self.assertIsNone(normalize_serato_mylists_stem("VDJ"))
        self.assertEqual(
            normalize_serato_mylists_stem("VDJ%%MyLists%%lista"),
            "MyLists%%lista",
        )
        self.assertEqual(
            normalize_serato_mylists_stem("MyLists%%lista"),
            "MyLists%%lista",
        )
        self.assertIsNone(normalize_serato_mylists_stem("Sideview%%automix"))
        self.assertEqual(
            normalize_serato_mylists_stem("wszystkie pliki"),
            "wszystkie pliki",
        )
        self.assertEqual(
            normalize_serato_mylists_stem("VDJ Offline Cache"),
            "VDJ Offline Cache",
        )

    def test_find_master_creates_exact_path(self):
        """MyLists path is created under Serato Library root."""
        import sqlite3
        import tempfile
        from pathlib import Path

        from serato_library_sqlite import _find_master_containers

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            con = sqlite3.connect(str(db))
            con.executescript(
                """
                CREATE TABLE space (id INTEGER PRIMARY KEY, name TEXT);
                INSERT INTO space VALUES (5, 'Serato Library');
                CREATE TABLE container (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_id INTEGER,
                    name TEXT NOT NULL,
                    type INTEGER DEFAULT 1,
                    list_order INTEGER NOT NULL,
                    space_id INTEGER,
                    time_added INTEGER DEFAULT 0,
                    expanded INTEGER DEFAULT 0,
                    portable_id TEXT DEFAULT '',
                    color INTEGER,
                    UNIQUE(parent_id, name COLLATE NOCASE, type)
                );
                INSERT INTO container (id, parent_id, name, type, list_order, space_id)
                VALUES (1, 0, 'Serato Library root', 0, 1, 5);
                """
            )
            con.commit()
            mids = _find_master_containers(con, ["MyLists", "only-here"])
            self.assertEqual(len(mids), 1)
            row = con.execute(
                "SELECT c.name, p.name FROM container c JOIN container p ON p.id=c.parent_id WHERE c.id=?",
                (mids[0],),
            ).fetchone()
            self.assertEqual(row[0], "only-here")
            self.assertEqual(row[1], "MyLists")
            con.close()


class TestTidalMetadataGuards(unittest.TestCase):
    def test_is_tidal_placeholder_name(self):
        from serato_library_sqlite import is_tidal_placeholder_name

        self.assertTrue(is_tidal_placeholder_name("Tidal 528013885", "528013885"))
        self.assertTrue(is_tidal_placeholder_name("tidal 99", "99"))
        self.assertFalse(is_tidal_placeholder_name("My Real Track", "99"))
        self.assertTrue(is_tidal_placeholder_name(""))

    def test_upsert_does_not_overwrite_good_title_with_placeholder(self):
        import sqlite3
        import tempfile
        from pathlib import Path

        from serato_library_sqlite import _upsert_tidal_asset

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "tidal.sqlite"
            con = sqlite3.connect(str(db))
            con.executescript(
                """
                CREATE TABLE asset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    revision INTEGER DEFAULT 1,
                    portable_id TEXT,
                    file_name TEXT,
                    type TEXT,
                    format TEXT,
                    artist TEXT,
                    name TEXT,
                    album TEXT,
                    year TEXT,
                    bpm REAL,
                    key TEXT,
                    length_sec INTEGER,
                    length_ms INTEGER,
                    time_added INTEGER,
                    time_modified INTEGER,
                    third_party_type INTEGER,
                    type_specific_data TEXT
                );
                """
            )
            aid = _upsert_tidal_asset(con, "123", title="Good Title", artist="Artist")
            con.commit()
            _upsert_tidal_asset(con, "123", title="Tidal 123", artist="Artist")
            con.commit()
            name = con.execute("SELECT name FROM asset WHERE id=?", (aid,)).fetchone()[0]
            self.assertEqual(name, "Good Title")
            con.close()

    def test_resolve_tidal_metadata_prefers_vdj_song(self):
        from serato_library_sqlite import resolve_tidal_metadata_for_install

        songs = [
            {
                "FilePath": "netsearch://td777",
                "Tags.Title": "VDJ Title",
                "Tags.Author": "VDJ Artist",
            }
        ]
        meta = resolve_tidal_metadata_for_install(
            "777",
            {"777": {"Tags.Title": "Tidal 777"}},
            songs,
        )
        self.assertEqual(meta.get("Tags.Title"), "VDJ Title")
        self.assertEqual(meta.get("Tags.Author"), "VDJ Artist")

    def test_build_tidal_meta_index_merges_songs_over_vdjfolder(self):
        from serato_parser import build_tidal_meta_index

        vdjfolders = {
            "x.vdjfolder": (
                '<VirtualFolder><song path="netsearch://td42" title="Folder Title" artist="Folder Artist"/></VirtualFolder>'
            )
        }
        songs = [
            {
                "FilePath": "netsearch://td42",
                "Tags.Title": "Database Title",
                "Tags.Author": "Database Artist",
            }
        ]
        index = build_tidal_meta_index(vdjfolders, songs)
        self.assertEqual(index["42"]["Tags.Title"], "Database Title")
        self.assertEqual(index["42"]["Tags.Author"], "Database Artist")


if __name__ == "__main__":
    unittest.main()
