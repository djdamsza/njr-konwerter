"""Szukanie baz DJ i kopia, którą da się przywrócić."""
import unittest
from pathlib import Path


class TestDjLibraries(unittest.TestCase):
    def test_locate_serato_sqlite_and_backup_roundtrip(self):
        import tempfile

        from dj_libraries import create_backup, locate, restore_backup

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            library = home / "Library" / "Application Support" / "Serato" / "Library"
            library.mkdir(parents=True)
            master = library / "master.sqlite"
            root = library / "root.sqlite"
            master.write_bytes(b"master-v1")
            root.write_bytes(b"root-v1")

            info = locate("serato", home)
            self.assertTrue(info["importable"])
            self.assertEqual(info["kind"], "serato-sqlite")
            self.assertEqual(Path(info["path"]), library)

            backup = create_backup("serato", home)
            self.assertGreaterEqual(backup["files"], 2)
            master.write_bytes(b"master-changed")
            restored = restore_backup("serato", home)
            self.assertIn(str(master), restored["restored"])
            self.assertEqual(master.read_bytes(), b"master-v1")

    def test_only_three_backups_are_kept(self):
        import tempfile

        from dj_libraries import BACKUP_KEEP, backup_root, create_backup, restore_backup

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            library = home / "Library" / "Application Support" / "Serato" / "Library"
            library.mkdir(parents=True)
            master = library / "master.sqlite"
            (library / "root.sqlite").write_bytes(b"root")
            for n in range(5):
                master.write_bytes(f"v{n}".encode())
                create_backup("serato", home)
            kept = [p for p in (backup_root(home) / "serato").iterdir() if p.is_dir()]
            self.assertEqual(len(kept), BACKUP_KEEP)
            master.write_bytes(b"changed")
            restore_backup("serato", home)
            self.assertEqual(master.read_bytes(), b"v4")

    def test_backup_list_open_and_delete(self):
        import tempfile

        from dj_libraries import (
            backup_day_label,
            create_backup,
            delete_backup,
            list_backups,
            materialize_backup,
        )

        self.assertIn("października 2026", backup_day_label("20261016_141009"))
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            library = home / "Library" / "Application Support" / "Serato" / "Library"
            library.mkdir(parents=True)
            (library / "master.sqlite").write_bytes(b"master")
            (library / "root.sqlite").write_bytes(b"root")
            made = create_backup("serato", home)
            copies = list_backups("serato", home)
            self.assertEqual(len(copies), 1)
            self.assertEqual(copies[0]["stamp"], made["stamp"])
            with tempfile.TemporaryDirectory() as opened:
                target = materialize_backup("serato", made["stamp"], Path(opened), home)
                self.assertTrue((target / "master.sqlite").is_file())
            delete_backup("serato", made["stamp"], home)
            self.assertEqual(list_backups("serato", home), [])

    def test_rekordbox_db_backup_needs_xml(self):
        import json
        import tempfile

        from dj_libraries import backup_root, materialize_backup

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            stamp = "20261016_141009"
            folder = backup_root(home) / "rekordbox" / stamp
            folder.mkdir(parents=True)
            (folder / "00_master.db").write_bytes(b"db")
            (folder / "manifest.json").write_text(json.dumps({
                "created": stamp,
                "files": [{"file": "00_master.db", "src": "/Library/Pioneer/rekordbox/master.db"}],
            }), encoding="utf-8")
            with tempfile.TemporaryDirectory() as opened:
                with self.assertRaises(ValueError):
                    materialize_backup("rekordbox", stamp, Path(opened), home)

    def test_rekordbox_without_xml_is_not_importable(self):
        import tempfile

        from dj_libraries import locate

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            folder = home / "Library" / "Pioneer" / "rekordbox"
            folder.mkdir(parents=True)
            (folder / "master.db").write_bytes(b"db")
            info = locate("rekordbox", home)
            self.assertTrue(info["found"])
            self.assertFalse(info["importable"])
            (folder / "collection.xml").write_text("<DJ_PLAYLISTS/>", encoding="utf-8")
            (folder / "automixPlaylist6.xml").write_text("<AUTOMIX/>", encoding="utf-8")
            info = locate("rekordbox", home)
            self.assertTrue(info["importable"])
            self.assertTrue(info["path"].endswith("collection.xml"))

    def test_traktor_nml_roundtrip(self):
        import tempfile

        from traktor_parser import load_traktor_nml, save_traktor_nml
        from unified_model import Playlist, Track, UnifiedDatabase

        db = UnifiedDatabase(
            tracks=[Track(path="/Users/dj/Music/a.mp3", title="Song", artist="DJ", bpm=128)],
            playlists=[Playlist(name="wesele", track_ids=["/Users/dj/Music/a.mp3"])],
            source="traktor",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "collection.nml"
            path.write_bytes(save_traktor_nml(db))
            loaded = load_traktor_nml(path)
            self.assertEqual(loaded.tracks[0].title, "Song")
            self.assertEqual(loaded.tracks[0].path, "/Users/dj/Music/a.mp3")
            self.assertEqual(loaded.playlists[0].name, "wesele")
            self.assertIn("/Users/dj/Music/a.mp3", loaded.playlists[0].track_ids)


if __name__ == "__main__":
    unittest.main()
