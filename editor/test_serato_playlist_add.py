"""Dopisanie utworu do listy Serato zapisuje crate i master.sqlite."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from serato_library_sqlite import append_track_to_live_playlist, sync_live_serato_playlists
from serato_parser import load_serato_crate, save_serato_crate


class SeratoPlaylistAddTests(unittest.TestCase):
    def test_disk_track_lands_in_crate_and_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            track = "/Users/test/Desktop/muzyka dj/Scooter - Maria (I Like It Loud).mp3"
            crate = root / "MyLists%%gatunki%%TECHNO _1.crate"
            copy_crate = root / "Serato%%Serato%%MyLists%%gatunki%%TECHNO _1.crate"
            payload = save_serato_crate(
                ["/Users/test/Desktop/muzyka dj/inne.mp3"],
                "TECHNO _1",
                "/",
                path_style="relative",
                existing_files_only=False,
            )
            crate.write_bytes(payload)
            copy_crate.write_bytes(payload)
            library = root / "master.sqlite"
            con = sqlite3.connect(library)
            con.executescript(
                """
                CREATE TABLE container (
                    id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT
                );
                CREATE TABLE asset (
                    id INTEGER PRIMARY KEY, location_id INTEGER, portable_id TEXT
                );
                CREATE TABLE space_asset (
                    id INTEGER PRIMARY KEY, asset_id INTEGER, space_id INTEGER
                );
                CREATE TABLE location_container (
                    id INTEGER PRIMARY KEY, container_id INTEGER, location_id INTEGER
                );
                CREATE TABLE container_asset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    location_container_id INTEGER NOT NULL,
                    space_asset_id INTEGER NOT NULL,
                    external_container_asset_id INTEGER,
                    list_order INTEGER NOT NULL,
                    time_added INTEGER NOT NULL
                );
                INSERT INTO container VALUES (1, 0, 'Serato Library root');
                INSERT INTO container VALUES (2, 1, 'MyLists');
                INSERT INTO container VALUES (3, 2, 'gatunki');
                INSERT INTO container VALUES (4, 3, 'TECHNO _1');
                INSERT INTO container VALUES (5, 1, 'Serato');
                INSERT INTO container VALUES (6, 5, 'MyLists');
                INSERT INTO container VALUES (7, 6, 'gatunki');
                INSERT INTO container VALUES (8, 7, 'TECHNO _1');
                INSERT INTO container VALUES (9, 1, 'Serato');
                INSERT INTO container VALUES (10, 9, 'Serato');
                INSERT INTO container VALUES (11, 10, 'MyLists');
                INSERT INTO container VALUES (12, 11, 'gatunki');
                INSERT INTO container VALUES (13, 12, 'TECHNO _1');
                INSERT INTO asset VALUES (10, 1, 'Users/test/Desktop/muzyka dj/Scooter - Maria (I Like It Loud).mp3');
                INSERT INTO space_asset VALUES (10, 10, 1);
                INSERT INTO location_container VALUES (40, 4, 1);
                INSERT INTO location_container VALUES (80, 8, 1);
                INSERT INTO location_container VALUES (130, 13, 1);
                """
            )
            con.commit()
            con.close()
            saved = append_track_to_live_playlist(
                "MyLists / gatunki / TECHNO _1",
                track,
                library_path=library,
                crate_path=crate,
            )
            self.assertTrue(saved["ok"])
            self.assertTrue(saved["sqlite"])
            playlist = load_serato_crate(crate.read_bytes(), crate.stem, drive_root="/")
            visible = load_serato_crate(copy_crate.read_bytes(), copy_crate.stem, drive_root="/")
            self.assertTrue(any("Maria" in item for item in playlist.track_ids))
            self.assertTrue(any("Maria" in item for item in visible.track_ids))
            con = sqlite3.connect(library)
            on_real = con.execute(
                "SELECT COUNT(*) FROM container_asset WHERE location_container_id=40 AND asset_id=10"
            ).fetchone()[0]
            on_copy = con.execute(
                "SELECT COUNT(*) FROM container_asset WHERE location_container_id=80 AND asset_id=10"
            ).fetchone()[0]
            on_visible = con.execute(
                "SELECT COUNT(*) FROM container_asset WHERE location_container_id=130 AND asset_id=10"
            ).fetchone()[0]
            external = con.execute(
                "SELECT external_container_asset_id FROM container_asset WHERE asset_id=10"
            ).fetchall()
            con.close()
            self.assertEqual(on_real, 1)
            self.assertEqual(on_copy, 1)
            self.assertEqual(on_visible, 1)
            self.assertTrue(all(row[0] for row in external))

    def test_tidal_track_uses_its_own_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "master.sqlite"
            con = sqlite3.connect(library)
            con.executescript(
                """
                CREATE TABLE container (
                    id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT
                );
                CREATE TABLE asset (
                    id INTEGER PRIMARY KEY, location_id INTEGER, portable_id TEXT
                );
                CREATE TABLE space_asset (
                    id INTEGER PRIMARY KEY, asset_id INTEGER, space_id INTEGER
                );
                CREATE TABLE location_container (
                    id INTEGER PRIMARY KEY, container_id INTEGER, location_id INTEGER,
                    external_container_id INTEGER
                );
                CREATE TABLE container_asset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    location_container_id INTEGER NOT NULL,
                    space_asset_id INTEGER NOT NULL,
                    external_container_asset_id INTEGER,
                    list_order INTEGER NOT NULL,
                    time_added INTEGER NOT NULL
                );
                INSERT INTO container VALUES (1, 0, 'Serato Library root');
                INSERT INTO container VALUES (2, 1, 'MyLists');
                INSERT INTO container VALUES (3, 2, 'gatunki');
                INSERT INTO container VALUES (4, 3, 'DISCO-POLO _1');
                INSERT INTO container VALUES (5, 1, 'Serato');
                INSERT INTO container VALUES (6, 5, 'Serato');
                INSERT INTO container VALUES (7, 6, 'MyLists');
                INSERT INTO container VALUES (8, 7, 'gatunki');
                INSERT INTO container VALUES (9, 8, 'DISCO-POLO _1');
                INSERT INTO asset VALUES (20, 4, 'streaming://tidal/26475968');
                INSERT INTO space_asset VALUES (20, 20, 12);
                INSERT INTO location_container VALUES (40, 4, 1, 10);
                INSERT INTO location_container VALUES (90, 9, 1, 11);
                """
            )
            con.commit()
            con.close()
            saved = append_track_to_live_playlist(
                "MyLists / gatunki / DISCO-POLO _1",
                "netsearch://td26475968",
                library_path=library,
                crate_path=root / "brak.crate",
            )
            self.assertTrue(saved["ok"], saved)
            con = sqlite3.connect(library)
            tidal_links = con.execute(
                """
                SELECT lc.container_id, lc.location_id
                FROM container_asset ca
                JOIN location_container lc ON lc.id = ca.location_container_id
                WHERE ca.asset_id=20
                ORDER BY lc.container_id
                """
            ).fetchall()
            on_file_location = con.execute(
                """
                SELECT COUNT(*) FROM container_asset ca
                JOIN location_container lc ON lc.id = ca.location_container_id
                WHERE ca.asset_id=20 AND lc.location_id=1
                """
            ).fetchone()[0]
            con.close()
            self.assertEqual(tidal_links, [(4, 4), (9, 4)])
            self.assertEqual(on_file_location, 0)

    def test_sync_adds_known_file_without_per_row_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "master.sqlite"
            con = sqlite3.connect(library)
            con.executescript(
                """
                CREATE TABLE container (
                    id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT
                );
                CREATE TABLE asset (
                    id INTEGER PRIMARY KEY, location_id INTEGER, portable_id TEXT
                );
                CREATE TABLE space_asset (
                    id INTEGER PRIMARY KEY, asset_id INTEGER, space_id INTEGER
                );
                CREATE TABLE location_container (
                    id INTEGER PRIMARY KEY, container_id INTEGER, location_id INTEGER,
                    external_container_id INTEGER
                );
                CREATE TABLE container_asset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    location_container_id INTEGER NOT NULL,
                    space_asset_id INTEGER NOT NULL,
                    external_container_asset_id INTEGER,
                    list_order INTEGER NOT NULL,
                    time_added INTEGER NOT NULL
                );
                INSERT INTO container VALUES (1, 0, 'Serato Library root');
                INSERT INTO container VALUES (2, 1, 'MyLists');
                INSERT INTO container VALUES (3, 2, 'gatunki');
                INSERT INTO container VALUES (4, 3, 'DISCO-POLO _1');
                INSERT INTO asset VALUES
                    (10, 1, 'Users/test/Desktop/muzyka dj/a.mp3'),
                    (11, 1, 'Users/test/Desktop/muzyka dj/b.mp3');
                INSERT INTO space_asset VALUES (10, 10, 1), (11, 11, 1);
                INSERT INTO location_container VALUES (40, 4, 1, 10);
                INSERT INTO container_asset (
                    asset_id, location_container_id, space_asset_id,
                    external_container_asset_id, list_order, time_added
                ) VALUES (10, 40, 10, 1, 1, 1);
                """
            )
            con.commit()
            con.close()
            saved = sync_live_serato_playlists(
                [(
                    "MyLists / gatunki / DISCO-POLO _1",
                    [
                        "/Users/test/Desktop/muzyka dj/a.mp3",
                        "/Users/test/Desktop/muzyka dj/b.mp3",
                        "streaming://tidal/999",
                    ],
                )],
                library_path=library,
            )
            self.assertTrue(saved["ok"], saved)
            self.assertEqual(saved["added"], 1)
            self.assertEqual(saved["skipped"], 1)
            con = sqlite3.connect(library)
            ids = [
                row[0]
                for row in con.execute(
                    "SELECT asset_id FROM container_asset WHERE location_container_id=40 ORDER BY asset_id"
                )
            ]
            con.close()
            self.assertEqual(ids, [10, 11])

    def test_tidal_on_library_list_uses_library_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "master.sqlite"
            con = sqlite3.connect(library)
            con.executescript(
                """
                CREATE TABLE container (
                    id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT, space_id INTEGER
                );
                CREATE TABLE asset (
                    id INTEGER PRIMARY KEY, location_id INTEGER, portable_id TEXT
                );
                CREATE TABLE space_asset (
                    id INTEGER PRIMARY KEY, asset_id INTEGER, space_id INTEGER
                );
                CREATE TABLE location_container (
                    id INTEGER PRIMARY KEY, container_id INTEGER, location_id INTEGER,
                    external_container_id INTEGER
                );
                CREATE TABLE container_asset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    location_container_id INTEGER NOT NULL,
                    space_asset_id INTEGER NOT NULL,
                    external_container_asset_id INTEGER,
                    list_order INTEGER NOT NULL,
                    time_added INTEGER NOT NULL
                );
                INSERT INTO container VALUES (1, 0, 'Serato Library root', 5);
                INSERT INTO container VALUES (2, 1, 'MyLists', 5);
                INSERT INTO container VALUES (3, 2, 'genre', 5);
                INSERT INTO container VALUES (4, 3, 'Techno', 5);
                INSERT INTO asset VALUES (30, 4, 'streaming://tidal/71508889');
                INSERT INTO space_asset VALUES (90, 30, 12);
                INSERT INTO location_container VALUES (40, 4, 1, 10);
                """
            )
            con.commit()
            con.close()
            saved = append_track_to_live_playlist(
                "MyLists / genre / Techno",
                "streaming://tidal/71508889",
                library_path=library,
                crate_path=Path(tmp) / "brak.crate",
            )
            self.assertTrue(saved["ok"], saved)
            con = sqlite3.connect(library)
            row = con.execute(
                """
                SELECT sa.space_id, lc.location_id
                FROM container_asset ca
                JOIN space_asset sa ON sa.id = ca.space_asset_id
                JOIN location_container lc ON lc.id = ca.location_container_id
                WHERE ca.asset_id=30
                """
            ).fetchone()
            con.close()
            self.assertEqual(row, (5, 4))

    def test_missing_tidal_track_is_added_to_the_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "master.sqlite"
            con = sqlite3.connect(library)
            con.executescript(
                """
                CREATE TABLE container (
                    id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT, space_id INTEGER
                );
                CREATE TABLE asset (
                    id INTEGER PRIMARY KEY,
                    external_id INTEGER NOT NULL,
                    location_id INTEGER NOT NULL,
                    portable_id TEXT NOT NULL,
                    file_name TEXT,
                    type TEXT NOT NULL DEFAULT '',
                    format TEXT NOT NULL DEFAULT '',
                    artist TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL DEFAULT '',
                    album TEXT NOT NULL DEFAULT '',
                    year TEXT NOT NULL DEFAULT '',
                    genre TEXT NOT NULL DEFAULT '',
                    key TEXT NOT NULL DEFAULT '',
                    time_added INTEGER NOT NULL DEFAULT 0,
                    time_modified INTEGER NOT NULL DEFAULT 0,
                    third_party_type INTEGER,
                    type_specific_data TEXT
                );
                CREATE TRIGGER after_asset_insert AFTER INSERT ON asset
                BEGIN
                    SELECT serato_str_norm(new.name);
                END;
                CREATE TABLE space_asset (
                    id INTEGER PRIMARY KEY, asset_id INTEGER, space_id INTEGER
                );
                CREATE TABLE location_container (
                    id INTEGER PRIMARY KEY, container_id INTEGER, location_id INTEGER,
                    external_container_id INTEGER
                );
                CREATE TABLE container_asset (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id INTEGER NOT NULL,
                    location_container_id INTEGER NOT NULL,
                    space_asset_id INTEGER NOT NULL,
                    external_container_asset_id INTEGER,
                    list_order INTEGER NOT NULL,
                    time_added INTEGER NOT NULL
                );
                INSERT INTO container VALUES (1, 0, 'Serato Library root', 5);
                INSERT INTO container VALUES (2, 1, 'MyLists', 5);
                INSERT INTO container VALUES (3, 2, 'genre', 5);
                INSERT INTO container VALUES (4, 3, 'Techno', 5);
                INSERT INTO location_container VALUES (40, 4, 1, 10);
                """
            )
            con.commit()
            con.close()
            saved = append_track_to_live_playlist(
                "MyLists / genre / Techno",
                "streaming://tidal/123456",
                library_path=library,
                crate_path=Path(tmp) / "brak.crate",
                artist="Sek Noel",
                title="Loca People",
            )
            self.assertTrue(saved["ok"], saved)
            con = sqlite3.connect(library)
            asset = con.execute(
                "SELECT artist, name, portable_id, location_id FROM asset"
            ).fetchone()
            space = con.execute(
                "SELECT space_id FROM space_asset ORDER BY space_id"
            ).fetchone()
            con.close()
            self.assertEqual(asset, ("Sek Noel", "Loca People", "streaming://tidal/123456", 4))
            self.assertEqual(space[0], 5)


if __name__ == "__main__":
    unittest.main()
