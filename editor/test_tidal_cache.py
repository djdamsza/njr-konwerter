"""Testy Tidal Cache → Serato."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vdj_tidal_cache import extract_netsearch_link, scan_tidal_cache_entries


class TestVdjTidalCacheScan(unittest.TestCase):
    def test_extract_netsearch_link(self):
        s = {
            "_children_xml": ['<Link NetSearch="td12345" />'],
            "FilePath": "netsearch://td12345",
        }
        self.assertEqual(extract_netsearch_link(s), "12345")

    def test_scan_cached_and_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "Artist - Song.vdjcache"
            cache.write_bytes(b"VDJCACHE600")
            songs = [
                {
                    "FilePath": "netsearch://td999",
                    "Tags.Author": "Artist",
                    "Tags.Title": "Song",
                    "Infos.SongLength": "180",
                },
                {
                    "FilePath": "netsearch://td111",
                    "Tags.Author": "Other",
                    "Tags.Title": "Online",
                    "Infos.SongLength": "200",
                },
            ]
            result = scan_tidal_cache_entries(
                songs,
                vdj_cache_path=tmp,
                manifest_tracks={},
            )
            entries = {e["tidalId"]: e for e in result["entries"]}
            self.assertTrue(entries["999"]["cached"])
            self.assertFalse(entries["111"]["cached"])
            self.assertEqual(result["stats"]["cached_vdj"], 1)

    def test_scan_manifest_downloaded(self):
        with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
            f.write(b"fake")
            local = f.name
        try:
            songs = [
                {
                    "FilePath": "netsearch://td555",
                    "Tags.Author": "A",
                    "Tags.Title": "B",
                },
            ]
            manifest = {"555": {"path": local, "author": "A", "title": "B"}}
            result = scan_tidal_cache_entries(songs, manifest_tracks=manifest)
            e = next(x for x in result["entries"] if x["tidalId"] == "555")
            self.assertEqual(e["downloadStatus"], "downloaded")
            self.assertEqual(e["localPath"], local)
        finally:
            Path(local).unlink(missing_ok=True)


class TestTidalDownloadManifest(unittest.TestCase):
    def test_manifest_substitutes(self):
        import tidal_download as td

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp)
            with tempfile.NamedTemporaryFile(suffix=".mp3", dir=tmp, delete=False) as f:
                f.write(b"x")
                path = f.name
            try:
                with patch.object(td, "config_dir", return_value=cfg):
                    with patch.object(td, "manifest_path", return_value=cfg / "manifest.json"):
                        manifest = {"version": 1, "tracks": {"42": {"path": path, "author": "X", "title": "Y"}}}
                        td.save_manifest(manifest)
                        subs = td.manifest_substitutes()
                        self.assertIn(path, subs.values())
            finally:
                Path(path).unlink(missing_ok=True)

    @patch("tidal_download.find_tiddl_executable", return_value="/usr/bin/tiddl")
    @patch("tidal_download.subprocess.run")
    def test_download_mock_tiddl(self, mock_run, _find):
        import tidal_download as td

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp)

            def fake_run(cmd, **kwargs):
                out_flag_idx = None
                for i, p in enumerate(cmd):
                    if p in ("-p", "--output", "--path") and i + 1 < len(cmd):
                        out_flag_idx = i + 1
                        break
                out = Path(out_flag_idx and cmd[out_flag_idx] or tmp)
                p = out / "Artist" / "track.flac"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"flac")

                class R:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return R()

            mock_run.side_effect = fake_run

            with patch.object(td, "config_dir", return_value=cfg):
                with patch.object(td, "manifest_path", return_value=cfg / "manifest.json"):
                    with patch.object(td, "output_dir", return_value=cfg / "out"):
                        (cfg / "out").mkdir()
                        path, err = td.download_track_to_manifest(
                            "777", author="Artist", title="Track", out_dir=cfg / "out"
                        )
                        self.assertIsNone(err)
                        self.assertTrue(path and Path(path).is_file())
                        self.assertIn("777", td.manifest_tracks())


class TestTiddlLoginStatus(unittest.TestCase):
    def test_tiddl_logged_in_false_when_no_token(self):
        import tidal_download as td

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "tiddl.json"
            cfg.write_text('{"auth": {"token": "", "user_id": ""}}', encoding="utf-8")
            with patch.object(td, "_tiddl_config_path", return_value=cfg):
                self.assertFalse(td.tiddl_logged_in())

    def test_tiddl_logged_in_true_with_token(self):
        import tidal_download as td

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "tiddl.json"
            cfg.write_text('{"auth": {"token": "abc", "user_id": "123"}}', encoding="utf-8")
            with patch.object(td, "_tiddl_config_path", return_value=cfg):
                self.assertTrue(td.tiddl_logged_in())

    @patch("tidal_download.tiddl_logged_in", return_value=False)
    @patch("tidal_download.find_tiddl_executable", return_value="/usr/bin/tiddl")
    def test_tool_status_not_logged_in(self, _find, _logged):
        import tidal_download as td

        st = td.tiddl_tool_status()
        self.assertTrue(st["installed"])
        self.assertFalse(st["logged_in"])
        self.assertIn("auth login", st["hint"])


class TestTidalVdjMetadata(unittest.TestCase):
    def test_find_vdj_song_by_netsearch_link(self):
        from tidal_vdj_metadata import find_vdj_song_for_tidal_id

        songs = [
            {
                "FilePath": "/cache/Artist - Song.vdjcache",
                "_children_xml": ['<Link NetSearch="td999" />'],
                "Tags.Author": "Artist",
                "Tags.Title": "Song",
            },
        ]
        hit = find_vdj_song_for_tidal_id("999", songs)
        self.assertIsNotNone(hit)


class TestSeratoManifestPriority(unittest.TestCase):
    def test_manifest_before_streaming(self):
        from serato_offline import build_serato_offline_substitutes

        with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
            f.write(b"x")
            local = f.name
        try:
            import tidal_download as td

            with patch.object(td, "manifest_substitutes", return_value={
                "netsearch://td888": local,
            }):
                songs = [
                    {
                        "FilePath": "netsearch://td888",
                        "Tags.Author": "Z",
                        "Tags.Title": "W",
                    },
                ]
                subs, stats = build_serato_offline_substitutes(songs)
                self.assertEqual(subs.get("netsearch://td888"), local)
                self.assertEqual(stats["tidal_njr_download"], 1)
        finally:
            Path(local).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
