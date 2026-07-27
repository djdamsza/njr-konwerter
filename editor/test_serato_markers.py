"""Testy Serato Markers2 (hot cues → pliki audio)."""
from __future__ import annotations

import base64
import struct
import tempfile
import unittest
from pathlib import Path

from mutagen.id3 import GEOB, ID3, TIT2

from serato_markers import (
    encode_markers2_id3,
    parse_markers2_id3,
    serato_cue_index,
    write_serato_markers2_to_file,
)
from unified_model import CuePoint, LoopPoint, Track


class TestSeratoCueIndex(unittest.TestCase):
    def test_vdj_1_based(self):
        self.assertEqual(serato_cue_index(1), 0)
        self.assertEqual(serato_cue_index(8), 7)

    def test_legacy_0_based(self):
        # Num 0 = legacy slot 0; Num 1–8 traktowane jako VDJ 1-based
        self.assertEqual(serato_cue_index(0), 0)
        self.assertEqual(serato_cue_index(7), 6)  # VDJ cue 7 → slot 6

    def test_out_of_range(self):
        self.assertIsNone(serato_cue_index(9))
        self.assertIsNone(serato_cue_index(-1))


class TestMarkers2EncodeParse(unittest.TestCase):
    def test_roundtrip_cues(self):
        cues = [
            CuePoint(name="Intro", pos=12.5, num=1, color=0xFFCC0000),
            CuePoint(name="Drop", pos=64.0, num=2),
            CuePoint(name="Extra", pos=1.0, num=99),  # remap na wolny slot
        ]
        blob = encode_markers2_id3(cues)
        self.assertGreaterEqual(len(blob), 470)
        self.assertEqual(blob[:2], b"\x01\x01")
        parsed = parse_markers2_id3(blob)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["index"], 0)
        self.assertEqual(parsed[0]["position_ms"], 12500)
        self.assertEqual(parsed[0]["name"], "Intro")
        self.assertEqual(parsed[1]["index"], 1)
        self.assertEqual(parsed[1]["position_ms"], 64000)
        self.assertEqual(parsed[1]["name"], "Drop")
        self.assertEqual(parsed[2]["index"], 2)
        self.assertEqual(parsed[2]["position_ms"], 1000)
        self.assertEqual(parsed[2]["name"], "Extra")

    def test_duplicate_slot_keeps_first(self):
        cues = [
            CuePoint(name="A", pos=1.0, num=1),
            CuePoint(name="B", pos=2.0, num=1),
        ]
        parsed = parse_markers2_id3(encode_markers2_id3(cues))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["name"], "A")


class TestWriteMarkers2Mp3(unittest.TestCase):
    def test_write_to_id3_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "track.mp3"
            tags = ID3()
            tags.add(TIT2(encoding=3, text="Test"))
            tags.save(str(path))

            track = Track(
                path=str(path),
                title="Test",
                cue_points=[
                    CuePoint(name="Cue 1", pos=5.25, num=1),
                    CuePoint(name="Cue 3", pos=30.0, num=3),
                ],
            )
            ok, msg = write_serato_markers2_to_file(track, skip_unchanged=False)
            self.assertTrue(ok, msg)

            loaded = ID3(str(path))
            geob = loaded.get("GEOB:Serato Markers2")
            self.assertIsInstance(geob, GEOB)
            parsed = parse_markers2_id3(geob.data)
            self.assertEqual(len(parsed), 2)
            self.assertEqual(parsed[0]["position_ms"], 5250)
            self.assertEqual(parsed[1]["index"], 2)

            # ponowny zapis bez zmian → UNCHANGED
            ok2, msg2 = write_serato_markers2_to_file(track, skip_unchanged=True)
            self.assertFalse(ok2)
            self.assertEqual(msg2, "UNCHANGED")

            # zmiana pozycji → zapis
            track.cue_points[0] = CuePoint(name="Cue 1", pos=6.0, num=1)
            ok3, msg3 = write_serato_markers2_to_file(track, skip_unchanged=True)
            self.assertTrue(ok3, msg3)

            # Markers_ też zapisane (MP3)
            loaded2 = ID3(str(path))
            self.assertIsNotNone(loaded2.get("GEOB:Serato Markers_"))

    def test_no_markers_skipped(self):
        track = Track(path="/tmp/x.mp3", cue_points=[], loops=[])
        ok, msg = write_serato_markers2_to_file(track)
        self.assertFalse(ok)
        self.assertEqual(msg, "NO_MARKERS")

    def test_loops_only_written(self):
        try:
            from mutagen.id3 import ID3
        except ImportError:
            self.skipTest("mutagen not installed")
        from serato_markers import read_loops_from_file

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "loop.mp3"
            ID3().save(str(path))
            track = Track(
                path=str(path),
                loops=[
                    LoopPoint(slot=1, label="Drop", position_ms=60000, end_ms=90000)
                ],
            )
            ok, msg = write_serato_markers2_to_file(track, skip_unchanged=False)
            self.assertTrue(ok, msg)
            parsed = read_loops_from_file(str(path))
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0].slot, 1)
            self.assertEqual(parsed[0].position_ms, 60000)


class TestMarkersUnderscoreAndM4a(unittest.TestCase):
    def test_encode_markers_underscore_has_5_cues(self):
        from serato_markers import encode_serato_markers_underscore

        cues = [CuePoint(name="A", pos=1.5, num=1), CuePoint(name="B", pos=10.0, num=3)]
        blob = encode_serato_markers_underscore(cues)
        self.assertEqual(blob[:2], b"\x02\x05")
        self.assertEqual(struct.unpack(">I", blob[2:6])[0], 14)
        self.assertEqual(len(blob), 6 + 14 * 22 + 4)

    def test_encode_markers_mp4_layout(self):
        from serato_markers import encode_serato_markers_mp4

        cues = [CuePoint(name="A", pos=0.312, num=1)]
        blob = encode_serato_markers_mp4(cues)
        self.assertEqual(blob[:2], b"\x02\x05")
        self.assertEqual(struct.unpack(">I", blob[2:6])[0], 14)
        # 2 + 4 + 14*19 + 1 + 3
        self.assertEqual(len(blob), 6 + 14 * 19 + 4)
        # first cue: pos 312 as plain u32
        self.assertEqual(struct.unpack(">I", blob[6:10])[0], 312)
        self.assertEqual(blob[10:14], b"\xFF\xFF\xFF\xFF")
        self.assertEqual(blob[14:20], b"\x00\xFF\xFF\xFF\xFF\x00")
        # unset cue slot type Invalid=0 at entry index 1
        e1 = 6 + 19
        self.assertEqual(blob[e1 : e1 + 4], b"\xFF\xFF\xFF\xFF")
        self.assertEqual(blob[e1 + 17], 0)  # type Invalid

    def test_write_m4a_writes_both_atoms(self):
        import shutil

        from mutagen.mp4 import MP4
        from serato_markers import (
            encode_serato_markers_underscore,
            read_markers2_cues_from_file,
        )

        src = Path.home() / "Music/NJR-Tidal-Serato/Skaner/Skaner - Nadzieja.m4a"
        if not src.is_file():
            self.skipTest("brak przykładowego M4A NJR")

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "track.m4a"
            shutil.copy2(src, path)

            track = Track(
                path=str(path),
                title="Test",
                cue_points=[
                    CuePoint(name="Cue 1", pos=5.0, num=1),
                    CuePoint(name="Cue 2", pos=20.0, num=2),
                ],
            )
            ok, msg = write_serato_markers2_to_file(track, skip_unchanged=False)
            self.assertTrue(ok, msg)

            loaded = MP4(str(path))
            self.assertIn("----:com.serato.dj:markers", loaded)
            self.assertIn("----:com.serato.dj:markersv2", loaded)

            raw = loaded["----:com.serato.dj:markers"][0]
            text = raw.decode("ascii").replace("\n", "")
            pad = "=" * (-len(text) % 4)
            blob = base64.b64decode(text + pad)
            self.assertTrue(
                blob.startswith(b"application/octet-stream\x00\x00Serato Markers_\x00")
            )
            payload = blob.split(b"Serato Markers_\x00", 1)[1]
            self.assertEqual(payload[:2], b"\x02\x05")
            from serato_markers import encode_serato_markers_mp4

            self.assertEqual(
                len(payload), len(encode_serato_markers_mp4(track.cue_points))
            )
            # MP4: pozycja jako zwykłe u32, nie serato32
            self.assertEqual(struct.unpack(">I", payload[6:10])[0], 5000)

            parsed = read_markers2_cues_from_file(str(path))
            self.assertEqual(len(parsed), 2)
            self.assertEqual(parsed[0]["position_ms"], 5000)

            del loaded["----:com.serato.dj:markers"]
            loaded.save()
            ok2, msg2 = write_serato_markers2_to_file(track, skip_unchanged=True)
            self.assertTrue(ok2, msg2)


if __name__ == "__main__":
    unittest.main()
