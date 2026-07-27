#!/usr/bin/env python3
"""Testy smart crates Serato + rozszerzone filtry VDJ."""
import struct
import unittest
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from serato_smart_crate import (
    vdj_filter_to_serato_rules,
    save_serato_smart_crate,
    RULE_FIELD_GENRE,
    CMP_CONTAINS,
)
from engine_smartlist import vdj_filter_to_engine_rules
from serato_parser import (
    _parse_serato_records,
    iter_serato_crate_files,
    is_serato_crate_local_path,
)
from unified_model import Playlist
from vdjfolder import vdjfolders_to_playlist_tree


class TestSeratoSmartCrate(unittest.TestCase):
    def test_tag_filter_maps(self):
        r = vdj_filter_to_serato_rules("User 1 has tag ballady")
        self.assertIsNotNone(r)
        self.assertFalse(r["match_all"])
        self.assertEqual(r["rules"][0]["field"], RULE_FIELD_GENRE)
        self.assertEqual(r["rules"][0]["comparison"], CMP_CONTAINS)
        self.assertEqual(r["rules"][0]["value"], "§ballady§")

    def test_and_or(self):
        r = vdj_filter_to_serato_rules(
            "User 1 has tag TANECZNE and User 1 has tag 2025"
        )
        self.assertTrue(r["match_all"])
        self.assertEqual(len(r["rules"]), 2)

        r2 = vdj_filter_to_serato_rules(
            "User 1 has tag PARTY or User 1 has tag TANECZNE"
        )
        self.assertFalse(r2["match_all"])
        self.assertEqual(len(r2["rules"]), 2)

    def test_rating_unmapped_serato_but_engine(self):
        self.assertIsNone(vdj_filter_to_serato_rules("rating >= 4"))
        self.assertIsNotNone(vdj_filter_to_engine_rules("rating >= 4"))

    def test_non_tag_filters_not_smart(self):
        self.assertIsNone(vdj_filter_to_serato_rules("bpm >= 120"))
        self.assertIsNone(vdj_filter_to_serato_rules("year is 2024"))
        self.assertIsNone(vdj_filter_to_serato_rules("play count >= 3"))
        self.assertIsNone(vdj_filter_to_serato_rules("artist contains Foo"))
        self.assertIsNotNone(vdj_filter_to_engine_rules("bpm >= 120"))

    def test_energy_user2_uses_anchor(self):
        r = vdj_filter_to_serato_rules("User 2 has tag 1")
        self.assertIsNotNone(r)
        self.assertEqual(r["rules"][0]["value"], "§1§")
        r2 = vdj_filter_to_serato_rules('User 2 has tag "normal club"')
        self.assertEqual(r2["rules"][0]["value"], "§normalclub§")
        r3 = vdj_filter_to_serato_rules("Genre is #AI")
        self.assertEqual(r3["rules"][0]["value"], "§ai§")
        r4 = vdj_filter_to_serato_rules("Genre contains dp-best")
        self.assertEqual(r4["rules"][0]["value"], "dp-best")
        r5 = vdj_filter_to_serato_rules("User 1 has tag EXTRAROCK'N'ROLL")
        self.assertEqual(r5["rules"][0]["value"], "§extrarock'n'roll§")

    def test_normalize_tag_key(self):
        from serato_smart_crate import normalize_tag_key
        self.assertEqual(normalize_tag_key("NORMAL_CLUB"), "normalclub")
        self.assertEqual(normalize_tag_key("normal club"), "normalclub")
        self.assertEqual(normalize_tag_key("#LATA90-TE"), "lata90te")

    def test_build_genre_anchors(self):
        from serato_smart_crate import build_serato_genre_field
        g = build_serato_genre_field("#Polskie", "", "#1 #X")
        self.assertIn("#Polskie", g)
        self.assertIn("#1", g)
        self.assertIn("#X", g)
        self.assertNotIn("§", g)

    def test_write_and_parse_scrate(self):
        rules = vdj_filter_to_serato_rules("User 1 has tag rock")
        data = save_serato_smart_crate(rules)
        recs = _parse_serato_records(BytesIO(data))
        tags = [t for t, _ in recs]
        self.assertIn("vrsn", tags)
        self.assertIn("rurt", tags)
        self.assertTrue(data.startswith(b"vrsn"))


class TestPlaylistTreeSnapshots(unittest.TestCase):
    def test_filter_list_expanded_to_tracks(self):
        folders = {
            "MyLists/BALLADY.vdjfolder": (
                '<?xml version="1.0"?>'
                '<FilterFolder filter="User 1 has tag ballady">'
                "<VirtualFolder/></FilterFolder>"
            ),
        }
        songs = [
            {
                "FilePath": "/Users/test/Music/a.mp3",
                "Tags.Title": "A",
                "Tags.User1": "ballady",
            }
        ]
        valid = {"/Users/test/Music/a.mp3"}
        tree = vdjfolders_to_playlist_tree(folders, songs, valid)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0].name, "MyLists")
        leaf = tree[0].children[0]
        self.assertEqual(leaf.name, "BALLADY")
        self.assertFalse(getattr(leaf, "filter_text", ""))
        self.assertIn("/Users/test/Music/a.mp3", leaf.track_ids)

    def test_tidal_on_static_list(self):
        folders = {
            "MyLists/mix.vdjfolder": (
                '<?xml version="1.0"?>'
                "<VirtualFolder>"
                '<song path="netsearch://td999"/>'
                '<song path="/Users/test/Music/b.mp3"/>'
                "</VirtualFolder>"
            ),
        }
        songs = [
            {"FilePath": "netsearch://td999", "Tags.Title": "Tide"},
            {"FilePath": "/Users/test/Music/b.mp3", "Tags.Title": "Local"},
        ]
        valid = {"netsearch://td999", "/Users/test/Music/b.mp3"}
        tree = vdjfolders_to_playlist_tree(folders, songs, valid)
        paths = tree[0].children[0].track_ids
        self.assertIn("netsearch://td999", paths)
        self.assertIn("/Users/test/Music/b.mp3", paths)

    def test_iter_crate_with_filter_snapshot(self):
        root = Playlist(
            name="VDJ",
            track_ids=[],
            is_folder=True,
            children=[
                Playlist(name="A", track_ids=["/x/a.mp3"]),
                Playlist(name="SMART", track_ids=["/x/b.mp3"]),
            ],
        )
        crates = iter_serato_crate_files([root])
        stems = {s for s, _ in crates}
        self.assertIn("VDJ%%SMART", stems)
        self.assertEqual(dict(crates)["VDJ%%SMART"], ["/x/b.mp3"])
        self.assertTrue(is_serato_crate_local_path("/Users/x/a.mp3"))
        self.assertFalse(is_serato_crate_local_path("netsearch://td1"))
        self.assertFalse(is_serato_crate_local_path("td12345"))


if __name__ == "__main__":
    unittest.main()
