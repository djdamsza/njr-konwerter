"""Brakujące pliki: streaming odpada, niepodpięty dysk widać po ścieżce."""
import unittest

from missing_files import in_trash, index_audio, is_streaming_path, pick_new_path, volume_unmounted


class MissingFilesTests(unittest.TestCase):
    def test_streaming_stays_out(self):
        self.assertTrue(is_streaming_path("netsearch://td123"))
        self.assertTrue(is_streaming_path("streaming://tidal/99"))
        self.assertTrue(is_streaming_path("td252147049"))
        self.assertFalse(is_streaming_path("/Users/test/Desktop/muzyka dj/a.mp3"))

    def test_unmounted_volume_and_trash(self):
        self.assertEqual(volume_unmounted("/Volumes/NieMaTakiegoDyskuXYZ/a.mp3"), "NieMaTakiegoDyskuXYZ")
        self.assertEqual(volume_unmounted("/Users/test/Music/a.mp3"), "")
        self.assertEqual(volume_unmounted("Z:\\Muzyka\\a.mp3"), "Z:")
        self.assertTrue(in_trash("/Users/test/Trash/utwor.mp3"))
        self.assertTrue(in_trash("C:\\$Recycle.Bin\\S-1\\utwor.mp3"))
        self.assertFalse(in_trash("/Users/test/Desktop/muzyka dj/utwor.mp3"))

    def test_dangling_link_is_not_a_found_file(self):
        import tempfile
        from pathlib import Path

        root = Path(tempfile.mkdtemp())
        real = root / "muzyka"
        real.mkdir()
        song = real / "Get Ready.mp3"
        song.write_bytes(b"mp3")
        engine = root / "Engine Library"
        engine.mkdir()
        (engine / "Get Ready.mp3").symlink_to(song)
        (engine / "Gone.mp3").symlink_to(real / "nie-ma.mp3")
        index = index_audio([engine], {".mp3"})
        self.assertEqual(index.get("get ready"), [str(song.resolve())])
        self.assertNotIn("gone", index)

    def test_pick_same_filename_not_the_old_path(self):
        chosen = pick_new_path(
            "/Volumes/Stary/Maria.mp3",
            ["/Volumes/Stary/Maria.mp3", "/Users/test/Desktop/muzyka dj/Maria.mp3"],
        )
        self.assertEqual(chosen, "/Users/test/Desktop/muzyka dj/Maria.mp3")


if __name__ == "__main__":
    unittest.main()
