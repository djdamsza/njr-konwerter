"""Skan dysku: plik spoza bazy wchodzi, plik z bazy i folder Library odpadają."""
import tempfile
import unittest
from pathlib import Path

from routes.files import iter_orphan_audio


class OrphanDiskTests(unittest.TestCase):
    def test_finds_music_missing_from_db_and_skips_library(self):
        root = Path(tempfile.mkdtemp())
        known = root / "znany.mp3"
        known.write_bytes(b"a")
        missing = root / "nowy.mp3"
        missing.write_bytes(b"b")
        library = root / "Library"
        library.mkdir()
        (library / "ukryty.mp3").write_bytes(b"c")
        (root / "notatka.txt").write_text("x")
        found, capped, _errors = iter_orphan_audio([root], {str(known.resolve())}, limit=10)
        paths = {row["path"] for row in found}
        self.assertIn(str(missing.resolve()), paths)
        self.assertNotIn(str(known.resolve()), paths)
        self.assertFalse(any("ukryty.mp3" in path for path in paths))
        self.assertFalse(capped)


if __name__ == "__main__":
    unittest.main()
