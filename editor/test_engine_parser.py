"""Odczyt m.db: stary Engine Prime (MetaData) i aktualny Database2 (kolumny w Track)."""
import sqlite3
import unittest
from pathlib import Path


class TestEngineParser(unittest.TestCase):
    def test_database2_reads_title_from_track_and_playlist(self):
        import os
        import tempfile

        from engine_parser import load_engine_db

        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "Engine Library"
            dbdir = lib / "Database2"
            dbdir.mkdir(parents=True)
            music = lib / "Music"
            music.mkdir()
            song = music / "a.mp3"
            song.write_bytes(b"mp3")
            conn = sqlite3.connect(str(dbdir / "m.db"))
            conn.executescript(
                """
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY,
                    path TEXT,
                    filename TEXT,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    genre TEXT,
                    comment TEXT,
                    year INTEGER,
                    length INTEGER,
                    bpm INTEGER,
                    bpmAnalyzed REAL,
                    key INTEGER,
                    rating INTEGER
                );
                CREATE TABLE Playlist (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    parentListId INTEGER
                );
                CREATE TABLE PlaylistEntity (
                    id INTEGER PRIMARY KEY,
                    listId INTEGER,
                    trackId INTEGER,
                    nextEntityId INTEGER
                );
                INSERT INTO Track VALUES
                    (1, 'Music/a.mp3', 'a.mp3', 'Song', 'DJ', 'Album', 'House', '', 2020, 200, 0, 128.0, 0, 80);
                INSERT INTO Playlist VALUES (1, 'wesele', 0);
                INSERT INTO PlaylistEntity VALUES (1, 1, 1, 0);
                """
            )
            conn.commit()
            conn.close()
            os.environ["NJR_NO_PRIVACY_PROMPT"] = "1"
            db = load_engine_db(dbdir / "m.db")
            self.assertEqual(len(db.tracks), 1)
            self.assertEqual(db.tracks[0].title, "Song")
            self.assertEqual(db.tracks[0].artist, "DJ")
            self.assertEqual(db.tracks[0].bpm, 128)
            self.assertEqual(db.tracks[0].key, "8B")
            self.assertEqual(db.tracks[0].path, str(song.resolve()))
            self.assertEqual(db.playlists[0].name, "wesele")
            self.assertEqual(db.playlists[0].track_ids, [str(song.resolve())])

    def test_old_metadata_table_still_loads(self):
        import tempfile

        from engine_parser import load_engine_db

        with tempfile.TemporaryDirectory() as tmp:
            mdb = Path(tmp) / "m.db"
            conn = sqlite3.connect(str(mdb))
            conn.executescript(
                """
                CREATE TABLE Track (
                    id INTEGER PRIMARY KEY,
                    path TEXT,
                    filename TEXT,
                    length INTEGER,
                    bpm INTEGER,
                    year INTEGER,
                    bpmAnalyzed REAL
                );
                CREATE TABLE MetaData (id INTEGER, type INTEGER, text TEXT);
                CREATE TABLE MetaDataInteger (id INTEGER, type INTEGER, value INTEGER);
                CREATE TABLE Playlist (id INTEGER PRIMARY KEY, title TEXT);
                CREATE TABLE PlaylistTrackList (
                    playlistId INTEGER, trackId INTEGER, trackNumber INTEGER
                );
                INSERT INTO Track VALUES (1, '/Users/dj/Music/a.mp3', 'a.mp3', 180, 120, 2019, 0);
                INSERT INTO MetaData VALUES (1, 13, 'Old Song'), (1, 12, 'Old DJ');
                INSERT INTO Playlist VALUES (1, 'set');
                INSERT INTO PlaylistTrackList VALUES (1, 1, 1);
                """
            )
            conn.commit()
            conn.close()
            db = load_engine_db(mdb)
            self.assertEqual(db.tracks[0].title, "Old Song")
            self.assertEqual(db.tracks[0].artist, "Old DJ")
            self.assertEqual(db.tracks[0].path, "/Users/dj/Music/a.mp3")
            self.assertEqual(db.playlists[0].name, "set")


if __name__ == "__main__":
    unittest.main()
