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
            self.assertIn('KeyType="0"', xml)
            flat = xml.replace("\n", "")
            self.assertIn('Entries="2"', flat)
            self.assertRegex(flat, r'<TRACK Key="\d+"')
            self.assertIn("<COLLECTION Entries=\"3\"", xml)

    def test_artist_taken_from_filename_when_missing(self):
        from rb_generator import _artist_for_rb
        from unified_model import Track

        filled = Track(
            path="/Users/dj/Music/RICHARD GREY - Welcome To My House.mp3",
            title="Welcome To My House",
            artist="",
        )
        self.assertEqual(_artist_for_rb(filled), "RICHARD GREY")
        junk = Track(
            path="/Users/dj/Music/tomp3.cc - IN GRID Tu Es Foutu.mp3",
            title="IN GRID Tu Es Foutu",
            artist="",
        )
        self.assertEqual(_artist_for_rb(junk), "")
        kept = Track(path="/x/a.mp3", title="Song", artist="DJ")
        self.assertEqual(_artist_for_rb(kept), "DJ")
        polish = Track(
            path="/Users/dj/Music/SLAWEK UNIATOWSKI - Kazdemu wolno kochac (Album Version).mp3",
            title="Każdemu wolno kochać (Album Version)",
            artist="",
        )
        self.assertEqual(_artist_for_rb(polish), "SLAWEK UNIATOWSKI")
        emdash = Track(
            path="/Users/dj/Music/Adele — Rolling in the deep (Ayur Tsyrenov DFM extended remix).mp3",
            title="Rolling in the deep (Ayur Tsyrenov DFM extended remix)",
            artist="",
        )
        self.assertEqual(_artist_for_rb(emdash), "Adele")
        underscored = Track(
            path="/Users/dj/Music/Sean_Paul_ft_Alexis_Jordan-Got_2_Luv_U_(Radio_mix).mp3",
            title="Got 2 Luv U (Radio mix)",
            artist="",
        )
        self.assertEqual(_artist_for_rb(underscored), "Sean Paul ft Alexis Jordan")
        from_tag = Track(path="/x/song.mp3", title="Song", artist="")
        self.assertEqual(_artist_for_rb(from_tag, file_artist="Tag Artist"), "Tag Artist")

    def test_nested_sqlite_crates_keep_tracks_in_rekordbox_xml(self):
        from rb_generator import generate_rb_xml
        from serato_parser import serato_playlists_for_export
        from unified_model import Playlist, Track, UnifiedDatabase

        leaf = Playlist(name="wesele", track_ids=["/Users/dj/Music/a.mp3"], is_folder=False)
        folder = Playlist(name="imprezy", track_ids=[], is_folder=True, children=[leaf])
        tree = serato_playlists_for_export([folder])
        self.assertEqual(tree[0].children[0].track_ids, ["/Users/dj/Music/a.mp3"])
        flat = serato_playlists_for_export(
            [Playlist(name="imprezy%%wesele", track_ids=["/Users/dj/Music/a.mp3"])]
        )
        self.assertEqual(flat[0].name, "imprezy")
        db = UnifiedDatabase(
            tracks=[Track(path="/Users/dj/Music/a.mp3", title="Song", artist="")],
            playlists=tree,
        )
        xml = generate_rb_xml(db).decode("utf-8").replace("\n", "")
        self.assertIn('Name="wesele"', xml)
        self.assertIn('Entries="1"', xml)
        self.assertIn('KeyType="0"', xml)
        self.assertRegex(xml, r'<TRACK Key="\d+"')

    def test_location_matches_rekordbox_export(self):
        from rb_generator import _path_to_location

        loc = _path_to_location(
            "/Users/test/Downloads/DAWID KWIATKOWSKI, MARGARET - Pozniej (Radio Edit).mp3"
        )
        self.assertEqual(
            loc,
            "file://localhost/Users/test/Downloads/DAWID%20KWIATKOWSKI%2C%20MARGARET%20-%20Pozniej%20%28Radio%20Edit%29.mp3",
        )
        self.assertIn("%26", _path_to_location("/Users/test/Music/A & B.mp3"))

    def test_root_sqlite_tree_beats_empty_master_crates(self):
        import tempfile

        from serato_sqlite_read import load_serato_sqlite_from_path

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            root = folder / "root.sqlite"
            master = folder / "master.sqlite"
            _write(root, _ASSET + """
                INSERT INTO asset VALUES
                    (1, 'Users/dj/Music/a.mp3', 'a.mp3', 'DJ', 'Song', '', '', '8A', 128, 200, 200000, 0.8, '', '2020', 1);
                INSERT INTO space_asset VALUES (5, 1, 1);
                INSERT INTO container VALUES
                    (1, 0, 'automix', 0, 1, 1),
                    (2, 1, 'sylwester', 1, 1, 1);
                INSERT INTO container_asset VALUES (1, 2, 5, 1);
            """)
            _write(master, """
                CREATE TABLE space (id INTEGER PRIMARY KEY, name TEXT);
                INSERT INTO space VALUES (5, 'Serato Library');
                CREATE TABLE container (
                    id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT,
                    type INTEGER, list_order INTEGER, space_id INTEGER
                );
                INSERT INTO container VALUES
                    (1, 0, 'Serato Library root', 0, 0, 5),
                    (2, 1, 'automix', 1, 1, 5);
                CREATE TABLE location (id INTEGER PRIMARY KEY, path TEXT);
                CREATE TABLE connection (location_id INTEGER PRIMARY KEY, database_uri TEXT);
                CREATE TABLE location_container (
                    id INTEGER PRIMARY KEY, container_id INTEGER,
                    location_id INTEGER, external_container_id INTEGER
                );
            """)
            con = sqlite3.connect(str(master))
            con.execute("INSERT INTO connection VALUES (1, ?)", (str(root),))
            con.commit()
            con.close()
            db, _info = load_serato_sqlite_from_path(folder)
            self.assertEqual(db.playlists[0].name, "automix")
            self.assertTrue(db.playlists[0].is_folder)
            child = db.playlists[0].children[0]
            self.assertEqual(child.name, "sylwester")
            self.assertIn("/Users/dj/Music/a.mp3", child.track_ids)

    def test_subcrates_replace_empty_sqlite_playlists(self):
        import tempfile
        from io import BytesIO

        from rb_generator import generate_rb_xml
        from serato_parser import _encode_utf16be, _write_serato_record, overlay_disk_subcrates
        from unified_model import Playlist, Track, UnifiedDatabase

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "_Serato_"
            (base / "Subcrates").mkdir(parents=True)
            buf = BytesIO()
            _write_serato_record(buf, "vrsn", _encode_utf16be("1.0/Serato ScratchLive Crate"))
            inner = BytesIO()
            _write_serato_record(inner, "ptrk", _encode_utf16be("Users/dj/Music/a.mp3"))
            _write_serato_record(buf, "otrk", inner.getvalue())
            (base / "Subcrates" / "automix%%sylwester.crate").write_bytes(buf.getvalue())
            db = UnifiedDatabase(
                tracks=[Track(path="/Users/dj/Music/a.mp3", title="Song", artist="DJ")],
                playlists=[Playlist(name="automix", track_ids=[], is_folder=False)],
                source="serato",
            )
            db, note = overlay_disk_subcrates(db, roots=[(base, "/")])
            self.assertIn("Subcrates", note)
            folder = next(pl for pl in db.playlists if pl.name == "automix")
            self.assertTrue(folder.is_folder)
            leaf = next(pl for pl in folder.children if pl.name == "sylwester")
            self.assertEqual(leaf.track_ids, ["/Users/dj/Music/a.mp3"])
            xml = generate_rb_xml(db).decode("utf-8").replace("\n", "")
            self.assertIn('Type="0"', xml)
            self.assertIn('Name="sylwester"', xml)
            self.assertIn('KeyType="0"', xml)
            self.assertIn('Entries="1"', xml)
            self.assertRegex(xml, r'<TRACK Key="\d+"')

    def test_cyclic_containers_do_not_recurse(self):
        import sqlite3
        import tempfile

        from serato_sqlite_read import _playlist_tree

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "root.sqlite"
            con = sqlite3.connect(str(path))
            con.row_factory = sqlite3.Row
            con.executescript(
                """
                CREATE TABLE container (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER,
                    name TEXT,
                    type INTEGER,
                    list_order INTEGER
                );
                INSERT INTO container VALUES
                    (1, 2, 'automix', 1, 1),
                    (2, 1, 'sylwester', 1, 2);
                """
            )
            con.commit()
            tree = _playlist_tree(con, lambda _cid: [])
            con.close()
            self.assertEqual(len(tree), 1)
            self.assertEqual({tree[0].name, tree[0].children[0].name}, {"automix", "sylwester"})

    def test_long_parent_chain_does_not_recurse(self):
        import sqlite3
        import tempfile

        from serato_sqlite_read import _playlist_tree

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "root.sqlite"
            con = sqlite3.connect(str(path))
            con.row_factory = sqlite3.Row
            con.execute(
                "CREATE TABLE container (id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT)"
            )
            con.executemany(
                "INSERT INTO container VALUES (?, ?, ?)",
                [(i, i - 1, f"c{i}") for i in range(1, 1201)],
            )
            con.commit()
            tree = _playlist_tree(con, lambda _cid: [])
            con.close()
            self.assertTrue(tree)
            self.assertEqual(tree[0].name, "c1")

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
