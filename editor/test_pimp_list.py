"""Pimp my list: dysk, Tidal, remixy, token tylko przy udanej paczce."""
import unittest

from pimp_list import (
    charge_token,
    disk_candidates,
    facts,
    find_on_disk,
    is_weird_remix,
    materialize,
    parse_model_json,
    pick_tidal_hit,
    prefer_local_options,
    rank_replacements,
    same_recording,
    with_version,
    reset_tokens,
    streaming_path,
    pimp_read_tokens,
    pimp_slices,
    suggest_prompt,
    summary_prompt,
    tokens_for_thousand,
    tokens_spent,
)


def _row(idx, author, title, genre="", path="/music/a.mp3", bpm=120, plays=0, streaming=False):
    return {
        "idx": idx,
        "author": author,
        "title": title,
        "genre": genre,
        "user1": "",
        "user2": "",
        "bpm": bpm,
        "year": "2011",
        "playcount": plays,
        "path": path,
        "streaming": streaming,
        "cache": False,
    }


class PimpListTests(unittest.TestCase):
    def setUp(self):
        reset_tokens()

    def test_weird_remix_is_out(self):
        self.assertTrue(is_weird_remix("Give Me Everything (Remix)"))
        self.assertTrue(is_weird_remix("Explosion (Extended Mix)"))
        self.assertFalse(is_weird_remix("I Love It"))
        self.assertFalse(is_weird_remix("Free from Desire (Radio Edit)"))

    def test_disk_candidate_is_same_artist_not_already_listed(self):
        on_list = [_row(1, "Rihanna", "Umbrella", genre="pop", path="/a.mp3")]
        library = on_list + [
            _row(2, "Rihanna", "We Found Love", genre="pop", path="/b.mp3", plays=4),
            _row(3, "Rihanna", "We Found Love (Remix)", genre="pop", path="/c.mp3", plays=9),
            _row(4, "Pitbull", "Give Me Everything", genre="jazz", path="/d.mp3"),
            _row(5, "Dua Lipa", "Levitating", genre="pop", path="/e.mp3"),
        ]
        info = facts(on_list)
        keys = {("rihanna", "umbrella")}
        found = disk_candidates(library, keys, info)
        titles = [row["title"] for row in found]
        self.assertIn("We Found Love", titles)
        self.assertIn("Levitating", titles)
        self.assertNotIn("We Found Love (Remix)", titles)
        self.assertNotIn("Umbrella", titles)
        self.assertNotIn("Give Me Everything", titles)

    def test_named_hit_on_disk_becomes_disk_row(self):
        rows = [_row(7, "Pitbull", "Give Me Everything", path="/pit.mp3", plays=3)]
        data = {
            "klimat": "parkiet",
            "propozycje": [
                {"zrodlo": "brak", "artysta": "Pitbull", "tytul": "Give Me Everything", "dlaczego": "brakuje"},
                {"zrodlo": "brak", "artysta": "Icona Pop", "tytul": "I Love It", "dlaczego": "most"},
                {"zrodlo": "brak", "artysta": "Gala", "tytul": "Free from Desire (Remix)", "dlaczego": "nie"},
            ],
        }
        climate, suggestions = materialize(data, [], rows, set())
        self.assertEqual(climate, "parkiet")
        self.assertEqual(suggestions[0]["kind"], "disk")
        self.assertEqual(suggestions[0]["path"], "/pit.mp3")
        self.assertEqual(suggestions[1]["kind"], "tidal")
        self.assertEqual(len(suggestions), 2)

    def test_mixed_prompt_names_the_bridge(self):
        tracks = [
            _row(1, "Anyma", "After Dark", genre="techno"),
            _row(2, "ABBA", "Dancing Queen", genre="wesele"),
        ]
        info = facts(tracks)
        self.assertTrue(info["mixed"])
        text = suggest_prompt("Sala", info, tracks, "dzień kobiet", [], [])
        self.assertIn("Nagrania już na liście", text)
        self.assertIn("dzień kobiet", text)
        self.assertIn("Anyma - After Dark", text)
        self.assertIn("ABBA - Dancing Queen", text)
        self.assertNotIn("Najczęściej", text)

    def test_whole_playlist_is_priced_per_300(self):
        self.assertEqual(pimp_read_tokens(0), 0)
        self.assertEqual(pimp_read_tokens(300), 1)
        self.assertEqual(pimp_read_tokens(301), 2)
        tracks = [_row(i, f"Artist {i}", f"Title number {i}") for i in range(45)]
        info = facts(tracks)
        text = summary_prompt("Sala", info, tracks)
        self.assertIn("Artist 0 - Title number 0", text)
        self.assertIn("Artist 44 - Title number 44", text)
        self.assertEqual(len(pimp_slices(tracks)), 1)

    def test_parse_fenced_json(self):
        data = parse_model_json('```json\n{"klimat":"x","propozycje":[]}\n```')
        self.assertEqual(data["klimat"], "x")

    def test_tidal_pick_rejects_a_random_first_hit(self):
        results = [
            {"id": "1", "artist": "Someone", "title": "Other Song"},
            {"id": "2", "artist": "Icona Pop", "title": "I Love It"},
        ]
        hit = pick_tidal_hit(results, "Icona Pop", "I Love It")
        self.assertEqual(hit["id"], "2")
        self.assertIsNone(pick_tidal_hit(results, "Pitbull", "Timber"))

    def test_balance_reaches_zero(self):
        import pimp_list
        from unittest.mock import patch
        pimp_list._balance = 1
        pimp_list._balance_ready = True
        pimp_list._tokens_spent = 0
        with patch("njr_account.spend_tokens", return_value={"tokens": 0}):
            charge_token()
        self.assertEqual(pimp_list.token_balance(), 0)
        self.assertEqual(tokens_spent(), 1)

    def test_collection_spelling_finds_the_disk_file(self):
        library = [
            _row(1, "SAFRI DUO -", "Played-A-Live (Album Version)", path="/safri.mp3"),
            _row(2, "Gigi D'agostino", "lamour toujour", path="/gigi.mp3"),
            _row(3, "Sash!", "Equador (Original Extended)", path="/sash.mp3"),
            _row(4, "Alice Deejay", "Better Off Alone (Clean) (Extended)", path="/alice-ext.mp3"),
            _row(5, "Alice Deejay", "Better Off Alone (QH) (Marty Mar Edit)", path="/alice-edit.mp3"),
            _row(6, "GEO DA SILVA & CANELLO", "Freed From Desire (Extended Mix)", path="/cover.mp3"),
            _row(7, "PAKITO", "LIVING on VIDEO ENDRIU BOOTLEG", path="/boot.mp3"),
        ]
        playlist = library[:3]
        data = {
            "klimat": "klub",
            "propozycje": [
                {"zrodlo": "brak", "artysta": "Safri Duo", "tytul": "Played-A-Live (The Bongo Song)", "dlaczego": "hymn"},
                {"zrodlo": "brak", "artysta": "Gigi D'Agostino", "tytul": "L'Amour Toujours", "dlaczego": "chór"},
                {"zrodlo": "brak", "artysta": "Sash!", "tytul": "Ecuador", "dlaczego": "trance"},
                {"zrodlo": "brak", "artysta": "Alice Deejay", "tytul": "Better Off Alone", "dlaczego": "euro"},
                {"zrodlo": "brak", "artysta": "Gala", "tytul": "Freed From Desire", "dlaczego": "most"},
                {"zrodlo": "brak", "artysta": "Pakito", "tytul": "Living On Video", "dlaczego": "klub"},
            ],
        }
        _climate, suggestions = materialize(data, [], library, set(), playlist_rows=playlist)
        artists = [row["artist"] for row in suggestions]
        self.assertNotIn("Safri Duo", artists)
        self.assertNotIn("Gigi D'Agostino", artists)
        self.assertNotIn("Sash!", artists)
        alice = next(row for row in suggestions if row["artist"] == "Alice Deejay")
        self.assertEqual(alice["kind"], "tidal")
        self.assertFalse(any(row.get("already") for row in alice["versions"]))
        self.assertIn("Better Off Alone (Clean) (Extended)", [row["title"] for row in alice["versions"]])
        gala = next(row for row in suggestions if row["artist"] == "Gala")
        self.assertEqual(gala["kind"], "tidal")
        pakito = next(row for row in suggestions if row["artist"] == "Pakito")
        self.assertEqual(pakito["versions"][0]["path"], "/boot.mp3")

    def test_short_titles_stay_different_songs(self):
        library = [
            _row(1, "ALVARO SOLER", "Magia (Radio Edit)", path="/magia.mp3"),
            _row(2, "Francesco Napoli", "Marina (Roberto Bedross Edit)", path="/marina.mp3"),
            _row(3, "GEO DA SILVA", "Marina (Extended Mix)", path="/marina2.mp3"),
        ]
        data = {"klimat": "klub", "propozycje": [
            {"zrodlo": "brak", "artysta": "Scooter", "tytul": "Maria (I Like It Loud)", "dlaczego": "hymn"},
        ]}
        _climate, suggestions = materialize(data, [], library, set())
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["kind"], "tidal")
        self.assertEqual(suggestions[0]["title"], "Maria")
        self.assertEqual(suggestions[0]["versions"], [])

    def test_shared_word_is_not_the_same_song(self):
        library = [
            _row(1, "Mike Candys feat. Sandra Wild", "Sunshine (Fly So High) (Radio Mix)", path="/radio.mp3"),
            _row(2, "NIZZA NOISE", "Sunshine Reggae (Beach Extended Mix)", path="/reggae1.mp3"),
            _row(3, "Laid Back", "Sunshine Reggae (Edit)", path="/reggae2.mp3"),
            _row(4, "TOUCH and GO", "Would You... (Radio Edit)", path="/would.mp3"),
        ]
        data = {"klimat": "klub", "propozycje": [
            {"zrodlo": "brak", "artysta": "Mike Candys", "tytul": "Sunshine (Fly So High)", "dlaczego": "hit"},
            {"zrodlo": "brak", "artysta": "C-Bool", "tytul": "Would You Feel", "dlaczego": "klub"},
        ]}
        _climate, suggestions = materialize(data, [], library, set())
        sun = next(row for row in suggestions if row["title"].startswith("Sunshine"))
        self.assertEqual(
            [row["title"] for row in sun["versions"]],
            ["Sunshine (Fly So High) (Radio Mix)"],
        )
        would = next(row for row in suggestions if "Would You" in row["title"])
        self.assertEqual(would["versions"], [])

    def test_named_edits_sit_under_the_original(self):
        library = [
            _row(1, "Alice Deejay", "Better Off Alone (Radio Edit)", path="/radio.mp3"),
            _row(2, "ATB", "Better Off Alone (ATB Remix)", path="/atb.mp3"),
            _row(3, "Tiësto", "Better Off Alone (Tiesto Edit)", path="/tiesto.mp3"),
            _row(4, "Cover Band", "Better Off Alone (Cover)", path="/cover.mp3"),
        ]
        data = {"klimat": "klub", "propozycje": [
            {"zrodlo": "brak", "artysta": "Alice Deejay", "tytul": "Better Off Alone", "dlaczego": "oryginał"},
        ]}
        _climate, suggestions = materialize(data, [], library, set())
        self.assertEqual(len(suggestions), 1)
        parent = suggestions[0]
        self.assertEqual(parent["kind"], "tidal")
        letters = [row["title"] for row in parent["versions"]]
        self.assertEqual(letters[0], "Better Off Alone (Radio Edit)")
        self.assertIn("Better Off Alone (ATB Remix)", letters)
        self.assertIn("Better Off Alone (Tiesto Edit)", letters)
        self.assertIn("Better Off Alone (Cover)", letters)

    def test_streaming_path_follows_the_program(self):
        self.assertEqual(streaming_path("vdj", "42"), "netsearch://td42")
        self.assertEqual(streaming_path("serato", "42"), "streaming://tidal/42")
        self.assertEqual(streaming_path("rekordbox", "42"), "file://localhosttidal:tracks:42")

    def test_local_file_is_preferred_over_tidal_and_remix(self):
        options, preferred = prefer_local_options(
            [
                {"title": "Criminal (Remix)", "kind": "disk"},
                {"title": "Criminal", "kind": "disk"},
            ],
            [{"title": "Criminal", "kind": "tidal"}],
        )
        self.assertEqual(options[0]["title"], "Criminal")
        self.assertEqual(options[0]["kind"], "disk")
        self.assertEqual(preferred, 0)
        self.assertEqual(options[-1]["title"], "Criminal (Remix)")
        remix_only, remix_pick = prefer_local_options(
            [{"title": "Criminal (Remix)", "kind": "disk"}],
            [],
        )
        self.assertEqual(remix_pick, -1)
        self.assertEqual(len(remix_only), 1)
        self.assertEqual(tokens_for_thousand(0), 0)
        self.assertEqual(tokens_for_thousand(1), 1)
        self.assertEqual(tokens_for_thousand(1000), 1)
        self.assertEqual(tokens_for_thousand(1001), 2)
        self.assertEqual(tokens_for_thousand(6000), 6)

    def test_replacement_drops_a_different_song_by_the_same_artist(self):
        self.assertFalse(same_recording(
            "Crying at the Discoteque",
            "This Is The World We Live In (Album Version)",
        ))
        self.assertTrue(same_recording(
            "Crying at the Discoteque",
            "Crying at the Discoteque (Radio Edit)",
        ))
        options, preferred = rank_replacements(
            "Alcazar",
            "Crying at the Discoteque",
            [
                {"kind": "disk", "author": "ALCAZAR", "title": "This Is The World We Live In (Album Version)"},
                {"kind": "tidal", "author": "Alcazar", "title": "Crying at the Discoteque"},
                {"kind": "disk", "author": "Alcazar", "title": "Crying at the Discoteque (Radio Edit)"},
            ],
        )
        self.assertEqual([row["title"] for row in options], [
            "Crying at the Discoteque (Radio Edit)",
            "Crying at the Discoteque",
        ])
        self.assertEqual(options[0]["kind"], "disk")
        self.assertEqual(preferred, 0)

    def test_replacement_prefers_the_artist_without_extra_names(self):
        options, preferred = rank_replacements(
            "Dr Alban",
            "Sing Hallelujah",
            [
                {"kind": "disk", "author": "POPEK, DR ALBAN, CLAY", "title": "Sing Hallelujah (Radio Edit)"},
                {"kind": "disk", "author": "Scotty Pres", "title": "Sing Hallelujah (Scotty Edit)"},
                {"kind": "disk", "author": "DR. ALBAN", "title": "Sing Hallelujah (Radio Edit)"},
                {"kind": "tidal", "author": "Dr Alban", "title": "Sing Hallelujah (Remix)"},
                {"kind": "disk", "author": "Dr Alban", "title": "It's My Life (Raggadag Remix)"},
            ],
        )
        self.assertEqual(options[0]["author"], "DR. ALBAN")
        self.assertEqual(preferred, 0)
        titles = [row["title"] for row in options]
        authors = [row["author"] for row in options]
        self.assertNotIn("It's My Life (Raggadag Remix)", titles)
        self.assertNotIn("Scotty Pres", authors)
        self.assertLess(authors.index("DR. ALBAN"), authors.index("POPEK, DR ALBAN, CLAY"))
        self.assertLess(titles.index("Sing Hallelujah (Radio Edit)"), titles.index("Sing Hallelujah (Remix)"))
        remix_only, remix_pick = rank_replacements(
            "Dr Alban",
            "Sing Hallelujah",
            [{"kind": "disk", "author": "Dr Alban", "title": "Sing Hallelujah (Remix)"}],
        )
        self.assertEqual(remix_pick, -1)
        self.assertEqual(len(remix_only), 1)

    def test_same_title_by_another_artist_is_not_a_replacement(self):
        options, preferred = rank_replacements(
            "SylkaSy",
            "Nic do stracenia",
            [
                {"kind": "tidal", "author": "Mrozu", "title": "Nic Do Stracenia", "duration": 215},
                {"kind": "tidal", "author": "SVM!R", "title": "NIC DO STRACENIA", "duration": 184},
                {"kind": "tidal", "author": "Baciary", "title": "Nic do stracenia", "duration": 188},
                {"kind": "tidal", "author": "T.LOVE", "title": "Nic do stracenia", "duration": 178},
            ],
            duration=172,
        )
        self.assertEqual(options, [])
        self.assertEqual(preferred, -1)
        mamy, _pick = rank_replacements(
            "Cypis",
            "Mamy Moc",
            [
                {"kind": "tidal", "author": "Cypis", "title": "Mamy Moc", "duration": 211},
                {"kind": "tidal", "author": "Gaja", "title": "Mamy moc", "duration": 238},
                {"kind": "tidal", "author": "Bosski", "title": "Mamy moc", "duration": 245},
                {"kind": "tidal", "author": "Big Cyc", "title": "Mamy Moc", "duration": 191},
            ],
            duration=211,
        )
        self.assertEqual([row["author"] for row in mamy], ["Cypis"])

    def test_bialy_mis_keeps_other_performers_of_the_same_song(self):
        options, preferred = rank_replacements(
            "Top One",
            "Biały miś",
            [
                {"kind": "tidal", "author": "Top One", "title": "BIAŁY MIŚ", "duration": 233},
                {"kind": "disk", "author": "Janusz Laskowski", "title": "Biały miś", "duration": 219},
                {"kind": "tidal", "author": "Boys", "title": "Hej sokoły", "duration": 223},
            ],
            duration=304,
        )
        authors = [row["author"] for row in options]
        self.assertEqual(authors[0], "Top One")
        self.assertIn("Janusz Laskowski", authors)
        self.assertNotIn("Boys", authors)
        self.assertEqual(preferred, 0)

    def test_live_loses_to_the_closer_studio_version(self):
        options, preferred = rank_replacements(
            "David Bowie",
            "Let's Dance (2002 Remaster)",
            [
                {"kind": "tidal", "author": "David Bowie", "title": "Let's Dance (Live, Glastonbury, 2000)", "duration": 427},
                {"kind": "tidal", "author": "David Bowie", "title": "Let's Dance (2002 Remaster)", "duration": 248},
                {"kind": "disk", "author": "David Bowie", "title": "Let's Dance (1999 Remastered Version)", "duration": 457},
            ],
            duration=245,
        )
        self.assertEqual(options[0]["title"], "Let's Dance (2002 Remaster)")
        self.assertEqual(preferred, 0)
        haddaway, _pick = rank_replacements(
            "Haddaway",
            "What Is Love (7\" Mix)",
            [
                {"kind": "disk", "author": "Johnny Price", "title": "What Is Love", "duration": 223},
                {"kind": "disk", "author": "Haddaway", "title": "What Is Love (Original 7' Mix)", "duration": 269},
                {"kind": "tidal", "author": "Party Tyme", "title": "What Is Love (Karaoke Version)", "duration": 270},
            ],
            duration=270,
        )
        self.assertEqual([row["author"] for row in haddaway], ["Haddaway"])

    def test_disk_radio_edit_beats_a_plain_tidal_copy(self):
        self.assertEqual(with_version("Królowa", "Fikoł & Fair Play Remix"), "Królowa (Fikoł & Fair Play Remix)")
        self.assertEqual(with_version("Unforgiven (DJ Erwin Remix)", ""), "Unforgiven (DJ Erwin Remix)")
        options, preferred = rank_replacements(
            "MiłyPan",
            "Królowa",
            [
                {"kind": "tidal", "author": "MiłyPan", "title": "Królowa", "duration": 245, "bpm": 138},
                {"kind": "tidal", "author": "MiłyPan", "title": "Królowa (Fikoł & Fair Play Remix)", "duration": 228, "bpm": 128},
                {"kind": "tidal", "author": "MiłyPan", "title": "Królowa (Short Version)", "duration": 190},
                {"kind": "disk", "author": "MiłyPan", "title": "Królowa (Radio Edit)", "duration": 210, "bpm": 138},
                {"kind": "disk", "author": "MIŁY PAN", "title": "Królowa (Radio Edit)", "duration": 246, "bpm": 138},
            ],
            duration=245,
            bpm=138,
        )
        self.assertEqual(options[0]["kind"], "disk")
        self.assertEqual(options[0]["duration"], 246)
        self.assertEqual(preferred, 0)
        titles = [row["title"] for row in options]
        self.assertLess(titles.index("Królowa (Radio Edit)"), titles.index("Królowa (Fikoł & Fair Play Remix)"))


if __name__ == "__main__":
    unittest.main()
