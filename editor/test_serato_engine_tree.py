"""Testy drzewa Serato → Engine (płaskie %% → nested Playlist)."""
from __future__ import annotations

import unittest
from pathlib import Path

from serato_parser import prepare_serato_unified_for_engine, serato_flat_playlists_to_tree
from unified_model import Playlist


class TestSeratoEngineTree(unittest.TestCase):
    def test_flat_to_nested(self):
        flat = [
            Playlist(name="MyLists%%gatunki%%HOUSE", track_ids=["/a.mp3", "/b.mp3"]),
            Playlist(name="MyLists%%gatunki%%TECHNO", track_ids=["/c.mp3"]),
            Playlist(name="wszystkie pliki", track_ids=["/a.mp3"]),
            Playlist(name="Sideview%%automix", track_ids=["/x.mp3"]),
            Playlist(name="Folders%%filters%%Decades", track_ids=["/y.mp3"]),
        ]
        tree = serato_flat_playlists_to_tree(flat)
        names = {n.name for n in tree}
        self.assertIn("MyLists", names)
        self.assertIn("wszystkie pliki", names)
        self.assertNotIn("Sideview", names)
        self.assertNotIn("Folders", names)
        mylists = next(n for n in tree if n.name == "MyLists")
        gatunki = next(c for c in mylists.children if c.name == "gatunki")
        house = next(c for c in gatunki.children if c.name == "HOUSE")
        self.assertEqual(house.track_ids, ["/a.mp3", "/b.mp3"])

    def test_prepare_from_live_serato_if_present(self):
        serato = Path.home() / "Music" / "_Serato_"
        if not (serato / "database V2").is_file():
            self.skipTest("brak lokalnej biblioteki Serato")
        db = prepare_serato_unified_for_engine(serato, drive_root="/")
        self.assertTrue(db.tracks)
        self.assertEqual(db.playlists[0].name, "Serato")
        self.assertTrue(db.playlists[0].children)
        # lokalne pliki (w tym NJR) powinny stanowić większość
        existing = sum(1 for t in db.tracks if Path(t.path).is_file())
        self.assertGreater(existing, 100)


if __name__ == "__main__":
    unittest.main()
