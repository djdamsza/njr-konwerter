#!/usr/bin/env python3
"""
Testy round-trip: VDJ (słowniki _songs) → format pośredni (Unified) → eksport → import → z powrotem VDJ.

Uruchomienie (z katalogu tools/vdj-database-editor; na Macu: python3 zamiast python):
  python3 -m unittest test_roundtrip_formats -v

Opcjonalnie z prawdziwym backupem ZIP (jak test_api.py):
  NJR_TEST_BACKUP=/ścieżka/do/backup.zip python3 -m unittest test_roundtrip_formats.TestRoundtripWithRealBackup -v

Na prawdziwych bibliotekach test dopuszcza drobne różnice: SongLength ±2 s, &amp; w polach tekstowych,
pusty Key lub BPM z jednej strony, BPM porównywany tylko gdy obie strony mają wartość > 0.
"""
from __future__ import annotations

import html
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Import modułów projektu
sys.path.insert(0, str(Path(__file__).resolve().parent))

from djxml_generator import generate_djxml
from djxml_parser import load_djxml
from rb_generator import generate_rb_xml
from rb_parser import load_rb_xml
from unified_model import Playlist, Track, UnifiedDatabase
from vdj_adapter import unified_to_vdj_songs, vdj_songs_to_unified
from vdj_parser import load_database, save_database
from vdjfolder import normalize_path


def _synthetic_songs(tmp: Path) -> list[dict]:
    """Minimalne wpisy VDJ (jak w database.xml) – bez prawdziwych plików audio."""
    f1 = tmp / "track_one.mp3"
    f2 = tmp / "drugi utwór.flac"
    f1.write_bytes(b"")
    f2.write_bytes(b"")
    p1, p2 = str(f1), str(f2)

    # BPM w VDJ: wartość 0.5 → 60/0.5 = 120 BPM
    song_a = {
        "FilePath": p1,
        "FileSize": "0",
        "Flag": "",
        "Tags.Author": "DJ Test",
        "Tags.Title": "Roundtrip Anthem",
        "Tags.Album": "Test LP",
        "Tags.Genre": "Electro",
        "Tags.User1": "#afterparty #warmup",
        "Tags.User2": "",
        "Tags.Bpm": "0.5",
        "Tags.Key": "8A",
        "Tags.Year": "2024",
        "Infos.SongLength": "195",
        "Infos.PlayCount": "42",
        "Tags.Stars": "3",
        "_children_xml": [
            '<Comment>notatka testowa</Comment>',
            '<Poi Pos="0.000000" Type="beatgrid" Bpm="120.00" />',
            '<Poi Name="Intro" Pos="12.500000" Num="1" Type="cue" />',
        ],
    }
    song_b = {
        "FilePath": p2,
        "FileSize": "0",
        "Flag": "",
        "Tags.Author": "Inny Artysta",
        "Tags.Title": "Drugi kawałek",
        "Tags.Album": "",
        "Tags.Genre": "",
        "Tags.User1": "#single-tag",
        "Tags.User2": "",
        "Tags.Bpm": "",
        "Tags.Key": "",
        "Tags.Year": "0",
        "Infos.SongLength": "",
        "Infos.PlayCount": "",
        "Tags.Stars": "",
        "_children_xml": [],
    }
    return [song_a, song_b]


def _song_key(s: dict) -> str:
    return normalize_path(s.get("FilePath") or "")


def _vdj_meta_text_equal(a: str, b: str) -> bool:
    """Author/Title/… – po round-trip XML & może być zapisane jako &amp; w atrybucie."""
    return html.unescape((a or "").strip()) == html.unescape((b or "").strip())


def _vdj_key_compatible(before: str, after: str) -> bool:
    """
    Key – w rzeczywistej bazie często puste w XML VDJ, a po DJXML/unified pojawia się
    z innego pola (MusicalKey) lub znika; pełna zgodność tylko gdy obie strony niepuste.
    """
    b = html.unescape((before or "").strip())
    a = html.unescape((after or "").strip())
    if not b and not a:
        return True
    if not b or not a:
        return True
    return b == a


def _numeric_infos_equal(a: str, b: str) -> bool:
    """Porównanie Infos (np. PlayCount) – 42 vs 42.0 po round-trip XML."""
    sa = (a or "").strip()
    sb = (b or "").strip()
    if sa == sb:
        return True
    if not sa and not sb:
        return True
    try:
        fa, fb = float(sa), float(sb)
        return abs(fa - fb) < 1e-6
    except ValueError:
        return False


def _song_length_roundtrip_equal(a: str, b: str, max_diff_sec: float = 2.0) -> bool:
    """
    Długość utworu w sekundach – VDJ często ma int w Infos.SongLength (229),
    a po DJXML/unified bywa float z metadanych pliku (229.70). Identyczne
    stringi lub różnica ≤ max_diff_sec uznajemy za OK.
    """
    if _numeric_infos_equal(a, b):
        return True
    sa = (a or "").strip()
    sb = (b or "").strip()
    if not sa and not sb:
        return True
    try:
        fa, fb = float(sa), float(sb)
        return abs(fa - fb) <= max_diff_sec
    except ValueError:
        return False


def _bpm_from_vdj(s: dict) -> float:
    raw = (s.get("Tags.Bpm") or "").strip()
    if not raw:
        return 0.0
    try:
        val = float(raw)
        if 0.2 <= val <= 2.0:
            return 60.0 / val
        if 20 <= val <= 300:
            return val
    except ValueError:
        pass
    return 0.0


def _comment_from_children(song: dict) -> str:
    for xml in song.get("_children_xml") or []:
        if "<Comment>" in xml and "</Comment>" in xml:
            start = xml.index("<Comment>") + len("<Comment>")
            end = xml.index("</Comment>", start)
            return xml[start:end].strip()
    return ""


def _vdj_tokens(song: dict) -> frozenset[str]:
    """
    Zbiór „znaczników” z VDJ: Genre + User1 + User2 + tekst <Comment>.
    Używane przy round-trip przez DJXML (format może przenieść tagi między polami).
    """
    from vdj_parser import parse_tags_value

    chunks: list[str] = []
    for key in ("Tags.Genre", "Tags.User1", "Tags.User2"):
        chunks.extend(parse_tags_value(song.get(key) or ""))
    c = _comment_from_children(song).strip()
    if c:
        if "#" in c:
            chunks.extend(parse_tags_value(c))
        else:
            chunks.extend(w for w in c.split() if w.strip())
    return frozenset(chunks)


def _assert_vdj_roundtrip_close(
    self,
    before: list[dict],
    after: list[dict],
    label: str,
    *,
    check_comments_and_usertags: bool = True,
) -> None:
    """
    check_comments_and_usertags: False dla VDJ→Rekordbox XML→VDJ (RB nie zachowuje <Comment> w tej ścieżce).
    """
    self.assertEqual(len(before), len(after), f"{label}: liczba utworów")
    mb = {_song_key(s): s for s in before}
    ma = {_song_key(s): s for s in after}
    self.assertEqual(set(mb.keys()), set(ma.keys()), f"{label}: zestaw ścieżek")
    for k in sorted(mb.keys()):
        sb, sa = mb[k], ma[k]
        self.assertEqual(
            normalize_path(sb.get("FilePath", "")),
            normalize_path(sa.get("FilePath", "")),
            f"{label}: FilePath {k}",
        )
        for field in ("Tags.Author", "Tags.Title", "Tags.Album", "Tags.Genre"):
            self.assertTrue(
                _vdj_meta_text_equal(sb.get(field) or "", sa.get(field) or ""),
                f"{label}: {field} dla {k!r}: {sb.get(field)!r} vs {sa.get(field)!r}",
            )
        self.assertTrue(
            _vdj_key_compatible(sb.get("Tags.Key") or "", sa.get("Tags.Key") or ""),
            f"{label}: Tags.Key dla {k!r}: {sb.get('Tags.Key')!r} vs {sa.get('Tags.Key')!r}",
        )
        bpm_b, bpm_a = _bpm_from_vdj(sb), _bpm_from_vdj(sa)
        # Oba > 0: muszą być zgodne. Gdy któryś 0 (cache/streaming, brak Tags.Bpm) – nie wymagamy.
        if bpm_b > 0 and bpm_a > 0:
            self.assertAlmostEqual(bpm_b, bpm_a, delta=0.05, msg=f"{label}: BPM dla {k}")
        sl_b = sb.get("Infos.SongLength") or ""
        sl_a = sa.get("Infos.SongLength") or ""
        self.assertTrue(
            _song_length_roundtrip_equal(sl_b, sl_a),
            f"{label}: SongLength dla {k!r}: {sl_b!r} vs {sl_a!r}",
        )
        pc_b = sb.get("Infos.PlayCount") or ""
        pc_a = sa.get("Infos.PlayCount") or ""
        self.assertTrue(
            _numeric_infos_equal(pc_b, pc_a),
            f"{label}: PlayCount dla {k!r}: {pc_b!r} vs {pc_a!r}",
        )
        if not check_comments_and_usertags:
            continue
        self.assertEqual(
            _vdj_tokens(sb),
            _vdj_tokens(sa),
            f"{label}: ten sam zbiór Genre/User/tagów/Comment dla {k}",
        )


class TestRoundtripDJXML(unittest.TestCase):
    def test_vdj_unified_djxml_unified_vdj(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            songs = _synthetic_songs(tmp_path)
            u1 = vdj_songs_to_unified(songs)
            self.assertEqual(len(u1.tracks), 2)

            xml_bytes = generate_djxml(u1)
            self.assertIn(b"<DJXML>", xml_bytes)
            u2 = load_djxml(xml_bytes)
            self.assertEqual(len(u2.tracks), 2, "DJXML: liczba utworów po imporcie")

            songs2 = unified_to_vdj_songs(u2)
            _assert_vdj_roundtrip_close(self, songs, songs2, "VDJ→DJXML→VDJ")

    def test_vdj_djxml_with_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            songs = _synthetic_songs(tmp_path)
            u = vdj_songs_to_unified(songs)
            p1 = normalize_path(songs[0]["FilePath"])
            p2 = normalize_path(songs[1]["FilePath"])
            u.playlists = [
                Playlist(name="Main Set", track_ids=[songs[0]["FilePath"], songs[1]["FilePath"]], is_folder=False)
            ]
            u2 = load_djxml(generate_djxml(u))
            self.assertEqual(len(u2.playlists), 1)
            self.assertEqual(u2.playlists[0].name, "Main Set")
            ids = [normalize_path(x) for x in u2.playlists[0].track_ids]
            self.assertEqual(ids, [p1, p2])


class TestRoundtripRBXML(unittest.TestCase):
    def test_vdj_rbxml_vdj(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            songs = _synthetic_songs(tmp_path)
            u1 = vdj_songs_to_unified(songs)
            rb_bytes = generate_rb_xml(u1)
            self.assertIn(b"COLLECTION", rb_bytes)

            rb_file = tmp_path / "export_rb.xml"
            rb_file.write_bytes(rb_bytes)
            u2 = load_rb_xml(rb_file)
            self.assertEqual(len(u2.tracks), 2, "RB XML: liczba utworów")

            songs2 = unified_to_vdj_songs(u2)
            _assert_vdj_roundtrip_close(
                self,
                songs,
                songs2,
                "VDJ→RB XML→VDJ",
                check_comments_and_usertags=False,
            )


class TestRoundtripVDJDatabaseFile(unittest.TestCase):
    """Zapis i odczyt database.xml + round-trip przez DJXML (spójność parsera VDJ)."""

    def test_save_load_djxml_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            songs = _synthetic_songs(tmp_path)
            db_path = tmp_path / "database.xml"
            save_database(db_path, songs, "8.5")
            loaded, ver = load_database(db_path)
            self.assertEqual(ver, "8.5")
            self.assertEqual(len(loaded), 2)

            u1 = vdj_songs_to_unified(loaded)
            u2 = load_djxml(generate_djxml(u1))
            songs2 = unified_to_vdj_songs(u2)
            _assert_vdj_roundtrip_close(self, songs, songs2, "XML zapis→odczyt→DJXML→VDJ")


def _find_backup() -> str | None:
    candidates = []
    env = os.environ.get("NJR_TEST_BACKUP", "").strip()
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve().parent
    candidates.extend(
        [
            here.parent.parent / "virtualdj" / "2026-03-01 20-23 Database Backup.zip",
            here / "test-backup-vdj.zip",
        ]
    )
    for p in candidates:
        if p.exists():
            return str(p)
    return None


@unittest.skipUnless(_find_backup(), "Brak backupu (NJR_TEST_BACKUP lub test-backup-vdj.zip)")
class TestRoundtripWithRealBackup(unittest.TestCase):
    """Wolniejszy test: wczytanie prawdziwego ZIP przez API nie jest tu używane — tylko plik XML z ZIP jeśli da się wyciągnąć."""

    def test_zip_contains_database_then_djxml_roundtrip(self) -> None:
        import zipfile

        backup = _find_backup()
        assert backup
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(backup, "r") as zf:
                names = zf.namelist()
                xml_names = [n for n in names if n.lower().endswith("database.xml")]
                self.assertTrue(xml_names, "ZIP musi zawierać database.xml")
                member = xml_names[0]
                zf.extract(member, tmp_path)
            extracted = tmp_path / member
            if not extracted.exists():
                extracted = next(tmp_path.rglob("database.xml"))
            songs, ver = load_database(extracted)
            self.assertTrue(songs, "Baza z ZIP jest pusta")
            self.assertTrue(ver, "Brak wersji bazy")

            # Nie modyfikujemy całej bazy w pamięci — tylko pierwsze 25 utworów (szybciej, mniej RAM)
            sample = songs[:25]
            u1 = vdj_songs_to_unified(sample)
            u2 = load_djxml(generate_djxml(u1))
            songs2 = unified_to_vdj_songs(u2)
            _assert_vdj_roundtrip_close(self, sample, songs2, f"Backup ZIP ({len(sample)} utworów) DJXML")


if __name__ == "__main__":
    unittest.main()
