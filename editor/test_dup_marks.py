import unittest

from dup_marks import advise_group


def row(**kwargs):
    base = {
        "path": "/a.mp3",
        "pathSource": "dysk",
        "bitrate": "320",
        "rating": 0,
        "playcount": 0,
        "playlists_count": 0,
    }
    base.update(kwargs)
    return base


class TestAdviseGroup(unittest.TestCase):
    def test_disk_beats_tidal(self):
        advice = advise_group([
            row(path="/disk.mp3", pathSource="dysk", bitrate="192", playlists_count=1),
            row(path="streaming://tidal/1", pathSource="tidal", playlists_count=12, playcount=40, rating=255),
        ])
        self.assertTrue(advice["marked"])
        self.assertEqual(advice["keepPath"], "/disk.mp3")
        self.assertIn("dysku", advice["note"])

    def test_low_bitrate_disk_loses_to_tidal(self):
        advice = advise_group([
            row(path="/disk.mp3", pathSource="dysk", bitrate="96", playlists_count=8),
            row(path="streaming://tidal/2", pathSource="tidal", bitrate="", playlists_count=1),
        ])
        self.assertEqual(advice["keepPath"], "streaming://tidal/2")
        self.assertIn("96", advice["note"])

    def test_lists_stars_and_plays(self):
        advice = advise_group([
            row(path="/weak.mp3", playlists_count=1, rating=51, playcount=2, bitrate="320"),
            row(path="/strong.mp3", playlists_count=6, rating=255, playcount=20, bitrate="256"),
        ])
        self.assertEqual(advice["keepPath"], "/strong.mp3")
        self.assertIn("6 list", advice["note"])

    def test_tie_marks_nothing(self):
        advice = advise_group([
            row(path="/a.mp3", playlists_count=2, rating=102, playcount=3, bitrate="320"),
            row(path="/b.mp3", playlists_count=2, rating=102, playcount=3, bitrate="320"),
        ])
        self.assertFalse(advice["marked"])
        self.assertEqual(advice["keepPath"], "")


if __name__ == "__main__":
    unittest.main()
