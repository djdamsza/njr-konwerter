#!/usr/bin/env python3
"""Testy drzewa playlist VDJ → Engine."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine_generator import unified_to_engine_export_doc
from unified_model import Playlist, Track, UnifiedDatabase
from vdjfolder import normalize_path, vdjfolders_to_playlist_tree


class TestVdjPlaylistTree(unittest.TestCase):
    def test_builds_nested_structure(self):
        vdjfolders = {
            "MyLists/gatunki.vdjfolder": '<?xml version="1.0"?><VirtualFolder/>',
            "MyLists/gatunki/disco.vdjfolder": (
                '<?xml version="1.0"?>'
                '<VirtualFolder><song path="/music/a.mp3"/></VirtualFolder>'
            ),
            "MyLists/wesela.vdjfolder": (
                '<?xml version="1.0"?>'
                '<VirtualFolder><song path="/music/b.mp3"/></VirtualFolder>'
            ),
        }
        order = {
            "MyLists.subfolders/order": b"gatunki\nwesela\n",
            "MyLists/gatunki.subfolders/order": b"disco\n",
        }
        songs = [
            {"FilePath": "/music/a.mp3"},
            {"FilePath": "/music/b.mp3"},
        ]
        valid = {normalize_path(s["FilePath"]) for s in songs}
        tree = vdjfolders_to_playlist_tree(vdjfolders, songs, valid, order)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0].name, "MyLists")
        self.assertTrue(tree[0].is_folder)
        child_names = [c.name for c in tree[0].children]
        self.assertEqual(child_names, ["gatunki", "wesela"])
        gatunki = tree[0].children[0]
        self.assertEqual(gatunki.name, "gatunki")
        self.assertEqual(len(gatunki.children), 1)
        self.assertEqual(gatunki.children[0].name, "disco")
        self.assertEqual(gatunki.children[0].track_ids, ["/music/a.mp3"])

    def test_subfolders_path_segment(self):
        vdjfolders = {
            "MyLists/270626.subfolders/wejscie.vdjfolder": (
                '<?xml version="1.0"?>'
                '<VirtualFolder><song path="/music/a.mp3"/></VirtualFolder>'
            ),
        }
        songs = [{"FilePath": "/music/a.mp3"}]
        valid = {normalize_path(s["FilePath"]) for s in songs}
        tree = vdjfolders_to_playlist_tree(vdjfolders, songs, valid, {})
        self.assertEqual(tree[0].name, "MyLists")
        self.assertEqual(tree[0].children[0].name, "270626")
        self.assertEqual(tree[0].children[0].children[0].name, "wejscie")

    def test_engine_export_nested_json(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
            tf.write(b"\x00")
            track_path = tf.name
        self.addCleanup(lambda: Path(track_path).unlink(missing_ok=True))
        db = UnifiedDatabase(
            tracks=[
                Track(path=track_path, title="A"),
            ],
            playlists=[
                Playlist(
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
                                    name="Set",
                                    track_ids=[track_path],
                                )
                            ],
                        )
                    ],
                )
            ],
        )
        engine = Path("/Users/test/Music/Engine Library")
        doc = unified_to_engine_export_doc(
            db, engine_dir=engine, merge_mode=True, engine_music_layout=True
        )
        self.assertEqual(len(doc["playlists"]), 1)
        root = doc["playlists"][0]
        self.assertEqual(root["name"], "VDJ")
        self.assertTrue(root.get("is_folder"))
        self.assertEqual(root["children"][0]["name"], "MyLists")
        leaf = root["children"][0]["children"][0]
        self.assertTrue(
            leaf["track_paths"][0].startswith("Music/"),
            leaf["track_paths"],
        )


if __name__ == "__main__":
    unittest.main()
