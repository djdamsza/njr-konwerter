import unittest

from title_clean import clean_junk


class TestTitleClean(unittest.TestCase):
    def test_keeps_version_and_real_parens(self):
        self.assertEqual(clean_junk("Song (Radio Edit)"), "Song (Radio Edit)")
        self.assertEqual(clean_junk("Song (Original Mix)"), "Song (Original Mix)")
        self.assertEqual(clean_junk("Song (Tall Paul Remix)"), "Song (Tall Paul Remix)")
        self.assertEqual(
            clean_junk("Dom (Laga Czigi) (SOUND BASS Official Remix)"),
            "Dom (Laga Czigi) (SOUND BASS Official Remix)",
        )
        self.assertEqual(
            clean_junk("King Of My Castle (Roy Malone Remix) (Clean) (Extended)"),
            "King Of My Castle (Roy Malone Remix) (Clean) (Extended)",
        )
        self.assertEqual(clean_junk("Ritmo (Bad Boys For Life) (Explicit)"), "Ritmo (Bad Boys For Life) (Explicit)")
        self.assertEqual(clean_junk("Song Club Mix"), "Song Club Mix")
        self.assertEqual(clean_junk("Tonacja C#m"), "Tonacja C#m")

    def test_strips_platform_junk(self):
        self.assertEqual(clean_junk("Song (Official Video)"), "Song")
        self.assertEqual(clean_junk("Song (Official Audio) [HD]"), "Song")
        self.assertEqual(clean_junk("Song (4K)"), "Song")
        self.assertEqual(clean_junk("NIC SIĘ NIE STAŁO (Official Game Over Song of Polish National Team)"), "NIC SIĘ NIE STAŁO")
        self.assertEqual(clean_junk("Polonez (videoo-info)"), "Polonez")
        self.assertEqual(
            clean_junk("Każdy ptaszek ( official ) piosenka #musicremixdance"),
            "Każdy ptaszek piosenka",
        )
        self.assertEqual(clean_junk("Song https://youtu.be/abc a@b.pl"), "Song")
        self.assertEqual(clean_junk("Hit www.example.com"), "Hit")


if __name__ == "__main__":
    unittest.main()
