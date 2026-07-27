"""Testy stylu ścieżek Serato i dedupe klonów /Users vs Users."""
import struct
import unittest
from io import BytesIO
from pathlib import Path

from serato_parser import (
    _encode_utf16be,
    _parse_serato_tcom,
    _path_to_serato_relative,
    _write_serato_record,
    dedupe_serato_database_v2,
    detect_serato_path_style,
    filter_track_paths_for_serato,
    load_serato_database_v2,
    normalize_serato_blob_to_relative,
    resolve_local_audio_path,
    save_serato_crate,
    save_serato_database_v2,
    serato_path_identity_key,
    to_serato_relative_path,
)


def _otrk(path: str, plays: int = 0, rating: int = 0) -> bytes:
    otrk = BytesIO()
    _write_serato_record(otrk, "pfil", _encode_utf16be(path))
    _write_serato_record(otrk, "tsng", _encode_utf16be("Song"))
    if rating:
        _write_serato_record(otrk, "tcom", _encode_utf16be(f"c | Rating: {rating}"))
    _write_serato_record(otrk, "utpc", struct.pack(">I", plays))
    return otrk.getvalue()


def _db(*otrks: bytes) -> bytes:
    buf = BytesIO()
    _write_serato_record(buf, "vrsn", _encode_utf16be("2.0/Serato Scratch LIVE Database"))
    for o in otrks:
        _write_serato_record(buf, "otrk", o)
    return buf.getvalue()


class TestSeratoTcomRating(unittest.TestCase):
    def test_standalone_rating_strips_comment(self):
        comment, stars = _parse_serato_tcom("Rating: 3")
        self.assertEqual(stars, 3)
        self.assertEqual(comment, "")

    def test_pipe_rating_keeps_comment(self):
        comment, stars = _parse_serato_tcom("my note | Rating: 4")
        self.assertEqual(stars, 4)
        self.assertEqual(comment, "my note")

    def test_load_db_standalone_rating(self):
        otrk = BytesIO()
        _write_serato_record(otrk, "pfil", _encode_utf16be("/Users/test/Music/a.mp3"))
        _write_serato_record(otrk, "tcom", _encode_utf16be("Rating: 5"))
        _write_serato_record(otrk, "talb", _encode_utf16be("Album X"))
        _write_serato_record(otrk, "ttyr", _encode_utf16be("2020"))
        db = load_serato_database_v2(
            _db(otrk.getvalue()),
            drive_root="/",
        )
        self.assertEqual(len(db.tracks), 1)
        t = db.tracks[0]
        self.assertEqual(t.rating, 255)
        self.assertEqual(t.comment, "")
        self.assertEqual(t.album, "Album X")
        self.assertEqual(t.year, 2020)


class TestSeratoPathIdentity(unittest.TestCase):
    def test_abs_and_rel_same_key(self):
        a = "/Users/test/Desktop/a.mp3"
        b = "Users/test/Desktop/a.mp3"
        self.assertEqual(serato_path_identity_key(a), serato_path_identity_key(b))

    def test_detect_absolute_dominant(self):
        self.assertEqual(
            detect_serato_path_style([
                "/Users/x/a.mp3",
                "/Users/x/b.mp3",
                "Users/x/c.mp3",
            ]),
            "absolute",
        )

    def test_path_style_absolute_keeps_slash(self):
        p = _path_to_serato_relative(
            "/Users/test/Desktop/a.mp3",
            "/",
            path_style="absolute",
        )
        self.assertEqual(p, "/Users/test/Desktop/a.mp3")

    def test_path_style_relative_strips(self):
        p = _path_to_serato_relative(
            "/Users/test/Desktop/a.mp3",
            "/",
            path_style="relative",
        )
        self.assertEqual(p, "Users/test/Desktop/a.mp3")

    def test_relative_without_drive_root_strips_slash(self):
        p = _path_to_serato_relative("/Users/test/Desktop/a.mp3", None, path_style="relative")
        self.assertEqual(p, "Users/test/Desktop/a.mp3")

    def test_db_dedupes_abs_and_rel(self):
        songs = [
            {"FilePath": "/Users/test/Desktop/a.mp3", "Tags.Title": "A", "Infos.PlayCount": 1},
            {"FilePath": "Users/test/Desktop/a.mp3", "Tags.Title": "A", "Infos.PlayCount": 9},
        ]
        raw = save_serato_database_v2(songs, "/", path_style="relative")
        from serato_parser import _iter_top_level_raw, _parse_serato_records
        paths = []
        for name, data in _iter_top_level_raw(raw):
            if name != "otrk":
                continue
            for n, v in _parse_serato_records(BytesIO(data)):
                if n in ("pfil", "ptrk"):
                    paths.append(v.strip())
                    break
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], "Users/test/Desktop/a.mp3")

    def test_crate_dedupes(self):
        crate = save_serato_crate(
            [
                "/Users/test/Desktop/a.mp3",
                "Users/test/Desktop/a.mp3",
                "/Users/test/Desktop/b.mp3",
            ],
            "t",
            "/",
            path_style="relative",
            existing_files_only=False,
        )
        from serato_parser import _parse_serato_records
        paths = []
        for n, v in _parse_serato_records(BytesIO(crate)):
            if n == "otrk" and isinstance(v, list):
                for a, b in v:
                    if a in ("ptrk", "pfil"):
                        paths.append(b.strip())
                        break
        self.assertEqual(paths, ["Users/test/Desktop/a.mp3", "Users/test/Desktop/b.mp3"])


class TestSeratoStalePurge(unittest.TestCase):
    def test_drops_orphan_missing(self):
        from serato_parser import purge_serato_stale_duplicates, _iter_top_level_raw
        raw = _db(_otrk("Inne komputery/Mój MacBook Pro/ghost/nope-missing-xyz.mp3", plays=1))
        cleaned, st = purge_serato_stale_duplicates(raw)
        self.assertEqual(st["kept"], 0)
        self.assertEqual(st["removed"], 1)
        otrk = sum(1 for n, _ in _iter_top_level_raw(cleaned) if n == "otrk")
        self.assertEqual(otrk, 0)


class TestSeratoNormalize(unittest.TestCase):
    def test_to_relative(self):
        self.assertEqual(
            to_serato_relative_path("/Users/test/Desktop/a.mp3"),
            "Users/test/Desktop/a.mp3",
        )
        self.assertEqual(
            to_serato_relative_path("Users/test/Desktop/a.mp3"),
            "Users/test/Desktop/a.mp3",
        )

    def test_normalize_blob_rewrites_and_dedupes(self):
        abs_p = "/Users/test/Desktop/a.mp3"
        rel_p = "Users/test/Desktop/a.mp3"
        raw = _db(_otrk(abs_p, plays=50), _otrk(rel_p, plays=10))
        norm, n = normalize_serato_blob_to_relative(raw)
        self.assertGreaterEqual(n, 1)
        cleaned, stats = dedupe_serato_database_v2(norm, prefer_style="relative")
        self.assertEqual(stats["kept"], 1)
        from serato_parser import _iter_top_level_raw, _parse_serato_records
        paths = []
        for name, data in _iter_top_level_raw(cleaned):
            if name != "otrk":
                continue
            for n2, v in _parse_serato_records(BytesIO(data)):
                if n2 in ("pfil", "ptrk"):
                    paths.append(v.strip())
                    break
        self.assertEqual(paths, [rel_p])

    def test_removes_rel_clone_keeps_richer(self):
        abs_p = "/Users/test/Desktop/a.mp3"
        rel_p = "Users/test/Desktop/a.mp3"
        raw = _db(_otrk(rel_p, plays=10, rating=2), _otrk(abs_p, plays=50, rating=5))
        cleaned, stats = dedupe_serato_database_v2(raw, prefer_style="absolute")
        self.assertEqual(stats["original"], 2)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["removed"], 1)
        from serato_parser import _iter_top_level_raw, _parse_serato_records
        paths = []
        for name, data in _iter_top_level_raw(cleaned):
            if name != "otrk":
                continue
            for n, v in _parse_serato_records(BytesIO(data)):
                if n in ("pfil", "ptrk"):
                    paths.append(v.strip())
                    break
        self.assertEqual(paths, [abs_p])

    def test_no_dupes_unchanged_count(self):
        raw = _db(_otrk("/Users/test/a.mp3", 1), _otrk("/Users/test/b.mp3", 2))
        cleaned, stats = dedupe_serato_database_v2(raw)
        self.assertEqual(stats["removed"], 0)
        self.assertEqual(stats["kept"], 2)
        self.assertEqual(len(cleaned), len(raw))


class TestSeratoExportPathFilter(unittest.TestCase):
    def test_resolve_skips_missing(self):
        self.assertIsNone(resolve_local_audio_path("/no/such/file.mp3"))

    def test_filter_existing_only(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"x")
            tmp = f.name
        try:
            out = filter_track_paths_for_serato([
                tmp,
                "/definitely/missing/file.mp3",
            ])
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0], tmp)
        finally:
            import os
            os.unlink(tmp)

    def test_crate_omits_missing(self):
        import os
        import struct
        import tempfile
        from io import BytesIO

        with tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent)) as d:
            tmp = os.path.join(d, "exists.mp3")
            with open(tmp, "wb") as f:
                f.write(b"x")
            data = save_serato_crate(
                [tmp, "/missing/track.mp3"],
                "t",
                "/",
                existing_files_only=True,
            )
            paths: list[str] = []

            def walk(payload: bytes) -> None:
                fp = BytesIO(payload)
                while True:
                    header = fp.read(8)
                    if len(header) < 8:
                        break
                    name = header[:4].decode("ascii", "replace")
                    length = struct.unpack(">I", header[4:8])[0]
                    payload = fp.read(length)
                    if name == "ptrk":
                        paths.append(payload.decode("utf-16-be").rstrip("\x00"))
                    elif name == "otrk":
                        walk(payload)

            walk(data)
            self.assertEqual(len(paths), 1)
            self.assertIn("Users/", paths[0])


class TestSeratoTidalExport(unittest.TestCase):
    def test_tidal_in_crate(self):
        import struct
        from io import BytesIO

        from serato_parser import save_serato_crate

        data = save_serato_crate(
            ["netsearch://td999"],
            "t",
            "/",
            existing_files_only=True,
        )
        paths: list[str] = []

        def walk(payload: bytes) -> None:
            fp = BytesIO(payload)
            while True:
                header = fp.read(8)
                if len(header) < 8:
                    break
                name = header[:4].decode("ascii", "replace")
                length = struct.unpack(">I", header[4:8])[0]
                payload = fp.read(length)
                if name == "ptrk":
                    paths.append(payload.decode("utf-16-be").rstrip("\x00"))
                elif name == "otrk":
                    walk(payload)

        walk(data)
        self.assertEqual(paths, [])  # streaming nie idzie do .crate

    def test_vdj_to_serato_path(self):
        from vdj_streaming import vdj_to_serato_tidal_path

        self.assertEqual(
            vdj_to_serato_tidal_path("netsearch://td12345"),
            "streaming://tidal/12345",
        )
        self.assertEqual(vdj_to_serato_tidal_path("td99"), "streaming://tidal/99")


class TestSeratoOfflineSubstitutes(unittest.TestCase):
    def test_tidal_prefers_local_mp3(self):
        import struct
        import tempfile
        from io import BytesIO

        from serato_offline import build_serato_offline_substitutes
        from serato_parser import save_serato_crate

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(b"\x00" * 64)
            local_path = tmp.name

        try:
            songs = [
                {
                    "FilePath": "netsearch://td999",
                    "Tags.Author": "Artist A",
                    "Tags.Title": "Song One",
                    "Infos.SongLength": "180.0",
                },
                {
                    "FilePath": local_path,
                    "Link.NetSearch": "td999",
                    "Tags.Author": "Artist A",
                    "Tags.Title": "Song One",
                    "Infos.SongLength": "180.0",
                },
            ]
            subs, stats = build_serato_offline_substitutes(songs)
            self.assertEqual(stats["tidal_link_local"], 1)
            data = save_serato_crate(
                ["netsearch://td999"],
                "t",
                "/",
                path_substitutes=subs,
                existing_files_only=True,
            )
            paths: list[str] = []

            def walk(payload: bytes) -> None:
                fp = BytesIO(payload)
                while True:
                    header = fp.read(8)
                    if len(header) < 8:
                        break
                    name = header[:4].decode("ascii", "replace")
                    length = struct.unpack(">I", header[4:8])[0]
                    payload = fp.read(length)
                    if name == "ptrk":
                        paths.append(payload.decode("utf-16-be").rstrip("\x00"))
                    elif name == "otrk":
                        walk(payload)

            walk(data)
            self.assertTrue(paths[0].endswith(".mp3"))
            self.assertNotIn("tidal:", paths[0])
        finally:
            Path(local_path).unlink(missing_ok=True)

    def test_vdjcache_rejected_without_substitute(self):
        from serato_parser import resolve_serato_export_path

        self.assertIsNone(
            resolve_serato_export_path(
                "/Users/test/Library/Application Support/VirtualDJ/Cache/x.vdjcache"
            )
        )

    def test_merge_prefers_njr_over_tidal_streaming(self):
        import tempfile
        from unittest.mock import patch

        from serato_parser import merge_vdj_tracks_into_serato_database, save_serato_database_v2

        test_dir = Path(__file__).resolve().parent / ".test_merge_data"
        test_dir.mkdir(exist_ok=True)
        local_path = str(test_dir / "Skaner - Nadzieja.m4a")
        Path(local_path).write_bytes(b"\x00" * 64)

        try:
            serato_dir = Path(tempfile.mkdtemp())
            (serato_dir / "database V2").write_bytes(save_serato_database_v2([]))
            songs = [
                {
                    "FilePath": "netsearch://td27558345",
                    "Tags.Author": "Skaner",
                    "Tags.Title": "Nadzieja",
                    "Tags.Stars": "3",
                    "Tags.Bpm": "73.4",
                    "Tags.Key": "6A",
                }
            ]
            subs = {"netsearch://td27558345": local_path}
            with patch("tidal_download.manifest_tracks", return_value={}):
                stats = merge_vdj_tracks_into_serato_database(
                    songs,
                    serato_dir,
                    dry_run=False,
                    path_substitutes=subs,
                )
            self.assertEqual(stats["added"], 1)
            self.assertEqual(stats["added_local"], 1)
            self.assertEqual(stats["added_streaming"], 0)
            db = (serato_dir / "database V2").read_bytes()
            self.assertIn("Nadzieja".encode("utf-16-be"), db)
            self.assertNotIn(b"tidal:tracks:27558345", db)
            rel = local_path.lstrip("/")
            if rel.startswith("Users/"):
                self.assertIn(rel.encode("utf-16-be"), db)
        finally:
            Path(local_path).unlink(missing_ok=True)
            test_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
