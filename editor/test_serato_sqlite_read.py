"""Serato 4: master + root + tidal z jednej kopii → jedna biblioteka i XML rekordbox."""
import sqlite3
import unittest
import zipfile
from pathlib import Path


_ASSET = """
CREATE TABLE asset (
    id INTEGER PRIMARY KEY,
    portable_id TEXT,
    file_name TEXT,
    artist TEXT,
    name TEXT,
    album TEXT,
    genre TEXT,
    key TEXT,
    bpm REAL,
    length_sec INTEGER,
    length_ms INTEGER,
    rating REAL,
    comments TEXT,
    year TEXT,
    dj_play_count INTEGER
);
CREATE TABLE space_asset (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER,
    space_id INTEGER
);
CREATE TABLE container (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER,
    name TEXT,
    type INTEGER,
    list_order INTEGER,
    space_id INTEGER
);
CREATE TABLE container_asset (
    id INTEGER PRIMARY KEY,
    container_id INTEGER,
    space_asset_id INTEGER,
    list_order INTEGER
);
"""

_MASTER = """
CREATE TABLE space (id INTEGER PRIMARY KEY, name TEXT);
INSERT INTO space VALUES (5, 'Serato Library');
CREATE TABLE container (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER,
    name TEXT,
    type INTEGER,
    list_order INTEGER,
    space_id INTEGER
);
INSERT INTO container VALUES
    (1, 0, 'Serato Library root', 0, 0, 5),
    (2, 1, 'MyLists', 0, 1, 5),
    (3, 2, 'wesele', 1, 1, 5);
CREATE TABLE location (id INTEGER PRIMARY KEY, path TEXT);
INSERT INTO location VALUES (1, ''), (2, '');
CREATE TABLE connection (location_id INTEGER PRIMARY KEY, database_uri TEXT);
CREATE TABLE location_container (
    id INTEGER PRIMARY KEY,
    container_id INTEGER,
    location_id INTEGER,
    external_container_id INTEGER
);
INSERT INTO location_container VALUES (1, 3, 1, 10), (2, 3, 2, 20);
"""


def _write(path: Path, script: str) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(script)
    con.commit()
    con.close()


def _library(tmp: Path) -> None:
    root = tmp / "root.sqlite"
    tidal = tmp / "tidal.sqlite"
    master = tmp / "master.sqlite"
    _write(root, _ASSET + """
        INSERT INTO asset VALUES
            (1, 'Users/dj/Music/a.mp3', 'a.mp3', 'DJ', 'Song', 'Album', 'House', '8A', 128, 200, 200000, 0.8, '', '2020', 4),
            (2, 'Users/dj/Music/b.mp3', 'b.mp3', 'DJ', 'Other', '', '', '', 0, 0, 0, NULL, '', '', 0);
        INSERT INTO space_asset VALUES (5, 1, 1), (6, 2, 1);
        INSERT INTO container VALUES (10, 0, 'wesele', 1, 1, 1);
        INSERT INTO container_asset VALUES (1, 10, 5, 1);
    """)
    _write(tidal, _ASSET + """
        INSERT INTO asset VALUES
            (7, 'streaming://tidal/99', 'streaming://tidal/99', 'Tidal Artist', 'Tide', '', '', '11A', 120, 180, 180000, NULL, '', '', 0);
        INSERT INTO space_asset VALUES (8, 7, 1);
        INSERT INTO container VALUES (20, 0, 'wesele', 1, 1, 1);
        INSERT INTO container_asset VALUES (1, 20, 8, 1);
    """)
    _write(master, _MASTER)
    con = sqlite3.connect(str(master))
    con.execute(
        "INSERT INTO connection VALUES (1, ?), (2, ?)",
        (str(root), str(tidal)),
    )
    con.commit()
    con.close()


class TestPlaylistCount(unittest.TestCase):
    def test_nested_crates_count_as_playlists(self):
        from unified_model import Playlist, count_playlist_entries, iter_playlist_entries

        tree = [
            Playlist(name="Folder", track_ids=[], is_folder=True, children=[
                Playlist(name="Folder", track_ids=["/a.mp3"]),
                Playlist(name="Crate", track_ids=["/b.mp3"]),
                Playlist(name="Deeper", track_ids=[], is_folder=True, children=[
                    Playlist(name="Inside", track_ids=["/c.mp3"]),
                ]),
            ]),
        ]
        self.assertEqual(count_playlist_entries(tree), 3)
        labels = [label for label, _pl in iter_playlist_entries(tree)]
        self.assertEqual(labels, ["Folder", "Folder / Crate", "Folder / Deeper / Inside"])


class TestSeratoSqliteRead(unittest.TestCase):
    def test_folder_with_spaces_opens(self):
        import tempfile

        from serato_sqlite_read import load_serato_sqlite_from_path

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "Application Support" / "Serato" / "Library"
            folder.mkdir(parents=True)
            _library(folder)
            db, _info = load_serato_sqlite_from_path(folder)
            self.assertTrue(any(t.path.endswith("a.mp3") for t in db.tracks))

    def test_live_folder_merges_three_databases(self):
        import tempfile

        from serato_sqlite_read import is_serato_sqlite_source, load_serato_sqlite_from_path

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _library(folder)
            self.assertTrue(is_serato_sqlite_source(folder))
            db, info = load_serato_sqlite_from_path(folder)
            paths = {t.path for t in db.tracks}
            self.assertIn("/Users/dj/Music/a.mp3", paths)
            self.assertIn("/Users/dj/Music/b.mp3", paths)
            self.assertIn("streaming://tidal/99", paths)
            self.assertEqual(info["roles"], ["master", "root", "tidal"])
            self.assertEqual(len(db.playlists), 1)
            self.assertEqual(db.playlists[0].name, "MyLists")
            self.assertTrue(db.playlists[0].is_folder)
            crate = db.playlists[0].children[0]
            self.assertEqual(crate.name, "wesele")
            self.assertIn("/Users/dj/Music/a.mp3", crate.track_ids)
            self.assertIn("streaming://tidal/99", crate.track_ids)
            self.assertNotIn("/Users/dj/Music/b.mp3", crate.track_ids)
            song = next(t for t in db.tracks if t.path.endswith("a.mp3"))
            self.assertEqual(song.title, "Song")
            self.assertEqual(song.artist, "DJ")
            self.assertEqual(song.bpm, 128)
            self.assertEqual(song.rating, 204)
            from unified_model import count_playlist_entries
            self.assertEqual(count_playlist_entries(db.playlists), 1)
            self.assertIn("1 list", info["message"])

    def test_one_backup_zip_pulls_the_other_two(self):
        import tempfile

        from rb_generator import generate_rb_xml
        from serato_sqlite_read import load_serato_sqlite_from_path

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            backups = Path(tmp) / "Backups"
            src.mkdir()
            backups.mkdir()
            _library(src)
            # Serato dopisuje kolejne ZIP-y o sekundę później.
            stamps = {
                "master": "20261016_075711+0200",
                "root": "20261016_075712+0200",
                "tidal": "20261016_075713+0200",
            }
            for role, stamp in stamps.items():
                zip_path = backups / f"{role}.sqlite-backup-{stamp}.zip"
                with zipfile.ZipFile(zip_path, "w") as zf:
                    zf.write(src / f"{role}.sqlite", arcname=f"{role}.sqlite")
            db, info = load_serato_sqlite_from_path(
                backups / f"master.sqlite-backup-{stamps['master']}.zip"
            )
            self.assertEqual(info["stamp"], stamps["master"])
            self.assertEqual(info["roles"], ["master", "root", "tidal"])
            self.assertEqual(len(db.tracks), 3)
            xml = generate_rb_xml(db).decode("utf-8")
            self.assertIn("file://localhost/Users/dj/Music/a.mp3", xml)
            self.assertIn("file://localhosttidal:tracks:99", xml)
            self.assertIn('Name="wesele"', xml)
            self.assertIn("<COLLECTION Entries=\"3\"", xml)

    def test_missing_sibling_is_reported(self):
        import tempfile

        from serato_sqlite_read import load_serato_sqlite_from_path

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _library(folder)
            stamp = "20261016_075713+0200"
            zip_path = folder / f"root.sqlite-backup-{stamp}.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(folder / "root.sqlite", arcname="root.sqlite")
            db, info = load_serato_sqlite_from_path(zip_path)
            self.assertEqual(info["roles"], ["root"])
            self.assertIn("tidal", info["missing"])
            self.assertIn("master", info["missing"])
            self.assertEqual(len(db.tracks), 2)


if __name__ == "__main__":
    unittest.main()
