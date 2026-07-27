"""Testy hierarchii crate Serato (%%)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from serato_parser import iter_serato_crate_files, safe_serato_crate_segment
from unified_model import Playlist


class TestSeratoCrateTree(unittest.TestCase):
    def test_safe_segment(self):
        self.assertEqual(safe_serato_crate_segment("My Lists"), "My Lists")
        self.assertNotIn("%", safe_serato_crate_segment("a%b"))

    def test_nested_stems(self):
        tree = [
            Playlist(
                name="VDJ",
                track_ids=[],
                is_folder=True,
                children=[
                    Playlist(name="wszystkie pliki", track_ids=["/a.mp3"]),
                    Playlist(
                        name="MyLists",
                        track_ids=[],
                        is_folder=True,
                        children=[
                            Playlist(
                                name="gatunki",
                                track_ids=[],
                                is_folder=True,
                                children=[
                                    Playlist(name="HOUSE", track_ids=["/h1.mp3", "/h2.mp3"]),
                                ],
                            ),
                        ],
                    ),
                ],
            )
        ]
        entries = iter_serato_crate_files(tree)
        stems = [s for s, _ in entries]
        self.assertIn("VDJ", stems)
        self.assertIn("VDJ%%wszystkie pliki", stems)
        self.assertIn("VDJ%%MyLists", stems)
        self.assertIn("VDJ%%MyLists%%gatunki", stems)
        self.assertIn("VDJ%%MyLists%%gatunki%%HOUSE", stems)
        house = dict(entries)["VDJ%%MyLists%%gatunki%%HOUSE"]
        self.assertEqual(house, ["/h1.mp3", "/h2.mp3"])

        from serato_parser import normalize_serato_mylists_stem

        norm = [normalize_serato_mylists_stem(s) for s in stems]
        self.assertIn("MyLists", norm)
        self.assertIn("MyLists%%gatunki%%HOUSE", norm)
        self.assertNotIn("VDJ%%MyLists%%gatunki%%HOUSE", norm)
        self.assertIsNone(normalize_serato_mylists_stem("VDJ%%Sideview%%automix"))
        self.assertIsNone(normalize_serato_mylists_stem("Folders%%filters"))
        self.assertEqual(
            normalize_serato_mylists_stem("VDJ%%wszystkie pliki"),
            "wszystkie pliki",
        )

    def test_remove_vdj_smart_crates(self):
        import tempfile
        from serato_parser import remove_vdj_smart_crates

        with tempfile.TemporaryDirectory() as tmp:
            smart = Path(tmp) / "SmartCrates"
            smart.mkdir()
            (smart / "VDJ≫≫MyLists≫≫PARTY.scrate").write_bytes(b"x")
            (smart / "OTHER.scrate").write_bytes(b"y")
            stats = remove_vdj_smart_crates(tmp, dry_run=False)
            self.assertIn("VDJ≫≫MyLists≫≫PARTY.scrate", stats["removed"])
            self.assertFalse((smart / "VDJ≫≫MyLists≫≫PARTY.scrate").exists())
            self.assertTrue((smart / "OTHER.scrate").exists())

    def test_grow_merge_linki(self):
        from serato_parser import (
            apply_grow_merge_to_prepared_entries,
            keep_existing_local_crate_paths,
            merge_grow_crate_track_paths,
            remove_excluded_transfer_subcrates,
            save_serato_crate,
            snapshot_grow_crate_tracks,
        )
        from vdjfolder import is_grow_serato_crate

        self.assertTrue(is_grow_serato_crate(name="LINKI"))
        self.assertTrue(is_grow_serato_crate(filter_text="Has Links = 1"))
        self.assertFalse(is_grow_serato_crate(name="PARTY"))

        merged = merge_grow_crate_track_paths(
            ["/Users/a/old.mp3", "Users/a/old.mp3"],
            ["/Users/a/new.mp3", "/Users/a/old.mp3"],
        )
        self.assertEqual(len(merged), 2)

        # keep_existing — tylko realne pliki
        self.assertEqual(keep_existing_local_crate_paths(["streaming://tidal/1"]), [])

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sub = base / "Subcrates"
            sub.mkdir()
            # prawdziwy plik do grow
            real = Path(tmp) / "track.mp3"
            real.write_bytes(b"ID3")
            stem = "MyLists%%kreatywne listy%%LINKI"
            (sub / f"{stem}.crate").write_bytes(
                save_serato_crate(
                    [str(real)],
                    stem,
                    existing_files_only=False,
                    path_style="absolute",
                )
            )
            (sub / "MyLists%%Folders%%Filters%%Compatible songs.crate").write_bytes(b"x")
            (sub / "Sideview%%automix.crate").write_bytes(b"x")
            (sub / "Folders%%filters.crate").write_bytes(b"x")
            (sub / "wszystkie pliki.crate").write_bytes(b"x")
            (sub / "VDJ Offline Cache.crate").write_bytes(b"x")
            snap = snapshot_grow_crate_tracks(base, drive_root=None)
            self.assertIn("linki", snap)
            self.assertEqual(len(snap["linki"]), 1)
            prepared = apply_grow_merge_to_prepared_entries(
                [(stem, [str(real)])], snap
            )
            tracks = dict(prepared)[stem]
            self.assertEqual(len(tracks), 1)
            ex = remove_excluded_transfer_subcrates(base, dry_run=False)
            self.assertIn("MyLists%%Folders%%Filters%%Compatible songs.crate", ex["removed"])
            self.assertIn("Sideview%%automix.crate", ex["removed"])
            self.assertIn("Folders%%filters.crate", ex["removed"])
            self.assertFalse(
                (sub / "MyLists%%Folders%%Filters%%Compatible songs.crate").exists()
            )
            self.assertTrue((sub / "wszystkie pliki.crate").exists())
            self.assertTrue((sub / "VDJ Offline Cache.crate").exists())
            self.assertTrue((sub / f"{stem}.crate").exists())

    def test_sync_grow_crate_flat_alias_writes_crate_files(self):
        from serato_library_sqlite import sync_grow_crate_flat_alias

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            sub = base / "Subcrates"
            sub.mkdir()
            real = Path(tmp) / "track.mp3"
            real.write_bytes(b"ID3")
            stem = "MyLists%%kreatywne listy%%LINKI"
            stats = sync_grow_crate_flat_alias(
                stem,
                [str(real)],
                serato_dir=base,
                drive_root="/",
                path_style="absolute",
            )
            self.assertTrue(stats.get("ok"))
            self.assertEqual(stats.get("flat_stem"), "MyLists%%LINKI")
            flat = sub / "MyLists%%LINKI.crate"
            parent = sub / "MyLists%%kreatywne listy.crate"
            self.assertTrue(flat.is_file())
            self.assertTrue(parent.is_file())
            self.assertGreater(stats.get("crate_tracks", 0), 0)

    def test_repair_master_sqlite_foreign_keys(self):
        import sqlite3
        import tempfile

        from serato_library_sqlite import repair_master_sqlite_foreign_keys

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            con = sqlite3.connect(str(db))
            con.executescript(
                """
                CREATE TABLE location (id INTEGER PRIMARY KEY, revision INTEGER, last_sync_time INTEGER);
                INSERT INTO location VALUES (1, 1, 0);
                CREATE TABLE container (id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT);
                INSERT INTO container VALUES (1, 0, 'MyLists'), (2, 1, 'LINKI');
                CREATE TABLE location_container (id INTEGER PRIMARY KEY, container_id INTEGER, location_id INTEGER, external_container_id INTEGER);
                INSERT INTO location_container VALUES (99, 2, 1, 100);
                CREATE TABLE container_asset (id INTEGER PRIMARY KEY, location_container_id INTEGER, space_asset_id INTEGER);
                INSERT INTO container_asset VALUES (1, 99, 1), (2, 999, 1);
                """
            )
            con.commit()
            con.close()
            result = repair_master_sqlite_foreign_keys(Path(tmp))
            self.assertTrue(result.get("ok"))
            self.assertGreaterEqual(result.get("removed_orphan_container_asset", 0), 1)
            con = sqlite3.connect(str(db))
            fk = list(con.execute("PRAGMA foreign_key_check"))
            con.close()
            self.assertEqual(fk, [])


if __name__ == "__main__":
    unittest.main()