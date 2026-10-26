import unittest

from tag_text import (
    is_gap, is_only_hyphen_name, is_various_artist, looks_like_joined, looks_like_split_candidate,
    looks_wrong, parse_ai_fixes, parse_gap_splits, parse_tag_bundle, rejects_name_split,
)


class TestTagText(unittest.TestCase):
    def test_caps_and_glued_words(self):
        self.assertTrue(looks_wrong("ONE WORLD ONE FUTURE"))
        self.assertTrue(looks_wrong("La GrÃ¢ce De Zorba"))
        self.assertTrue(looks_wrong("OneWorld"))
        self.assertTrue(looks_wrong("Dr.Motte"))
        self.assertFalse(looks_wrong("Dr. Motte"))
        self.assertFalse(looks_wrong("One World"))

    def test_gap_is_one_side_empty(self):
        self.assertTrue(is_gap("", "One World"))
        self.assertTrue(is_gap("Motte", ""))
        self.assertTrue(is_gap("", ""))
        self.assertTrue(is_gap("-", "One World"))
        self.assertFalse(is_gap("Motte", "One World"))

    def test_various_artist(self):
        self.assertTrue(is_various_artist("Various Artists"))
        self.assertTrue(is_various_artist("Various Artis"))
        self.assertFalse(is_various_artist("Starling"))

    def test_hyphenated_artist_is_not_a_split(self):
        self.assertTrue(is_only_hyphen_name("IN - GRID"))
        self.assertTrue(is_only_hyphen_name("Jay – Z"))
        self.assertFalse(looks_like_split_candidate("IN - GRID"))
        self.assertTrue(looks_like_split_candidate("Liroy feat. Lionel Richie – Hello (Official Music Video) [2001]"))
        self.assertTrue(rejects_name_split("IN - GRID", "", "IN", "GRID"))
        self.assertTrue(rejects_name_split("Tabata Music - Topic", "Energy", "Tabata Music", "Topic"))
        self.assertFalse(rejects_name_split(
            "",
            "Liroy feat. Lionel Richie – Hello",
            "Liroy feat. Lionel Richie",
            "Hello",
        ))

    def test_joined_title(self):
        raw = "Liroy feat. Lionel Richie – Hello (Official Music Video) [2001]"
        self.assertTrue(looks_like_joined(raw, ""))
        self.assertFalse(looks_like_joined("Hello", "Liroy"))
        self.assertTrue(looks_like_joined("Pan Savyan Feat. Julia Kaminska- Bursztynowe koraliki", ""))
        splits = parse_gap_splits('[{"idx": 3, "author": "Liroy feat. Lionel Richie", "title": "Hello", "why": "rozdzielone"}]')
        self.assertEqual(splits[0]["title"], "Hello")

    def test_parse_ai_json(self):
        raw = 'oto:\n[{"idx": 4, "field": "title", "after": "One World", "why": "brak spacji"}]'
        fixes = parse_ai_fixes(raw)
        self.assertEqual(fixes[0]["after"], "One World")
        self.assertEqual(parse_ai_fixes("nie json"), [])

    def test_parse_tag_bundle(self):
        raw = '''```json
        {"fixes": [{"idx": 4, "field": "title", "after": "One World", "why": "spacja"}],
         "splits": [{"idx": 9, "author": "Liroy", "title": "Hello", "why": "myślnik"}]}
        ```'''
        fixes, splits = parse_tag_bundle(raw)
        self.assertEqual(fixes[0]["after"], "One World")
        self.assertEqual(splits[0]["author"], "Liroy")
        self.assertEqual(parse_tag_bundle("nie json"), ([], []))


if __name__ == "__main__":
    unittest.main()
