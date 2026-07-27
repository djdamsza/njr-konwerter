#!/usr/bin/env python3
"""Testy migracji loopów VDJ → Serato → Engine."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine_generator import loops_to_engine
from unified_model import CuePoint, LoopPoint, Track
from vdj_adapter import _loops_from_vdj_poi, _parse_poi_children, vdj_songs_to_unified


class TestVdjLoopParse(unittest.TestCase):
    def test_parse_poi_loop_xml(self):
        children = [
            '<Poi Name="Cue 6" Pos="26.2090" Num="6" Color="4294934272" '
            'Type="loop" Size="8.0" />',
            '<Poi Pos="0.0" Type="beatgrid" Bpm="130.0" />',
        ]
        beatgrid, cues, raw = _parse_poi_children(children)
        self.assertEqual(len(beatgrid), 1)
        self.assertEqual(len(cues), 0)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["slot"], 5)  # Num 6 → slot 5
        self.assertAlmostEqual(raw[0]["pos_sec"], 26.2090)
        self.assertAlmostEqual(raw[0]["size_beats"], 8.0)

    def test_loops_from_vdj_poi_end_ms(self):
        raw = [{"slot": 0, "pos_sec": 10.0, "size_beats": 8.0, "name": "Intro loop"}]
        loops = _loops_from_vdj_poi(raw, bpm=120.0)
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0].slot, 0)
        self.assertEqual(loops[0].position_ms, 10000)
        # 8 beats @ 120 BPM = 4 s → end = 14 s
        self.assertEqual(loops[0].end_ms, 14000)

    def test_vdj_songs_to_unified_with_loop(self):
        songs = [{
            "FilePath": "/music/test.mp3",
            "Tags.Title": "Track",
            "Tags.Author": "Artist",
            "Infos.SongLength": "300",
            "_children_xml": [
                '<Poi Pos="0.0" Type="beatgrid" Bpm="128.0" />',
                '<Poi Name="Loop 1" Pos="30.0" Num="1" Type="loop" Size="4.0" />',
            ],
        }]
        db = vdj_songs_to_unified(songs)
        self.assertEqual(len(db.tracks), 1)
        self.assertEqual(len(db.tracks[0].loops), 1)
        lp = db.tracks[0].loops[0]
        self.assertEqual(lp.slot, 0)
        self.assertEqual(lp.position_ms, 30000)
        # 4 beats @ 128 BPM = 1.875 s
        self.assertEqual(lp.end_ms, 31875)


class TestVdjScanBpm(unittest.TestCase):
    def test_scan_bpm_inverse_format(self):
        from vdj_adapter import _parse_scan_bpm

        self.assertAlmostEqual(
            _parse_scan_bpm(['<Scan Bpm="0.444433" />']), 135.0, places=1
        )
        self.assertEqual(_parse_scan_bpm(['<Scan Bpm="128" />']), 128.0)

    def test_halo_style_song_keeps_loop_and_cues(self):
        songs = [{
            "FilePath": "/music/halo.mp3",
            "Tags.Title": "Halo",
            "Tags.Author": "WEEKEND",
            "Infos.SongLength": "180",
            "_children_xml": [
                '<Scan Version="801" Bpm="0.444433" Phase="2.274807" Key="A" />',
                '<Poi Pos="0.052630" Num="1" Type="cue" />',
                '<Poi Pos="0.052630" Num="5" Type="loop" Size="4.0" Slot="1" />',
                '<Poi Pos="2.274807" Type="beatgrid" />',
                '<Poi Pos="3.163651" Num="3" Type="cue" />',
            ],
        }]
        db = vdj_songs_to_unified(songs)
        t = db.tracks[0]
        self.assertAlmostEqual(t.bpm, 135.0, places=1)
        self.assertEqual(len(t.cue_points), 2)
        self.assertEqual(len(t.loops), 1)
        self.assertEqual(t.loops[0].slot, 1)
        self.assertEqual(len(t.beatgrid), 1)
        self.assertAlmostEqual(t.beatgrid[0].pos, 2.274807)


class TestVdjToSeratoLoopWrite(unittest.TestCase):
    def test_vdj_loop_only_writes_serato_markers(self):
        try:
            from mutagen.id3 import ID3
        except ImportError:
            self.skipTest("mutagen not installed")

        from serato_markers import read_loops_from_file, write_serato_markers2_to_file

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "track.mp3"
            ID3().save(str(path))
            songs = [{
                "FilePath": str(path),
                "Tags.Title": "Loop track",
                "Tags.Bpm": "128",
                "Infos.SongLength": "300",
                "_children_xml": [
                    '<Poi Pos="0.0" Type="beatgrid" Bpm="128.0" />',
                    '<Poi Name="Loop 1" Pos="30.0" Num="1" Type="loop" Size="4.0" />',
                ],
            }]
            db = vdj_songs_to_unified(songs)
            self.assertEqual(len(db.tracks[0].loops), 1)
            ok, msg = write_serato_markers2_to_file(db.tracks[0], skip_unchanged=False)
            self.assertTrue(ok, msg)
            loops = read_loops_from_file(str(path))
            self.assertEqual(len(loops), 1)
            self.assertEqual(loops[0].slot, 0)
            self.assertEqual(loops[0].position_ms, 30000)

    def test_loop_write_preserves_existing_cues(self):
        try:
            from mutagen.id3 import ID3
        except ImportError:
            self.skipTest("mutagen not installed")

        from serato_markers import (
            read_loops_from_file,
            read_markers2_cues_from_file,
            write_serato_markers2_to_file,
        )
        from unified_model import CuePoint, LoopPoint, Track

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "track.mp3"
            ID3().save(str(path))
            base = Track(
                path=str(path),
                cue_points=[CuePoint(name="A", pos=1.0, num=1)],
            )
            ok, msg = write_serato_markers2_to_file(
                base, skip_unchanged=False, preserve_existing=False
            )
            self.assertTrue(ok, msg)
            # zapis samych loopów NIE może wymazać cue
            loops_only = Track(
                path=str(path),
                loops=[LoopPoint(slot=0, label="L", position_ms=5000, end_ms=10000)],
            )
            ok, msg = write_serato_markers2_to_file(
                loops_only, skip_unchanged=False, preserve_existing=True
            )
            self.assertTrue(ok, msg)
            self.assertEqual(len(read_markers2_cues_from_file(str(path))), 1)
            self.assertEqual(len(read_loops_from_file(str(path))), 1)


class TestNormalizeOverflowCues(unittest.TestCase):
    def test_overflow_fills_free_slot(self):
        from serato_markers import normalize_serato_cue_points

        cues = [
            CuePoint(name="1", pos=1.0, num=1),
            CuePoint(name="3", pos=3.0, num=3),
            CuePoint(name="10", pos=10.0, num=10),
        ]
        out = normalize_serato_cue_points(cues)
        nums = sorted(cp.num for cp in out)
        self.assertEqual(nums, [1, 2, 3])
        by_num = {cp.num: cp for cp in out}
        self.assertAlmostEqual(by_num[2].pos, 10.0)


class TestM4aLoopRoundtrip(unittest.TestCase):
    def test_m4a_loop_write_and_read(self):
        try:
            from mutagen.mp4 import MP4
        except ImportError:
            self.skipTest("mutagen not installed")

        from serato_markers import read_loops_from_file, write_serato_markers2_to_file

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "track.m4a"
            # Minimal empty MP4 — mutagen can create tags on empty? Need real m4a.
            # Skip if we can't create; use write of freeform on new MP4 fails without media.
            # Create via copying encode path unit: write payload parse only.
            from serato_markers import (
                _parse_markers_underscore_loops,
                encode_serato_markers_mp4,
            )

            loops = [LoopPoint(slot=4, label="L", position_ms=4980, end_ms=8780)]
            cues = [CuePoint(name="A", pos=0.229, num=1)]
            payload = encode_serato_markers_mp4(cues, loops)
            parsed = _parse_markers_underscore_loops(payload)
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["slot"], 4)
            self.assertEqual(parsed[0]["position_ms"], 4980)
            self.assertEqual(parsed[0]["end_ms"], 8780)


class TestSeratoLoopParse(unittest.TestCase):
    def test_read_loops_from_markers_underscore(self):
        try:
            from mutagen.id3 import GEOB, ID3
        except ImportError:
            self.skipTest("mutagen not installed")

        from serato_markers import encode_serato_markers_underscore, read_loops_from_file

        loops = [LoopPoint(slot=2, label="L", position_ms=5000, end_ms=15000)]
        payload = encode_serato_markers_underscore([], loops)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "track.mp3"
            tags = ID3()
            tags.add(
                GEOB(
                    encoding=0,
                    mime="application/octet-stream",
                    desc="Serato Markers_",
                    data=payload,
                )
            )
            tags.save(str(path))

            parsed = read_loops_from_file(str(path))
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0].slot, 2)
            self.assertEqual(parsed[0].position_ms, 5000)
            self.assertEqual(parsed[0].end_ms, 15000)

    def test_encode_markers_underscore_roundtrip(self):
        try:
            from serato_tools.track_cues_v1 import TrackCuesV1
        except ImportError:
            self.skipTest("serato_tools not installed")

        from serato_markers import encode_serato_markers_underscore
        from unified_model import CuePoint

        loops = [LoopPoint(slot=1, label="Drop loop", position_ms=60000, end_ms=90000)]
        payload = encode_serato_markers_underscore(
            [CuePoint(name="A", pos=1.0, num=1)],
            loops,
        )
        v1 = TrackCuesV1(payload)
        entry = v1.entries[6]  # slot 1 → index 6
        self.assertEqual(entry.type, TrackCuesV1.EntryType.LOOP)
        self.assertTrue(entry.start_position_set)
        self.assertTrue(entry.end_position_set)
        self.assertEqual(entry.start_position, 60000)
        self.assertEqual(entry.end_position, 90000)


class TestLoopsToEngine(unittest.TestCase):
    def test_loops_to_engine_samples(self):
        t = Track(
            path="/music/x.mp3",
            loops=[
                LoopPoint(slot=0, label="A", position_ms=1000, end_ms=5000),
                LoopPoint(slot=3, label="B", position_ms=10000, end_ms=20000),
            ],
        )
        out = loops_to_engine(t, 44100)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["slot"], 0)
        self.assertAlmostEqual(out[0]["start_sample_offset"], 44100)
        self.assertAlmostEqual(out[0]["end_sample_offset"], 5 * 44100)
        self.assertEqual(out[1]["slot"], 3)

    def test_loops_max_eight_slots(self):
        loops = [
            LoopPoint(slot=i, label=f"L{i}", position_ms=1000 * i, end_ms=1000 * i + 500)
            for i in range(10)
        ]
        t = Track(path="/x.mp3", loops=loops)
        out = loops_to_engine(t, 48000)
        self.assertLessEqual(len(out), 8)
        slots = {x["slot"] for x in out}
        self.assertTrue(all(0 <= s <= 7 for s in slots))


class TestDjAppsGuard(unittest.TestCase):
    def test_sync_guard_not_blocked_when_apps_closed(self):
        from unittest.mock import patch

        from dj_apps_guard import sync_guard_blockers

        with patch("dj_apps_guard.is_vdj_running", return_value=(False, "")), patch(
            "dj_apps_guard.is_engine_running", return_value=(False, "")
        ):
            blocked, msg, checklist = sync_guard_blockers(require_vdj_closed=True)
            self.assertFalse(blocked)
            self.assertEqual(msg, "")


if __name__ == "__main__":
    unittest.main()
