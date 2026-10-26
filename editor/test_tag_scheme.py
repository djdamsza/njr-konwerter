"""Podgląd tagów: epoka, energia i odrzucenie śmieci."""
import unittest

from tag_scheme import (
    add_scheme_tags, builtin_field, field_owners, known_tag_map,
    needs_scheme, normalize_scheme_tag, parse_scheme_answer,
)


class TagSchemeTests(unittest.TestCase):
    def test_era_alias_and_energy(self):
        known = {"#lata00": "#Lata00", "#rock": "#Rock"}
        self.assertEqual(normalize_scheme_tag("lata2000", known), "#Lata00")
        self.assertEqual(normalize_scheme_tag("#5", known), "#5")
        self.assertEqual(normalize_scheme_tag("rock", known), "#Rock")

    def test_parse_drops_junk_and_short_lists(self):
        known = {"#rock": "#Rock", "#polskie": "#Polskie", "#ballady": "#ballady", "#lata00": "#Lata00"}
        raw = '[{"idx": 2, "tags": ["#Rock", "#X", "lata2000", "#Polskie", "#ballady", "#1"], "why": "ballada"}]'
        rows = parse_scheme_answer(raw, known)
        self.assertEqual(rows[0]["tags"], ["#Rock", "#Lata00", "#Polskie", "#ballady", "#1"])
        self.assertEqual(parse_scheme_answer('[{"idx": 1, "tags": ["#Rock"]}]', known), [])
        empty = parse_scheme_answer('[{"idx": 9, "tags": [], "why": "prywatne"}]', known)
        self.assertEqual(empty[0]["tags"], [])
        self.assertEqual(normalize_scheme_tag("christmas", {"#świąteczne": "#świąteczne"}), "#świąteczne")
        self.assertEqual(normalize_scheme_tag("hiszpańskie", {}), "#Latino")
        self.assertEqual(normalize_scheme_tag("brazylijskie", {}), "#Latino")
        self.assertEqual(normalize_scheme_tag("angielskie", {}), "#angielskie")
        self.assertEqual(normalize_scheme_tag("walc", {}), "#walczyk")
        self.assertEqual(normalize_scheme_tag("cza-cza", {}), "#cza-cza")

    def test_tags_land_in_the_bank_that_already_uses_them(self):
        library = [
            {"Tags.Genre": "#Rock", "Tags.User1": "#Lata00", "Tags.User2": "#5"},
            {"Tags.Author": "Lady Pank", "Tags.Title": "Zawsze tam gdzie ty", "Tags.Genre": "", "Tags.User1": "", "Tags.User2": ""},
        ]
        owners = field_owners(library)
        song = library[1]
        self.assertTrue(needs_scheme(song))
        self.assertTrue(add_scheme_tags(song, ["#Rock", "#Lata00", "#Polskie", "#5"], owners))
        self.assertIn("#Rock", song["Tags.Genre"])
        self.assertIn("#Polskie", song["Tags.Genre"])
        self.assertIn("#Lata00", song["Tags.User1"])
        self.assertIn("#5", song["Tags.User2"])
        self.assertFalse(add_scheme_tags(song, ["#Rock"], owners))

    def test_builtin_map_applies_without_library_examples(self):
        known = known_tag_map([])
        self.assertEqual(known["#disco-polo"], "#Disco-Polo")
        self.assertEqual(known["#lata80-te"], "#Lata80-te")
        self.assertEqual(normalize_scheme_tag("house", {}), "#House")
        self.assertEqual(builtin_field("#PARTY"), "User1")
        self.assertEqual(builtin_field("#cover"), "User2")
        song = {"Tags.Author": "Boys", "Tags.Title": "Szalona", "Tags.Genre": "", "Tags.User1": "", "Tags.User2": ""}
        self.assertTrue(add_scheme_tags(song, ["#Disco-Polo", "#Lata90-te", "#Polskie", "#4"], {}))
        self.assertIn("#Disco-Polo", song["Tags.Genre"])
        self.assertIn("#Polskie", song["Tags.Genre"])
        self.assertIn("#Lata90-te", song["Tags.User1"])
        self.assertIn("#4", song["Tags.User2"])


if __name__ == "__main__":
    unittest.main()
