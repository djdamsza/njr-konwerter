#!/usr/bin/env python3
"""Testy rozwijania filter list VDJ → snapshot."""
from __future__ import annotations

import unittest

from vdjfolder import (
    _expand_deck_relative_filter,
    _expand_filter_to_paths,
    _expand_group_by_to_playlists,
    _is_deck_relative_filter,
    _is_group_by_filter,
    _is_unexportable_filter,
    filter_vdjfolders_for_export,
    normalize_path,
    song_matches_filter,
    vdjfolders_to_playlist_tree,
)


class TestVdjFilterExpansion(unittest.TestCase):
    def test_days_since_first_seen(self):
        songs = [
            {
                "FilePath": "/a.mp3",
                "Infos.FirstSeen": str(int(__import__("time").time()) - 5 * 86400),
            },
            {
                "FilePath": "/b.mp3",
                "Infos.FirstSeen": str(int(__import__("time").time()) - 100 * 86400),
            },
        ]
        valid = {normalize_path(s["FilePath"]) for s in songs}
        path_to_norm = {normalize_path(s["FilePath"]): s["FilePath"] for s in songs}
        paths = _expand_filter_to_paths(
            "Days since First Seen <= 30", songs, valid, path_to_norm
        )
        self.assertEqual(paths, ["/a.mp3"])

    def test_user2_is_tag(self):
        songs = [{"FilePath": "/a.mp3", "Tags.User2": "#wesele"}]
        self.assertTrue(song_matches_filter("User 2 is #wesele", songs[0]))

    def test_play_count(self):
        songs = [{"FilePath": "/a.mp3", "Infos.PlayCount": "35"}]
        self.assertTrue(song_matches_filter("Play Count >= 30", songs[0]))

    def test_deck_relative_detected(self):
        self.assertTrue(_is_deck_relative_filter("bpmdiff<=4 and keydiff=0"))
        self.assertFalse(_is_unexportable_filter("bpmdiff<=4 and keydiff=0"))

    def test_group_by_detected(self):
        self.assertTrue(_is_group_by_filter("group by genre"))
        self.assertFalse(_is_unexportable_filter("group by genre"))

    def test_export_excludes_compatible_and_my_library(self):
        folders = {
            "Folders/Filters/Compatible songs.vdjfolder": "<FilterFolder filter='bpmdiff<=4'/>",
            "Sideview/automix.vdjfolder": "<VirtualFolder/>",
            "MyLists/Compatible.vdjfolder": "<FilterFolder filter='bpmdiff<=4'/>",
            "My Library/foo.vdjfolder": "<VirtualFolder/>",
            "MyLists/PARTY.vdjfolder": "<FilterFolder filter='User 1 has tag PARTY'/>",
            "MyLists/kreatywne listy.subfolders/LINKI.vdjfolder": (
                '<FilterFolder filter="Has Links = 1" scope="database" />'
            ),
        }
        out = filter_vdjfolders_for_export(folders)
        self.assertNotIn("Folders/Filters/Compatible songs.vdjfolder", out)
        self.assertNotIn("Sideview/automix.vdjfolder", out)
        self.assertNotIn("MyLists/Compatible.vdjfolder", out)
        self.assertNotIn("My Library/foo.vdjfolder", out)
        self.assertIn("MyLists/PARTY.vdjfolder", out)
        self.assertIn("MyLists/kreatywne listy.subfolders/LINKI.vdjfolder", out)

    def test_group_by_genre_creates_children(self):
        songs = [
            {"FilePath": "/a.mp3", "Tags.Genre": "#rock"},
            {"FilePath": "/b.mp3", "Tags.Genre": "#pop"},
            {"FilePath": "/c.mp3", "Tags.Genre": "#rock"},
        ]
        valid = {normalize_path(s["FilePath"]) for s in songs}
        folders = {
            "Folders/Filters/Genres.vdjfolder": (
                '<FilterFolder filter="group by genre"/>'
            ),
        }
        tree = vdjfolders_to_playlist_tree(
            folders, songs, valid, {}, keep_empty_folders=False
        )
        folders_node = next((n for n in tree if n.name == "Folders"), None)
        self.assertIsNotNone(folders_node)
        filters = next((n for n in (folders_node.children or []) if n.name == "Filters"), None)
        self.assertIsNotNone(filters)
        genres = next((n for n in (filters.children or []) if n.name == "Genres"), None)
        self.assertIsNotNone(genres)
        child_names = sorted(c.name for c in (genres.children or []))
        self.assertEqual(child_names, ["pop", "rock"])
        rock = next(c for c in genres.children if c.name == "rock")
        self.assertEqual(len(rock.track_ids), 2)

    def test_deck_relative_expansion(self):
        songs = [
            {
                "FilePath": "/ref.mp3",
                "Tags.Bpm": "120",
                "Tags.Key": "8A",
                "Infos.LastPlay": "999999",
            },
            {
                "FilePath": "/match.mp3",
                "Tags.Bpm": "122",
                "Tags.Key": "8A",
                "Infos.LastPlay": "1",
            },
            {
                "FilePath": "/far.mp3",
                "Tags.Bpm": "140",
                "Tags.Key": "8A",
                "Infos.LastPlay": "2",
            },
        ]
        valid = {normalize_path(s["FilePath"]) for s in songs}
        path_to_norm = {normalize_path(s["FilePath"]): s["FilePath"] for s in songs}
        paths = _expand_deck_relative_filter(
            "bpmdiff<=4 and keydiff=0",
            songs,
            valid,
            path_to_norm,
            deck_reference_path="/ref.mp3",
        )
        self.assertIn("/ref.mp3", paths)
        self.assertIn("/match.mp3", paths)
        self.assertNotIn("/far.mp3", paths)

    def test_compatible_list_excluded_from_tree(self):
        songs = [
            {
                "FilePath": "/ref.mp3",
                "Tags.Bpm": "120",
                "Tags.Key": "8A",
                "Infos.LastPlay": "999999",
            },
            {
                "FilePath": "/match.mp3",
                "Tags.Bpm": "122",
                "Tags.Key": "8A",
            },
            {"FilePath": "/a.mp3", "Tags.User1": "rock"},
        ]
        valid = {normalize_path(s["FilePath"]) for s in songs}
        folders = {
            "MyLists/Compatible.vdjfolder": (
                '<FilterFolder filter="bpmdiff&lt;=4 and keydiff=0"/>'
            ),
            "MyLists/OK.vdjfolder": (
                '<FilterFolder filter="User 1 has tag rock"/>'
            ),
        }
        tree = vdjfolders_to_playlist_tree(folders, songs, valid, {}, keep_empty_folders=False)
        mylists = next((n for n in tree if n.name == "MyLists"), None)
        self.assertIsNotNone(mylists)
        names = [n.name for n in (mylists.children or [])]
        self.assertIn("OK", names)
        self.assertNotIn("Compatible", names)

    def test_has_links_filter(self):
        songs = [
            {
                "FilePath": "/linked.mp3",
                "HasLinks": "1",
            },
            {"FilePath": "/plain.mp3", "HasLinks": "0"},
            {
                "FilePath": "/xml_link.mp3",
                "HasNetSearchLink": "1",
                "_children_xml": ['<Link NetSearch="td999" />'],
            },
        ]
        self.assertTrue(song_matches_filter("Has Links = 1", songs[0]))
        self.assertFalse(song_matches_filter("Has Links = 1", songs[1]))
        # NetSearch Link ≠ filtr Has Links (Linked Tracks)
        self.assertFalse(song_matches_filter("Has Links = 1", songs[2]))
        valid = {normalize_path(s["FilePath"]) for s in songs}
        path_to_norm = {normalize_path(s["FilePath"]): s["FilePath"] for s in songs}
        paths = _expand_filter_to_paths("Has Links = 1", songs, valid, path_to_norm)
        self.assertEqual(paths, ["/linked.mp3"])

        folders = {
            "MyLists/kreatywne listy.subfolders/LINKI.vdjfolder": (
                '<FilterFolder filter="Has Links = 1" scope="database" />'
            ),
        }
        tree = vdjfolders_to_playlist_tree(folders, songs, valid, {}, keep_empty_folders=False)
        leaf = tree[0].children[0].children[0]
        self.assertEqual(leaf.name, "LINKI")
        self.assertEqual(leaf.filter_text, "Has Links = 1")
        self.assertEqual(len(leaf.track_ids), 1)

    def test_top_lastplay(self):
        songs = [
            {"FilePath": "/a.mp3", "Infos.LastPlay": "100"},
            {"FilePath": "/b.mp3", "Infos.LastPlay": "200"},
            {"FilePath": "/c.mp3", "Infos.LastPlay": "50"},
        ]
        valid = {normalize_path(s["FilePath"]) for s in songs}
        path_to_norm = {normalize_path(s["FilePath"]): s["FilePath"] for s in songs}
        paths = _expand_filter_to_paths("top 2 lastplay", songs, valid, path_to_norm)
        self.assertEqual(paths, ["/b.mp3", "/a.mp3"])

    def test_virtualfolder_tidal_without_database_entry(self):
        """Playlisty VDJ z netsearch:// — eksport nawet bez rekordu w database.xml."""
        from vdjfolder import _playlist_paths_from_vdjfolder_content

        content = """<?xml version="1.0" encoding="UTF-8"?>
<VirtualFolder noDuplicates="no">
    <song path="netsearch://td348969829" artist="Haddaway" title="What Is Love" idx="0" />
    <song path="netsearch://td2938801" artist="Los Lobos" title="La Bamba" idx="1" />
    <song path="/Users/test/Library/Application Support/VirtualDJ/Cache/Rick Astley - Never Gonna Give You Up.vdjcache" netsearchId="td177186841" idx="2" />
</VirtualFolder>"""
        paths, is_filter, _ = _playlist_paths_from_vdjfolder_content(content, [], set(), {})
        self.assertFalse(is_filter)
        self.assertEqual(len(paths), 3)
        self.assertEqual(paths[0], "netsearch://td348969829")
        self.assertEqual(paths[2], "netsearch://td177186841")

        tree = vdjfolders_to_playlist_tree(
            {"MyLists/wesele bez DP.vdjfolder": content},
            [],
            set(),
            {},
            keep_empty_folders=False,
        )
        pl = next(n for n in tree if n.name == "MyLists").children[0]
        self.assertEqual(pl.name, "wesele bez DP")
        self.assertEqual(len(pl.track_ids), 3)


class TestHtmlRowMatching(unittest.TestCase):
    def test_disambiguates_same_artist_title_by_length_bpm_key(self):
        from vdj_linked_tracks import (
            _collect_row_candidates,
            _pick_best_song_for_row,
            linked_track_path_set,
        )

        rows = [
            {
                "title": "Brother Louie",
                "artist": "Modern Talking",
                "length": "03:40",
                "bpm": "108.9",
                "key": "",
                "rating": "",
            },
            {
                "title": "Brother Louie",
                "artist": "Modern Talking",
                "length": "03:43",
                "bpm": "108.9",
                "key": "02A",
                "rating": "★★★",
            },
        ]
        songs = [
            {
                "FilePath": "netsearch://td17562",
                "Tags.Author": "Modern Talking",
                "Tags.Title": "Brother Louie",
                "Infos.SongLength": "220.0",
                "Tags.Bpm": "0.550812",
            },
            {
                "FilePath": "/local/remaster.mp3",
                "Tags.Author": "Modern Talking",
                "Tags.Title": "Brother Louie",
                "Infos.SongLength": "223.007347",
                "Tags.Bpm": "0.550812",
                "Tags.Key": "Ebm",
                "Tags.Stars": "3",
            },
        ]
        lp = linked_track_path_set()
        used: set[int] = set()
        picks: list[str] = []
        for row in rows:
            cands = _collect_row_candidates(row, songs, used_ids=used)
            song, _sc, _ = _pick_best_song_for_row(row, cands, linked_paths=lp)
            self.assertIsNotNone(song)
            used.add(id(song))
            picks.append(song["FilePath"])
        self.assertEqual(len(set(picks)), 2)
        self.assertIn("netsearch://td17562", picks)
        self.assertIn("/local/remaster.mp3", picks)


if __name__ == "__main__":
    unittest.main()
