#!/usr/bin/env python3
"""Testy ścieżek Music/ dla Engine DJ."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine_music_paths import (
    ensure_music_symlink,
    is_junk_engine_path,
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
