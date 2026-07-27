"""
VirtualDJ Linked Tracks (filtr „Has Links”) + eksport HTML biblioteki.

„Has Links = 1” w VDJ ≠ element <Link NetSearch=…> w database.xml.
Prawdziwe Linked Tracks są w extra.db (related_tracks + track_data).

Eksport HTML (VirtualDJ Library Export) to wiarygodny snapshot listy z UI —
używamy go do doprecyzowania crate'ów (np. LINKI) gdy track_data jest niepełne.
"""
from __future__ import annotations

import re
import sqlite3
from html import unescape
from pathlib import Path
from typing import Optional

from vdjfolder import normalize_path


def vdj_home() -> Path:
    return Path.home() / "Library" / "Application Support" / "VirtualDJ"


def extra_db_path(home: Optional[Path] = None) -> Path:
    return (home or vdj_home()) / "extra.db"


def parse_vdj_library_html_export(path: str | Path) -> list[dict]:
    """
    Parsuje HTML z VirtualDJ (Library Export) → lista wierszy
    {title, artist, length, bpm, key, rating} w kolejności z tabeli.
    """
    html = Path(path).read_text(encoding="utf-8", errors="replace")
    body = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S | re.I)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body, flags=re.S | re.I)
    out: list[dict] = []
    for row in rows[1:]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S | re.I)
        if len(cells) < 2:
            continue

        def clean(x: str) -> str:
            return unescape(re.sub(r"<[^>]+>", "", x or "")).strip()

        out.append(
            {
                "title": clean(cells[0]),
                "artist": clean(cells[1]),
                "length": clean(cells[2]) if len(cells) > 2 else "",
                "bpm": clean(cells[3]) if len(cells) > 3 else "",
                "key": clean(cells[4]) if len(cells) > 4 else "",
                "rating": clean(cells[5]) if len(cells) > 5 else "",
            }
        )
    return out


def load_linked_track_entries(home: Optional[Path] = None) -> list[dict]:
    """
    Utwory z Linked Tracks (extra.db): ścieżka + artist/title z track_data
    dla sid występujących w related_tracks.
    """
    db = extra_db_path(home)
    if not db.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        sids = {
            r[0]
            for r in con.execute(
                "SELECT sid1 FROM related_tracks UNION SELECT sid2 FROM related_tracks"
            )
        }
        if not sids:
            return []
        out: list[dict] = []
        seen: set[str] = set()
        for sid, file, filesize, artist, title in con.execute(
            "SELECT sid, file, filesize, artist, title FROM track_data"
        ):
            if sid not in sids:
                continue
            fp = normalize_path((file or "").strip())
            if not fp or fp in seen:
                continue
            seen.add(fp)
            out.append(
                {
                    "FilePath": fp,
                    "FileSize": str(filesize or ""),
                    "Tags.Author": (artist or "").strip(),
                    "Tags.Title": (title or "").strip(),
                    "HasLinks": "1",
                }
            )
        return out
    finally:
        con.close()


def linked_track_path_set(home: Optional[Path] = None) -> set[str]:
    return {
        normalize_path(e.get("FilePath") or "")
        for e in load_linked_track_entries(home)
        if e.get("FilePath")
    }


def _norm_meta(s: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFC", (s or "").strip().lower())


def _title_core(title: str) -> str:
    t = _norm_meta(title)
    t = re.sub(r"\s*\([^)]*\)\s*", " ", t)
    t = re.sub(r"\s*\[[^\]]*\]\s*", " ", t)
    return " ".join(t.split())


def _parse_length_sec(text: str) -> Optional[float]:
    m = re.match(r"(\d+):(\d+(?:\.\d+)?)", (text or "").strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + float(m.group(2))


def _filename_search_blob(path: str) -> str:
    """Nazwa pliku bez rozszerzenia, znormalizowana do wyszukiwania."""
    name = Path((path or "").replace("\\", "/")).stem
    return _norm_meta(name.replace("—", "-").replace("–", "-"))


def _significant_words(text: str) -> list[str]:
    stop = {
        "the", "a", "an", "and", "or", "feat", "ft", "vs", "radio", "edit", "mix",
        "extended", "version", "remix", "oficial", "official", "lyrics",
    }
    words = re.findall(r"[a-z0-9ąćęłńóśźżäöü]+", _norm_meta(text))
    return [w for w in words if len(w) >= 3 and w not in stop]


def _song_bpm_display(song: dict) -> float:
    from vdjfolder import _song_bpm

    return _song_bpm(song)


def _song_length_sec(song: dict) -> Optional[float]:
    try:
        val = float(song.get("Infos.SongLength") or 0)
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_rating_stars(text: str) -> Optional[int]:
    raw = (text or "").strip()
    if not raw:
        return None
    stars = raw.count("★") + raw.count("*")
    if stars:
        return stars
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _song_stars(song: dict) -> Optional[int]:
    raw = (song.get("Tags.Stars") or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _keys_match(html_key: str, song_key: str) -> bool:
    from vdjfolder import _camelot_normalize

    hk = (html_key or "").strip()
    sk = (song_key or "").strip()
    if not hk or not sk:
        return False
    a = _camelot_normalize(hk)
    b = _camelot_normalize(sk)
    if a and b and a.upper() == b.upper():
        return True
    return _norm_meta(hk) == _norm_meta(sk)


def _score_html_row_against_song(
    row: dict,
    song: dict,
    *,
    linked_paths: Optional[set[str]] = None,
) -> float:
    """
    Punktacja zgodności wiersza HTML z rekordem VDJ (jak w UI biblioteki).
    Im wyżej, tym pewniejsze 1:1 dopasowanie wersji.
    """
    score = 0.0

    row_title = _norm_meta(row.get("title") or "")
    song_title = _norm_meta(song.get("Tags.Title") or "")
    if row_title and song_title:
        if row_title == song_title:
            score += 15
        elif _title_core(row_title) == _title_core(song_title):
            score += 5
        else:
            return 0.0

    row_artist = _norm_meta(row.get("artist") or "")
    song_artist = _norm_meta(song.get("Tags.Author") or song.get("Tags.Artist") or "")
    if row_artist and song_artist:
        if row_artist == song_artist or row_artist in song_artist or song_artist in row_artist:
            score += 10
        else:
            return 0.0

    want_len = _parse_length_sec(row.get("length") or "")
    song_len = _song_length_sec(song)
    if want_len is not None:
        if song_len is None:
            score -= 5
        else:
            diff = abs(want_len - song_len)
            if diff < 0.6:
                score += 55
            elif diff < 2.0:
                score += 45
            elif diff < 5.0:
                score += 25
            elif diff < 10.0:
                score += 10
            else:
                score -= min(diff, 30)

    want_bpm_raw = (row.get("bpm") or "").strip()
    if want_bpm_raw:
        try:
            want_bpm = float(want_bpm_raw)
        except ValueError:
            want_bpm = 0.0
        song_bpm = _song_bpm_display(song)
        if want_bpm > 0:
            if song_bpm <= 0:
                score -= 8
            else:
                diff = abs(want_bpm - song_bpm)
                if diff < 0.25:
                    score += 35
                elif diff < 1.0:
                    score += 28
                elif diff < 3.0:
                    score += 12
                else:
                    score -= min(diff, 20)

    html_key = (row.get("key") or "").strip()
    song_key = (song.get("Tags.Key") or "").strip()
    if html_key:
        if song_key and _keys_match(html_key, song_key):
            score += 30
        elif song_key:
            score -= 15
        else:
            score -= 5

    want_stars = _parse_rating_stars(row.get("rating") or "")
    song_stars = _song_stars(song)
    if want_stars is not None:
        if song_stars is not None and want_stars == song_stars:
            score += 25
        elif song_stars is not None:
            score -= 10

    if str(song.get("HasLinks") or "") == "1":
        score += 4

    fp = normalize_path(song.get("FilePath") or "")
    if fp and linked_paths and fp in linked_paths:
        score += 3

    return score


def _enrich_songs_from_extra_db(songs: list[dict]) -> list[dict]:
    """Uzupełnia puste tagi z extra.db (track_data) — jak w UI Linked Tracks."""
    out: list[dict] = [dict(s) for s in songs or []]
    by_fp: dict[str, dict] = {
        normalize_path(s.get("FilePath") or ""): s
        for s in out
        if s.get("FilePath")
    }
    for e in load_linked_track_entries():
        fp = normalize_path(e.get("FilePath") or "")
        if not fp:
            continue
        if fp in by_fp:
            s = by_fp[fp]
            if not str(s.get("Tags.Title") or "").strip():
                s["Tags.Title"] = e.get("Tags.Title") or ""
            if not str(s.get("Tags.Author") or "").strip():
                s["Tags.Author"] = e.get("Tags.Author") or ""
            if not str(s.get("Tags.Artist") or "").strip():
                s["Tags.Artist"] = e.get("Tags.Author") or ""
            if not s.get("HasLinks"):
                s["HasLinks"] = e.get("HasLinks") or s.get("HasLinks")
        else:
            merged = dict(e)
            merged.setdefault("Infos.SongLength", "")
            out.append(merged)
            by_fp[fp] = merged
    return out


def _collect_row_candidates(
    row: dict,
    songs: list[dict],
    *,
    used_ids: set[int],
) -> list[dict]:
    """Kandydaci VDJ dla wiersza HTML — ten sam wykonawca/tytuł, jeszcze nieużyci."""
    a = _norm_meta(row.get("artist") or "")
    t = _norm_meta(row.get("title") or "")
    tc = _title_core(t)
    out: list[dict] = []
    seen: set[int] = set()
    for s in songs or []:
        sid = id(s)
        if sid in used_ids or sid in seen:
            continue
        sa = _norm_meta(s.get("Tags.Author") or s.get("Tags.Artist") or "")
        st = _norm_meta(s.get("Tags.Title") or "")
        stc = _title_core(st)
        fp_blob = _filename_search_blob(s.get("FilePath") or "")
        if not t and not a:
            continue
        if not a:
            # HTML bez artysty — tytuł lub nazwa pliku
            title_ok = bool(t) and (
                st == t or stc == tc or (len(t) >= 4 and t in fp_blob)
            )
            if title_ok:
                seen.add(sid)
                out.append(s)
            continue
        artist_ok = sa == a or a in sa or sa in a
        title_ok = st == t or stc == tc or (t and len(t) >= 4 and t in fp_blob)
        if artist_ok and title_ok:
            seen.add(sid)
            out.append(s)
    return out


def _pick_best_song_for_row(
    row: dict,
    candidates: list[dict],
    *,
    linked_paths: Optional[set[str]] = None,
    min_score: float = 35.0,
    min_margin: float = 4.0,
) -> tuple[Optional[dict], float, str]:
    """Wybiera jednoznacznie najlepszy rekord VDJ dla wiersza HTML."""
    if not candidates:
        return None, 0.0, ""
    ranked = sorted(
        (
            (_score_html_row_against_song(row, s, linked_paths=linked_paths), s)
            for s in candidates
        ),
        key=lambda x: (-x[0], _norm_meta(x[1].get("FilePath") or "")),
    )
    best_score, best = ranked[0]
    if best_score < min_score:
        return None, best_score, ""
    if len(ranked) > 1:
        second_score = ranked[1][0]
        if best_score - second_score < min_margin and best_score < 70:
            return None, best_score, "ambiguous"
    return best, best_score, "row_match"


def match_html_rows_to_local_paths(
    rows: list[dict],
    songs: list[dict],
    *,
    path_substitutes: Optional[dict[str, str]] = None,
    include_tidal: bool = False,
) -> tuple[list[str], dict]:
    """
    Dopasowuje wiersze HTML do ścieżek eksportu 1:1 z rekordem VDJ.
    Ten sam wykonawca/tytuł może mieć wiele wersji — rozróżniamy po długości,
    BPM, tonacji i ocenie; każdy wpis bazy może być użyty tylko raz.
    """
    from serato_offline import lookup_serato_offline_substitute
    from vdj_path_mapping import extract_song_tidal_id, resolve_vdj_local_path
    from vdj_streaming import is_serato_tidal_path, vdj_to_serato_tidal_path

    def resolve_local(s: dict) -> Optional[str]:
        fp = (s.get("FilePath") or "").strip()
        if not fp:
            return None
        if path_substitutes:
            hit = lookup_serato_offline_substitute(fp, path_substitutes)
            if hit and not is_serato_tidal_path(hit) and Path(hit).is_file():
                return hit
        return resolve_vdj_local_path(s)

    def resolve_tidal(s: dict) -> Optional[str]:
        fp = (s.get("FilePath") or "").strip()
        if path_substitutes:
            hit = lookup_serato_offline_substitute(fp, path_substitutes)
            if hit and is_serato_tidal_path(hit):
                return hit
        tid = extract_song_tidal_id(s) or ""
        if tid:
            return f"streaming://tidal/{tid}"
        return vdj_to_serato_tidal_path(fp) or None

    def resolve_export(s: dict) -> tuple[Optional[str], str]:
        local = resolve_local(s)
        if local:
            return local, "local"
        if include_tidal:
            tidal = resolve_tidal(s)
            if tidal:
                return tidal, "tidal"
        return None, ""

    paths: list[str] = []
    seen_paths: set[str] = set()
    used_song_ids: set[int] = set()
    stats = {
        "rows": len(rows or []),
        "matched_local": 0,
        "matched_tidal": 0,
        "unmatched": 0,
        "ambiguous": 0,
        "duplicates_skipped": 0,
        "matched_via_row": 0,
        "matched_via_unique_meta": 0,
    }

    linked_paths = linked_track_path_set()
    enriched = _enrich_songs_from_extra_db(songs)

    for row in rows or []:
        candidates = _collect_row_candidates(row, enriched, used_ids=used_song_ids)
        chosen_song, score, reason = _pick_best_song_for_row(
            row, candidates, linked_paths=linked_paths
        )
        via = "row_match"

        if not chosen_song and len(candidates) == 1:
            only = candidates[0]
            only_score = _score_html_row_against_song(
                row, only, linked_paths=linked_paths
            )
            export_probe, _ = resolve_export(only)
            if export_probe and only_score >= 15:
                chosen_song = only
                via = "unique_meta"
                score = only_score

        if not chosen_song:
            if reason == "ambiguous":
                stats["ambiguous"] += 1
            stats["unmatched"] += 1
            continue

        export, kind = resolve_export(chosen_song)
        if not export:
            stats["unmatched"] += 1
            continue

        used_song_ids.add(id(chosen_song))
        key = (
            export.lower()
            if export.startswith("streaming:")
            else normalize_path(export)
        )
        if key in seen_paths:
            stats["duplicates_skipped"] += 1
            continue
        seen_paths.add(key)
        paths.append(export)
        if kind == "local":
            stats["matched_local"] += 1
            if via == "row_match":
                stats["matched_via_row"] += 1
            else:
                stats["matched_via_unique_meta"] += 1
        else:
            stats["matched_tidal"] += 1

    stats["unique_paths"] = len(paths)
    stats["unique_local"] = stats["matched_local"]
    stats["unique_songs_used"] = len(used_song_ids)
    return paths, stats


def apply_linked_tracks_flags(songs: list[dict], home: Optional[Path] = None) -> int:
    """
    Ustawia HasLinks=1 na utworach z database.xml według extra.db (ścieżka lub meta).
    Nadpisuje mylne HasLinks z <Link NetSearch>.
    Zwraca liczbę oznaczonych utworów.
    """
    entries = load_linked_track_entries(home)
    path_set = {normalize_path(e.get("FilePath") or "") for e in entries if e.get("FilePath")}
    meta_set = {
        (
            _norm_meta(e.get("Tags.Author") or ""),
            _norm_meta(e.get("Tags.Title") or ""),
        )
        for e in entries
        if e.get("Tags.Title") or e.get("Tags.Author")
    }
    marked = 0
    for s in songs or []:
        fp = normalize_path(s.get("FilePath") or "")
        a = _norm_meta(s.get("Tags.Author") or s.get("Tags.Artist") or "")
        t = _norm_meta(s.get("Tags.Title") or "")
        hit = (fp and fp in path_set) or ((a, t) in meta_set)
        s["HasLinks"] = "1" if hit else "0"
        if hit:
            marked += 1
    return marked
