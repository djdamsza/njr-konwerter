import unittest

from normalize_advice import advice_prompt, parse_normalize_advice


class TestNormalizeAdvice(unittest.TestCase):
    def test_prompt_lists_spellings(self):
        text = advice_prompt([{"gi": 2, "field": "author", "variants": ["THE BUGGLES", "The Buggles"]}])
        self.assertIn("2\tauthor\tTHE BUGGLES | The Buggles", text)

    def test_parse_keeps_only_known_spellings(self):
        raw = '[{"gi": 2, "keep": "The Buggles", "change": ["THE BUGGLES", "Obcy"], "why": "wielkość liter"}]'
        tips = parse_normalize_advice(raw, {2: {"THE BUGGLES", "The Buggles"}})
        self.assertEqual(tips[0]["keep"], "The Buggles")
        self.assertEqual(tips[0]["change"], ["THE BUGGLES"])

    def test_unknown_keep_is_dropped(self):
        raw = '[{"gi": 1, "keep": "Avicii", "change": ["AVICII"], "why": "spoza listy"}]'
        self.assertEqual(parse_normalize_advice(raw, {1: {"AVICII", "Avicii "}}), [])


if __name__ == "__main__":
    unittest.main()
