"""Scalanie tagów: literówka, dwa banki, śmieć z jednego utworu."""
import unittest

from tag_merge_ai import annotate_small, inventory, merge_prompt, parse_merge_answer, review_rows, tag_key, validate_proposal


def _song(genre="", user1="", user2=""):
    return {"Tags.Genre": genre, "Tags.User1": user1, "Tags.User2": user2}


class TagMergeAiTests(unittest.TestCase):
    def test_key_ignores_hash_and_case(self):
        self.assertEqual(tag_key("#DownTempo"), tag_key("down-tempo"))

    def test_review_includes_typo_and_cross_bank(self):
        songs = [_song("Dance", "#DownTempo") for _ in range(20)]
        songs.append(_song("dence", "#DownTempo"))
        songs.append(_song(user2="#DownTempo"))
        rows = inventory(songs)
        review = {(row["field"], row["tag"]) for row in review_rows(rows)}
        self.assertIn(("Genre", "dence"), review)
        self.assertIn(("Genre", "Dance"), review)
        self.assertIn(("User1", "#DownTempo"), review)
        self.assertIn(("User2", "#DownTempo"), review)

    def test_parse_keeps_typo_and_drop_and_rejects_energy(self):
        rows = inventory(
            [_song("Dance #Lata20", "#4") for _ in range(20)]
            + [_song("dence ze")]
        )
        raw = """[
            {"sources":[{"field":"Genre","tag":"dence"}],"newTag":"Dance","targetField":"Genre","why":"literówka nazwy Dance"},
            {"sources":[{"field":"Genre","tag":"ze"}],"newTag":"","why":"jeden utwór, to nie gatunek"},
            {"sources":[{"field":"User1","tag":"#4"}],"newTag":"#5","targetField":"User1","why":"energia obok energii"},
            {"sources":[{"field":"Genre","tag":"Dance"}],"newTag":"House","targetField":"Genre","why":"to nie jest ten sam tag"}
        ]"""
        parsed = parse_merge_answer(raw, rows)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["newTag"], "Dance")
        self.assertEqual(parsed[1]["newTag"], "")

    def test_cross_bank_same_tag_uses_larger_bank(self):
        rows = [
            {"field": "User1", "tag": "#DownTempo", "count": 10, "key": tag_key("#DownTempo")},
            {"field": "User2", "tag": "#DownTempo", "count": 40, "key": tag_key("#DownTempo")},
        ]
        item = validate_proposal(
            {
                "sources": [{"field": "User1", "tag": "#DownTempo"}, {"field": "User2", "tag": "#DownTempo"}],
                "newTag": "#DownTempo",
                "targetField": "User2",
                "why": "ten sam tag w dwóch bankach",
            },
            rows,
        )
        self.assertEqual(item["targetField"], "User2")
        self.assertEqual(item["targetCount"], 40)
        self.assertEqual(item["sources"], [{"field": "User1", "tag": "#DownTempo", "count": 10}])

    def test_drop_rejected_when_big_sibling_exists(self):
        rows = inventory([_song("#DownTempo") for _ in range(20)] + [_song("DownTempo")])
        item = validate_proposal(
            {"sources": [{"field": "Genre", "tag": "DownTempo"}], "newTag": "", "why": "mało utworów, usunąć"},
            rows,
        )
        self.assertIsNone(item)

    def test_small_tag_carries_its_tracks(self):
        songs = [_song("Italodance")]
        songs[0]["Tags.Author"] = "Gigi D'Agostino"
        songs[0]["Tags.Title"] = "L'Amour Toujours"
        rows = annotate_small(songs, inventory(songs))
        prompt = merge_prompt(rows, review_rows(rows))
        self.assertIn("Gigi D'Agostino — L'Amour Toujours", prompt)
        self.assertIn("Euro-Disco to nie #Disco-Polo", prompt)
        self.assertIn("I'll Be There for You", prompt)
        self.assertIn("nie #dziecianimacja", prompt)
        item = validate_proposal(
            {
                "sources": [{"field": "Genre", "tag": "Italodance"}],
                "newTag": "Dance",
                "targetField": "Genre",
                "why": "to nagranie jest taneczne",
            },
            rows + [{"field": "Genre", "tag": "Dance", "count": 20, "key": tag_key("Dance"), "tracks": []}],
        )
        self.assertEqual(item["sources"][0]["tracks"], ["Gigi D'Agostino — L'Amour Toujours"])


if __name__ == "__main__":
    unittest.main()
