import unittest

from dup_search import cluster_recordings, duplicate_kind, same_recording


class DupSearchTests(unittest.TestCase):
    def test_kind_keeps_files_and_tidal_only(self):
        self.assertEqual(duplicate_kind("/Users/test/Music/a.mp3"), "file")
        self.assertEqual(duplicate_kind("netsearch://td9184437"), "tidal")
        self.assertEqual(duplicate_kind("netsearch://va5881"), "skip")
        self.assertEqual(duplicate_kind("netsearch://vj24261"), "skip")
        self.assertEqual(duplicate_kind("netsearch://dz3658193"), "skip")
        self.assertEqual(duplicate_kind("/tmp/song.vdjcache"), "skip")

    def test_cache_link_joins_stream_when_duration_matches(self):
        from dup_search import tidal_duplicate_groups

        songs = [
            {"FilePath": "netsearch://td100", "Infos.SongLength": "200"},
            {
                "FilePath": "/Cache/Artist - Song.vdjcache",
                "Link.NetSearch": "td100",
                "Infos.SongLength": "200.4",
            },
            {
                "FilePath": "/Cache/Artist - Remix.vdjcache",
                "Link.NetSearch": "td100",
                "Infos.SongLength": "270",
            },
        ]
        groups = tidal_duplicate_groups(songs)
        self.assertEqual(groups, [[0, 1]])

    def test_different_lengths_stay_apart(self):
        rows = [
            {"duration": "199.9", "tidal_id": "1"},
            {"duration": "339", "tidal_id": "2"},
            {"duration": "", "tidal_id": ""},
        ]
        self.assertEqual(cluster_recordings(rows), [])
        self.assertFalse(same_recording("199.9", "339"))

    def test_same_length_file_and_tidal_group(self):
        rows = [
            {"duration": "265.12", "tidal_id": ""},
            {"duration": "265.07", "tidal_id": "313281843"},
            {"duration": "240.8", "tidal_id": "9"},
            {"duration": "241.5", "tidal_id": "8"},
        ]
        groups = cluster_recordings(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0]), 2)
        self.assertEqual(len(groups[1]), 2)


if __name__ == "__main__":
    unittest.main()
