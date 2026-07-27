"""Ścieżki VDJ: //Users bliźniaki, CRLF przy zapisie, dedupe przy eksporcie."""
import io
import tempfile
import unittest
from pathlib import Path

from vdjfolder import normalize_path
from vdj_parser import load_database, prepare_songs_for_vdj_write, save_database


class TestNormalizePathSlash(unittest.TestCase):
    def test_collapses_double_slash_filesystem(self):
        self.assertEqual(normalize_path("//Users/test/a.mp3"), "/Users/test/a.mp3")
        self.assertEqual(normalize_path("/Users/test//a.mp3"), "/Users/test/a.mp3")

    def test_preserves_url_schemes(self):
        self.assertEqual(normalize_path("netsearch://td123"), "netsearch://td123")
        self.assertEqual(normalize_path("clouddrive://foo//bar"), "clouddrive://foo/bar")


class TestPrepareAndSave(unittest.TestCase):
    def test_dedupe_slash_twins_keeps_richer(self):
        songs = [
            {"FilePath": "//Users/test/a.mp3", "Tags.Title": "Thin"},
            {
                "FilePath": "/Users/test/a.mp3",
                "Tags.Title": "Rich",
                "Tags.Author": "Artist",
                "_children_xml": ['<Poi Type="cue" />'],
            },
        ]
        out = prepare_songs_for_vdj_write(songs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["FilePath"], "/Users/test/a.mp3")
        self.assertEqual(out[0]["Tags.Title"], "Rich")

    def test_save_uses_crlf_and_no_double_slash(self):
        songs = [
            {"FilePath": "//Users/test/a.mp3", "Tags.Title": "A"},
            {"FilePath": "/Users/test/a.mp3", "Tags.Title": "A2", "Tags.Author": "X"},
            {"FilePath": "netsearch://td9", "Tags.Title": "Stream"},
        ]
        buf = io.BytesIO()
        save_database(buf, songs, "2026")
        data = buf.getvalue()
        self.assertGreater(data.count(b"\r\n"), 0)
        self.assertNotIn(b'FilePath="//Users', data)
        self.assertIn(b'FilePath="/Users/test/a.mp3"', data)
        self.assertIn(b'FilePath="netsearch://td9"', data)
        # jeden Song dla a.mp3
        self.assertEqual(data.count(b"<Song "), 2)

    def test_load_normalizes_double_slash(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\r\n'
            '<VirtualDJ_Database Version="2026">\r\n'
            ' <Song FilePath="//Users/test/a.mp3" FileSize="1">\r\n'
            '  <Tags Title="T" />\r\n'
            " </Song>\r\n"
            "</VirtualDJ_Database>\r\n"
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "database.xml"
            p.write_bytes(xml.encode("utf-8"))
            songs, ver = load_database(p)
        self.assertEqual(ver, "2026")
        self.assertEqual(songs[0]["FilePath"], "/Users/test/a.mp3")


if __name__ == "__main__":
    unittest.main()
