"""Synchronizacja ścieżek .vdjfolder po podmianie utworów (Tidal ↔ lokalne)."""
import unittest

from vdjfolder import (
    build_path_replacement_lookup,
    normalize_path,
    path_match_keys,
    repair_vdjfolder_paths_from_database,
    replace_paths_in_vdjfolder_content,
)


class TestPathMatchKeys(unittest.TestCase):
    def test_tidal_aliases(self):
        keys = path_match_keys("netsearch://td503099")
        self.assertIn(normalize_path("netsearch://td503099"), keys)
        self.assertIn(normalize_path("td503099"), keys)

    def test_link_netsearch_on_song(self):
        song = {"FilePath": "td50332071", "Link.NetSearch": "td503099"}
        keys = path_match_keys("td50332071", song)
        self.assertIn(normalize_path("netsearch://td503099"), keys)


class TestReplacePathsInVdjfolder(unittest.TestCase):
    def test_netsearch_to_local(self):
        content = '''<?xml version="1.0" encoding="UTF-8"?>
<VirtualFolder Name="Test">
\t<song path="netsearch://td503099" artist="Alcazar" title="Crying" idx="0" />
</VirtualFolder>'''
        local = "/Users/test/Alcazar - Crying.mp3"
        lookup = build_path_replacement_lookup("netsearch://td503099", local)
        out, n = replace_paths_in_vdjfolder_content(content, lookup)
        self.assertEqual(n, 1)
        self.assertIn(local, out)
        self.assertNotIn("netsearch://td503099", out)

    def test_td_alias_to_new_tidal(self):
        content = '''<?xml version="1.0" encoding="UTF-8"?>
<VirtualFolder Name="Test">
\t<song path="netsearch://td292509" artist="Madonna" title="Hung Up" idx="0" />
</VirtualFolder>'''
        lookup = build_path_replacement_lookup("netsearch://td292509", "td1669834")
        out, n = replace_paths_in_vdjfolder_content(content, lookup)
        self.assertEqual(n, 1)
        self.assertIn('path="td1669834"', out)
        self.assertIn('netsearchId="td1669834"', out)


class TestRepairFromDatabase(unittest.TestCase):
    def test_repairs_stale_netsearch_via_link_id(self):
        songs = [
            {
                "FilePath": "/Users/test/Alcazar - Crying.mp3",
                "Link.NetSearch": "td503099",
                "Tags.Author": "Alcazar",
                "Tags.Title": "Crying at the Discoteque (Radio Edit)",
            },
            {
                "FilePath": "td50332071",
                "Link.NetSearch": "td503099",
                "Tags.Author": "Alcazar",
                "Tags.Title": "Crying at the Discoteque",
            },
        ]
        vdjfolders = {
            "MyLists/test.vdjfolder": '''<?xml version="1.0" encoding="UTF-8"?>
<VirtualFolder Name="test">
\t<song path="netsearch://td503099" artist="Alcazar" title="Crying" idx="0" />
</VirtualFolder>''',
        }
        updated, folders_changed, refs = repair_vdjfolder_paths_from_database(songs, vdjfolders)
        self.assertEqual(refs, 1)
        self.assertIn("/Users/test/Alcazar - Crying.mp3", updated["MyLists/test.vdjfolder"])


if __name__ == "__main__":
    unittest.main()
