"""Podpięcie znalezionego pliku nie może zostawić listy na starej ścieżce."""
import sqlite3
import unittest
from pathlib import Path

from serato_library_sqlite import (
    _adopt_missing_same_filename,
    _merge_master_asset_into,
    rewrite_serato_blob_paths,
)
from serato_parser import (
    _encode_utf16be,
    _otrk_path_and_flags,
    _write_serato_record,
    dedupe_serato_database_v2,
    fill_otrk_missing_text_tags,
    restore_missing_v2_text_tags,
)


def _asset_table(con):
    con.execute(
        """
        CREATE TABLE asset (
            id INTEGER PRIMARY KEY,
            revision INTEGER,
            portable_id TEXT,
            file_name TEXT,
            file_size INTEGER,
            is_missing INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE space_asset (
            id INTEGER PRIMARY KEY,
            asset_id INTEGER,
            space_id INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE container_asset (
            id INTEGER PRIMARY KEY,
            asset_id INTEGER,
            location_container_id INTEGER,
            space_asset_id INTEGER,
            external_container_asset_id INTEGER,
            list_order INTEGER,
            time_added INTEGER
        )
        """
    )
    con.execute("CREATE TABLE dj_asset_metadata (asset_id INTEGER PRIMARY KEY)")


class RelinkTests(unittest.TestCase):
    def test_adopt_rewrites_missing_path_instead_of_second_row(self):
        found = Path(__file__).resolve().parent / "_relink_probe.mp3"
        found.write_bytes(b"mp3")
        self.addCleanup(lambda: found.unlink(missing_ok=True))
        portable = str(found).lstrip("/")
        con = sqlite3.connect(":memory:")
        _asset_table(con)
        con.execute(
            "INSERT INTO asset VALUES (1, 1, ?, ?, 10, 1)",
            ("Users/test/Downloads/" + found.name, found.name),
        )
        self.assertIsNone(_adopt_missing_same_filename(con, "Users/test/Desktop/nie-ma-takiego.mp3"))
        adopted = _adopt_missing_same_filename(con, portable)
        self.assertEqual(adopted, 1)
        row = con.execute("SELECT portable_id, is_missing FROM asset WHERE id=1").fetchone()
        self.assertEqual(row[0], portable)
        self.assertEqual(row[1], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM asset").fetchone()[0], 1)

    def test_merge_moves_crate_off_dead_copy(self):
        con = sqlite3.connect(":memory:")
        _asset_table(con)
        con.execute(
            "INSERT INTO asset VALUES (1, 1, 'Users/test/Downloads/a.mp3', 'a.mp3', 1, 1)"
        )
        con.execute(
            "INSERT INTO asset VALUES (2, 1, 'Users/test/Desktop/muzyka dj/a.mp3', 'a.mp3', 1, 0)"
        )
        con.execute("INSERT INTO space_asset VALUES (10, 1, 5)")
        con.execute("INSERT INTO space_asset VALUES (20, 2, 5)")
        con.execute("INSERT INTO container_asset VALUES (7, 1, 3, 10, 99, 1, 0)")
        merged = _merge_master_asset_into(con, loser_id=1, winner_id=2)
        self.assertTrue(merged["merged"])
        self.assertEqual(merged["moved"], 1)
        row = con.execute("SELECT asset_id, space_asset_id FROM container_asset").fetchone()
        self.assertEqual(row, (2, 20))
        self.assertIsNone(con.execute("SELECT id FROM asset WHERE id=1").fetchone())

    def test_blob_path_replace_keeps_other_tracks(self):
        import io

        payload = _encode_utf16be("Users/test/Downloads/a.mp3")
        out = io.BytesIO()
        _write_serato_record(out, "ptrk", payload)
        _write_serato_record(out, "vrsn", b"\x00\x00")
        updated, changed = rewrite_serato_blob_paths(
            out.getvalue(),
            {"Users/test/Downloads/a.mp3": "Users/test/Desktop/muzyka dj/a.mp3"},
        )
        self.assertEqual(changed, 1)
        self.assertIn("muzyka dj".encode("utf-16-be"), updated)
        self.assertIn(b"vrsn", updated)

    def test_restore_blank_tags_from_snapshot(self):
        import tempfile

        from serato_library_sqlite import restore_blank_serato_asset_metadata

        tmp = Path(tempfile.mkdtemp())
        lib = tmp / "lib"
        lib.mkdir()
        snap = tmp / "snap.sqlite"

        def schema(path):
            con = sqlite3.connect(path)
            con.execute(
                """
                CREATE TABLE asset (
                    id INTEGER PRIMARY KEY,
                    portable_id TEXT,
                    artist TEXT, name TEXT, album TEXT, genre TEXT, comments TEXT,
                    label TEXT, remixer TEXT, grouping TEXT, composer TEXT, year TEXT,
                    key TEXT, bpm REAL, length_sec INTEGER, length_ms INTEGER,
                    rating REAL, key_value INTEGER, time_added INTEGER,
                    time_modified INTEGER, revision INTEGER
                )
                """
            )
            con.execute(
                """
                CREATE TRIGGER after_asset_update
                AFTER UPDATE OF artist, name, key ON asset
                BEGIN
                    UPDATE asset SET key_value = serato_raw_key_string_to_key_type(key)
                    WHERE id = new.id;
                END
                """
            )
            con.commit()
            con.close()

        schema(snap)
        schema(lib / "master.sqlite")
        con = sqlite3.connect(snap)
        con.execute(
            "INSERT INTO asset (id, portable_id, artist, name, bpm, key, key_value, time_added) "
            "VALUES (1, 'Users/test/Music/a.m4a', 'Khaled', 'C''est la vie', 130, 'Eb', 12, 100)"
        )
        con.commit()
        con.close()
        con = sqlite3.connect(lib / "master.sqlite")
        con.execute(
            "INSERT INTO asset (id, portable_id, artist, name, time_added) "
            "VALUES (1, 'Users/test/Music/a.m4a', '', '', 999)"
        )
        con.execute(
            "INSERT INTO asset (id, portable_id, artist, name, bpm) "
            "VALUES (2, 'Users/test/Music/b.m4a', 'Filled', 'Stay', 100)"
        )
        con.commit()
        con.close()

        stats = restore_blank_serato_asset_metadata(
            lib, snapshot_paths=[snap], dry_run=False
        )
        self.assertTrue(stats["ok"])
        self.assertEqual(stats["restored"]["master.sqlite"], 1)
        con = sqlite3.connect(lib / "master.sqlite")
        blank = con.execute(
            "SELECT artist, name, bpm, key, key_value, time_added FROM asset WHERE id=1"
        ).fetchone()
        kept = con.execute("SELECT artist, name, bpm FROM asset WHERE id=2").fetchone()
        con.close()
        self.assertEqual(blank, ("Khaled", "C'est la vie", 130, "Eb", 12, 100))
        self.assertEqual(kept, ("Filled", "Stay", 100))

    def test_v2_stub_gets_title_without_changing_path(self):
        buf = __import__("io").BytesIO()
        _write_serato_record(buf, "pfil", _encode_utf16be("Users/test/Music/a.m4a"))
        _write_serato_record(buf, "bmis", b"\x00")
        updated, added = fill_otrk_missing_text_tags(
            buf.getvalue(),
            {"tsng": "C'est la vie", "tart": "Khaled", "pfil": "SHOULD-NOT-APPLY"},
        )
        self.assertEqual(added, 2)
        path, has_title, has_artist = _otrk_path_and_flags(updated)
        self.assertEqual(path, "Users/test/Music/a.m4a")
        self.assertTrue(has_title and has_artist)
        again, added_again = fill_otrk_missing_text_tags(updated, {"tsng": "Other"})
        self.assertEqual(added_again, 0)
        self.assertEqual(again, updated)

        top = __import__("io").BytesIO()
        _write_serato_record(top, "vrsn", _encode_utf16be("2.0"))
        _write_serato_record(top, "otrk", buf.getvalue())
        new, stats = restore_missing_v2_text_tags(
            top.getvalue(),
            {"users/test/music/a.m4a": {"tsng": "C'est la vie", "tart": "Khaled"}},
        )
        self.assertEqual(stats["filled"], 1)
        self.assertIn("Khaled".encode("utf-16-be"), new)
        self.assertIn(b"vrsn", new)

    def test_dedupe_keeps_tagged_record_over_path_only_copy(self):
        rich = __import__("io").BytesIO()
        _write_serato_record(rich, "pfil", _encode_utf16be("/Users/test/Music/a.m4a"))
        _write_serato_record(rich, "tsng", _encode_utf16be("C'est la vie"))
        _write_serato_record(rich, "tart", _encode_utf16be("Khaled"))
        stub = __import__("io").BytesIO()
        _write_serato_record(stub, "pfil", _encode_utf16be("Users/test/Music/a.m4a"))
        top = __import__("io").BytesIO()
        _write_serato_record(top, "vrsn", _encode_utf16be("2.0"))
        _write_serato_record(top, "otrk", rich.getvalue())
        _write_serato_record(top, "otrk", stub.getvalue())
        new, stats = dedupe_serato_database_v2(top.getvalue(), prefer_style="relative")
        self.assertEqual(stats["kept"], 1)
        self.assertIn("Khaled".encode("utf-16-be"), new)
        self.assertIn("C'est la vie".encode("utf-16-be"), new)


if __name__ == "__main__":
    unittest.main()
