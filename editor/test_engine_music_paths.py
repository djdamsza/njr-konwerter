#!/usr/bin/env python3
"""Testy ścieżek Music/ dla Engine DJ."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine_music_paths import (
    ensure_music_symlink,
    file_identity,
    index_engine_music_by_source,
    is_junk_engine_path,
    music_rel_for_export,
    prefer_patriot_music_path,
    resolve_local_file,
    _unique_music_rel,
)
from engine_generator import track_to_engine_json
from unified_model import Track


class TestEngineMusicPaths(unittest.TestCase):
    def test_junk_paths(self):
        self.assertTrue(is_junk_engine_path("../../../../clouddrive:/googledrive/x.mp3"))
        self.assertTrue(is_junk_engine_path("../../../../Mój dysk/foo.mp3"))
        self.assertFalse(is_junk_engine_path("/Users/x/Music/a.mp3"))

    def test_music_symlink_and_export(self):
        with tempfile.TemporaryDirectory() as td:
            engine = Path(td) / "Engine Library"
            engine.mkdir()
            src_dir = Path(td) / "Desktop"
            src_dir.mkdir()
            src = src_dir / "song.mp3"
            src.write_bytes(b"ID3")

            rel = _unique_music_rel(engine, "Artist", "Album", "song.mp3", set())
            self.assertTrue(rel.startswith("Music/"))
            self.assertTrue(ensure_music_symlink(engine, rel, src))

            row = track_to_engine_json(
                Track(path=str(src), title="Song", artist="Artist", album="Album"),
                engine_dir=engine,
                engine_music_layout=True,
            )
            self.assertIsNotNone(row)
            self.assertEqual(row["relative_path"], rel)
            self.assertTrue((engine / rel).is_file())

    def test_reuses_existing_symlink_when_artist_changes(self):
        with tempfile.TemporaryDirectory() as td:
            engine = Path(td) / "Engine Library"
            engine.mkdir()
            src = Path(td) / "song.mp3"
            src.write_bytes(b"ID3")
            rel = "Music/Old Artist/Album/song.mp3"
            self.assertTrue(ensure_music_symlink(engine, rel, src))
            found = index_engine_music_by_source(engine)
            self.assertEqual(found[str(src.resolve())], rel)
            row = track_to_engine_json(
                Track(path=str(src), title="Song", artist="New Artist", album="Album"),
                engine_dir=engine,
                engine_music_layout=True,
            )
            self.assertEqual(row["relative_path"], rel)

    def test_same_file_is_reused_when_path_text_differs(self):
        with tempfile.TemporaryDirectory() as td:
            engine = Path(td) / "Engine Library"
            engine.mkdir()
            src = Path(td) / "song.mp3"
            src.write_bytes(b"ID3")
            rel = "Music/Old Artist/Album/song.mp3"
            self.assertTrue(ensure_music_symlink(engine, rel, src))
            ident = file_identity(src)
            self.assertIsNotNone(ident)
            self.assertEqual(index_engine_music_by_source(engine)[ident], rel)
            got = music_rel_for_export(
                engine,
                artist="Inny",
                album="Album",
                abs_file=src.resolve(),
                occupied=set(),
                existing_by_source={ident: rel},
            )
            self.assertEqual(got, rel)

    def test_patriot_path_must_stay_under_music(self):
        occupied: set[str] = set()
        rel = prefer_patriot_music_path(
            "song.mp3",
            pat_index={"song.mp3": [{"path": "../../Desktop/song.mp3", "title": "Song"}]},
            occupied=occupied,
        )
        self.assertIsNone(rel)
        self.assertEqual(occupied, set())

    def test_playlist_does_not_reread_the_file(self):
        from engine_generator import unified_to_engine_export_doc
        from unified_model import Playlist, UnifiedDatabase
        import engine_music_paths

        with tempfile.TemporaryDirectory() as td:
            engine = Path(td) / "Engine Library"
            engine.mkdir()
            src = Path(td) / "song.mp3"
            src.write_bytes(b"ID3")
            calls = {"n": 0}
            real = engine_music_paths.resolve_local_file

            def wrapped(path: str):
                calls["n"] += 1
                return real(path)

            engine_music_paths.resolve_local_file = wrapped
            try:
                db = UnifiedDatabase(
                    tracks=[Track(path=str(src), title="Song", artist="A", album="B")],
                    playlists=[
                        Playlist(name="One", track_ids=[str(src)]),
                        Playlist(name="Two", track_ids=[str(src), str(src)]),
                    ],
                )
                doc = unified_to_engine_export_doc(
                    db, engine_dir=engine, engine_music_layout=True, merge_mode=True,
                )
            finally:
                engine_music_paths.resolve_local_file = real
            self.assertEqual(calls["n"], 1)
            self.assertEqual(len(doc["playlists"]), 2)
            self.assertEqual(
                doc["playlists"][0]["track_paths"],
                [doc["tracks"][0]["relative_path"]],
            )

    def test_resolve_local_file(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"x")
            path = f.name
        try:
            self.assertEqual(resolve_local_file(path), Path(path).resolve())
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
