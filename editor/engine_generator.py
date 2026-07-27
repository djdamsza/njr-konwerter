"""
Eksport UnifiedDatabase → Engine DJ (libdjinterop przez njr-engine-export).
Filter listy VDJ → zwykłe playlisty (przez filter_lists_to_regular_playlists).
"""
from __future__ import annotations

import math
import os
import re
import zipfile
from pathlib import Path
from typing import Optional

from unified_model import Track, UnifiedDatabase, BeatgridPoint, CuePoint, LoopPoint, Playlist
from vdj_parser import parse_tags_value, join_tags

# Rozszerzenia akceptowane przez Engine DJ (libdjinterop wymaga rozszerzenia w ścieżce).
_ENGINE_EXPORT_EXTENSIONS = frozenset({
    ".mp3", ".m4a", ".mp4", ".wav", ".flac", ".ogg", ".aac", ".aiff", ".aif", ".wma",
})
_ENGINE_SKIP_SUFFIXES = frozenset({".vdjcache", ".vdjsample"})

# Camelot (VDJ/OpenKey) — libdjinterop musical_key przez key_camelot w JSON
_CAMELOT_RE = re.compile(r"^\s*(\d{1,2})\s*([AB])\s*$", re.IGNORECASE)

# Zgodne z formatKey() w static/index.html (+ enharmonic majors dla G#, D#, A#, C#)
_CAMELOT_MAP: dict[str, str] = {
    "c": "8B",
    "g": "9B",
    "d": "10B",
    "a": "11B",
    "e": "12B",
    "b": "1B",
    "f#": "2B",
    "fsharp": "2B",
    "gb": "2B",
    "gflat": "2B",
    "db": "3B",
    "c#": "3B",
    "csharp": "3B",
    "dflat": "3B",
    "ab": "4B",
    "g#": "4B",
    "eb": "5B",
    "d#": "5B",
    "bb": "6B",
    "a#": "6B",
    "f": "7B",
    "am": "8A",
    "aminor": "8A",
    "em": "9A",
    "eminor": "9A",
    "bm": "10A",
    "bminor": "10A",
    "f#m": "11A",
    "fsharpm": "11A",
    "f#minor": "11A",
    "c#m": "12A",
    "csharpm": "12A",
    "dbm": "12A",
    "dbminor": "12A",
    "g#m": "1A",
    "gsharpm": "1A",
    "abm": "1A",
    "abminor": "1A",
    "d#m": "2A",
    "dsharpm": "2A",
    "ebm": "2A",
    "ebminor": "2A",
    "a#m": "3A",
    "asharpm": "3A",
    "bbm": "3A",
    "bbminor": "3A",
    "fm": "4A",
    "fminor": "4A",
    "cm": "5A",
    "cminor": "5A",
    "gm": "6A",
    "gminor": "6A",
    "dm": "7A",
    "dminor": "7A",
}


def _normalize_key_notation(key: str) -> str:
    k = key.strip().lower()
    k = re.sub(r"\s+", "", k)
    k = re.sub(r"minor", "m", k)
    k = re.sub(r"maj(?:or)?", "", k)
    k = re.sub(r"sharp", "#", k)
    k = re.sub(r"flat", "b", k)
    return k


def camelot_normalize(key: str) -> str:
    """VDJ/OpenKey (8A) lub tonacja muzyczna (Am, G#) → Camelot dla Engine DJ."""
    if not key:
        return ""
    raw = key.strip()
    m = _CAMELOT_RE.match(raw)
    if m:
        return f"{int(m.group(1))}{m.group(2).upper()}"

    norm = _normalize_key_notation(raw)
    if not norm:
        return ""

    hit = _CAMELOT_MAP.get(norm)
    if hit:
        return hit
    if norm.endswith("m"):
        base = norm[:-1]
        hit = _CAMELOT_MAP.get(base + "m")
        if hit:
            return hit
    else:
        hit = _CAMELOT_MAP.get(norm + "m")
        if hit:
            return hit
    return ""


def _rating_to_engine(rating: int) -> int:
    """VDJ 0–5 gwiazdek lub Serato/Rekordbox 0–255 → Engine 0–100."""
    if rating <= 0:
        return 0
    if rating <= 5:
        return min(100, max(20, rating * 20))
    return min(100, max(20, round(rating / 255 * 100)))


def _guess_sample_rate(track: Track) -> int:
    try:
        from mutagen import File as MutagenFile

        p = Path(track.path)
        if p.is_file():
            mf = MutagenFile(str(p))
            if mf and mf.info and getattr(mf.info, "sample_rate", None):
                return int(mf.info.sample_rate)
    except Exception:
        pass
    return 44100


def _guess_file_info(path: str) -> tuple[int, int]:
    """Bitrate (kbps) i rozmiar pliku (bajty) — Engine DJ wymaga tego m.in. do stemów."""
    from engine_file_info import probe_audio_file_info

    p = Path(path)
    if not p.is_file():
        return 0, 0
    bitrate, file_bytes = probe_audio_file_info(p)
    return int(bitrate or 0), int(file_bytes or 0)


def beatgrid_to_engine_markers(
    track: Track, sample_rate: int
) -> list[dict]:
    """
    Konwertuje beatgrid VDJ (sekundy + BPM) na markery libdjinterop.
    Używa konwencji Engine: pierwszy marker index -4, ostatni na końcu utworu.
    """
    duration_sec = track.duration or 0.0
    bpm = track.bpm or 0.0
    if track.beatgrid:
        bpm = track.beatgrid[0].bpm or bpm
        anchor_sec = min(bg.pos for bg in track.beatgrid)
    else:
        anchor_sec = 0.0

    if bpm <= 0 or duration_sec <= 0:
        return []

    sec_per_beat = 60.0 / bpm
    first_index = -4
    first_offset_sec = anchor_sec + first_index * sec_per_beat
    first_sample = first_offset_sec * sample_rate

    end_sample = duration_sec * sample_rate
    beats_from_anchor = max(1, int(math.floor((duration_sec - anchor_sec) / sec_per_beat)))
    last_index = beats_from_anchor

    return [
        {"index": first_index, "sample_offset": first_sample},
        {"index": last_index, "sample_offset": end_sample},
    ]


def _vdj_cue_slot(num: int) -> int | None:
    """VDJ hot cue Num 1–8 → Engine slot 0–7; Num 0–7 też akceptowane (legacy)."""
    if 1 <= num <= 8:
        return num - 1
    if 0 <= num < 8:
        return num
    return None


def cues_to_engine_hot(track: Track, sample_rate: int) -> list[dict]:
    out: list[dict] = []
    used: set[int] = set()
    for cp in track.cue_points or []:
        slot = _vdj_cue_slot(cp.num)
        if slot is None or slot in used:
            continue
        used.add(slot)
        out.append(
            {
                "slot": slot,
                "label": (cp.name or f"Cue {slot + 1}")[:64],
                "sample_offset": cp.pos * sample_rate,
                "pad": slot,
            }
        )
    return out


def loops_to_engine(track: Track, sample_rate: int) -> list[dict]:
    """LoopPoint → JSON dla libdjinterop (max 8 slotów 0–7)."""
    out: list[dict] = []
    used: set[int] = set()
    for lp in track.loops or []:
        slot = int(lp.slot)
        if slot < 0 or slot > 7 or slot in used:
            continue
        if lp.end_ms <= lp.position_ms:
            continue
        used.add(slot)
        start_samples = lp.position_ms / 1000.0 * sample_rate
        end_samples = lp.end_ms / 1000.0 * sample_rate
        out.append(
            {
                "slot": slot,
                "label": (lp.label or f"Loop {slot + 1}")[:64],
                "start_sample_offset": start_samples,
                "end_sample_offset": end_samples,
                "pad": slot,
            }
        )
    return out


def _to_relative_path(
    path: str,
    engine_dir: Optional[Path] = None,
    library_root: Optional[str] = None,
) -> str:
    """
    Ścieżka względna dla Engine DJ — zawsze względem folderu „Engine Library”,
    nie względem folderu z muzyką. Np. muzyka na Desktop → ../../Desktop/…/plik.mp3.
    """
    raw = path.replace("\\", "/")
    try:
        p = Path(raw).expanduser().resolve()
    except OSError:
        p = Path(raw)

    if engine_dir:
        try:
            rel = os.path.relpath(str(p), str(engine_dir.expanduser().resolve()))
            if rel in (".", ""):
                return p.name
            return Path(rel).as_posix()
        except ValueError:
            pass

    if library_root:
        root = Path(library_root.replace("\\", "/")).resolve()
        try:
            rel = p.resolve().relative_to(root)
            return rel.as_posix()
        except ValueError:
            pass
    return p.name


def _is_engine_exportable_path(path: str) -> bool:
    """Engine DJ odrzuca ścieżki bez rozszerzenia oraz cache VDJ/Tidal."""
    from engine_music_paths import is_junk_engine_path

    raw = (path or "").strip().replace("\\", "/")
    if not raw or raw.startswith("netsearch:"):
        return False
    if is_junk_engine_path(raw):
        return False
    name = Path(raw).name
    if not name or name.startswith("."):
        return False
    if re.fullmatch(r"td\d+", name, re.IGNORECASE):
        return False
    suffix = Path(name).suffix.lower()
    if not suffix:
        return False
    if suffix in _ENGINE_SKIP_SUFFIXES:
        return False
    return suffix in _ENGINE_EXPORT_EXTENSIONS


def _apply_path_replace(path: str, path_replace: Optional[dict[str, str]]) -> str:
    if not path_replace:
        return path
    from vdjfolder import normalize_path

    np = normalize_path(path)
    for old, new in path_replace.items():
        no = normalize_path(old).rstrip("/")
        if no and np.startswith(no):
            return normalize_path(new.rstrip("/") + np[len(no) :])
    return np


def engine_genre_for_export(track: Track) -> str:
    """
    Genre dla Engine DJ: Tags.Genre + tagi User1/User2 jako #tagi w jednym polu.
    Umożliwia Smartlisty Engine filtrowane po #tag (jak w VDJ).
    """
    parts: list[str] = []
    seen: set[str] = set()

    for t in parse_tags_value(track.genre or ""):
        key = t.lstrip("#").lower()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        parts.append(t if t.startswith("#") else f"#{t}")

    for t in track.tags or []:
        key = (t or "").lstrip("#").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        parts.append(t if str(t).startswith("#") else f"#{t}")

    return join_tags(parts)


def track_to_engine_json(
    track: Track,
    *,
    engine_dir: Optional[Path] = None,
    library_root: Optional[str] = None,
    path_replace: Optional[dict[str, str]] = None,
    engine_music_layout: bool = False,
    music_path_occupied: Optional[set[str]] = None,
    music_source_to_rel: Optional[dict[str, str]] = None,
    patriot_path_index: Optional[dict[str, list[dict]]] = None,
) -> Optional[dict]:
    from engine_music_paths import (
        ensure_music_symlink,
        music_rel_for_export,
        resolve_local_file,
    )

    path = _apply_path_replace(track.path, path_replace)
    if not _is_engine_exportable_path(path):
        return None
    abs_file = resolve_local_file(path)
    if not abs_file:
        return None
    sample_rate = _guess_sample_rate(track)
    bitrate, file_bytes = _guess_file_info(str(abs_file))
    if engine_music_layout and engine_dir:
        occupied = music_path_occupied if music_path_occupied is not None else set()
        source_key = str(abs_file)
        cached = (music_source_to_rel or {}).get(source_key)
        if cached:
            rel = cached
        else:
            rel = music_rel_for_export(
                engine_dir,
                artist=track.artist or "",
                album=track.album or "",
                abs_file=abs_file,
                title=track.title or "",
                file_bytes=file_bytes,
                occupied=occupied,
                pat_index=patriot_path_index,
            )
            if music_source_to_rel is not None:
                music_source_to_rel[source_key] = rel
        if not ensure_music_symlink(engine_dir, rel, abs_file):
            return None
    else:
        rel = _to_relative_path(
            str(abs_file),
            engine_dir=engine_dir,
            library_root=library_root,
        )
    from tag_writer import strip_rating_hack_from_comment

    entry = {
        "relative_path": rel,
        "title": track.title or Path(str(abs_file)).stem,
        "artist": track.artist or "",
        "album": track.album or "",
        "genre": engine_genre_for_export(track),
        "comment": strip_rating_hack_from_comment(track.comment or ""),
        "year": int(track.year or 0),
        "bpm": float(track.bpm or 0),
        "duration_sec": float(track.duration or 0),
        "rating": _rating_to_engine(int(track.rating or 0)),
        "sample_rate": sample_rate,
        "bitrate": bitrate,
        "file_bytes": file_bytes,
    }
    ck = camelot_normalize(track.key or "")
    if ck:
        entry["key_camelot"] = ck
    bg = beatgrid_to_engine_markers(track, sample_rate)
    if bg:
        entry["beatgrid"] = bg
    hot = cues_to_engine_hot(track, sample_rate)
    if hot:
        entry["hot_cues"] = hot
    loops = loops_to_engine(track, sample_rate)
    if loops:
        entry["loops"] = loops
    return entry


def _resolve_playlist_track_paths(
    track_ids: list[str],
    db: UnifiedDatabase,
    *,
    engine_dir: Optional[Path] = None,
    library_root: Optional[str] = None,
    path_replace: Optional[dict[str, str]] = None,
    path_set: set[str],
    engine_music_layout: bool = False,
    music_path_occupied: Optional[set[str]] = None,
    music_source_to_rel: Optional[dict[str, str]] = None,
    patriot_path_index: Optional[dict[str, list[dict]]] = None,
) -> list[str]:
    paths: list[str] = []
    for tid in track_ids:
        tmatch = next((x for x in db.tracks if x.path == tid), None)
        if tmatch:
            row = track_to_engine_json(
                tmatch,
                engine_dir=engine_dir,
                library_root=library_root,
                path_replace=path_replace,
                engine_music_layout=engine_music_layout,
                music_path_occupied=music_path_occupied,
                music_source_to_rel=music_source_to_rel,
                patriot_path_index=patriot_path_index,
            )
            if row:
                paths.append(row["relative_path"])
        else:
            ap = _apply_path_replace(tid, path_replace)
            if _is_engine_exportable_path(ap):
                rel = _to_relative_path(ap, engine_dir=engine_dir, library_root=library_root)
                if rel in path_set:
                    paths.append(rel)
    deduped: list[str] = []
    seen: set[str] = set()
    for rel in paths:
        if rel not in seen:
            seen.add(rel)
            deduped.append(rel)
    return deduped


def _playlist_to_engine_json(
    pl: Playlist,
    db: UnifiedDatabase,
    *,
    engine_dir: Optional[Path] = None,
    library_root: Optional[str] = None,
    path_replace: Optional[dict[str, str]] = None,
    path_set: set[str],
    engine_music_layout: bool = False,
    music_path_occupied: Optional[set[str]] = None,
    music_source_to_rel: Optional[dict[str, str]] = None,
    patriot_path_index: Optional[dict[str, list[dict]]] = None,
) -> Optional[dict]:
    children_json: list[dict] = []
    for child in pl.children or []:
        row = _playlist_to_engine_json(
            child,
            db,
            engine_dir=engine_dir,
            library_root=library_root,
            path_replace=path_replace,
            path_set=path_set,
            engine_music_layout=engine_music_layout,
            music_path_occupied=music_path_occupied,
            music_source_to_rel=music_source_to_rel,
            patriot_path_index=patriot_path_index,
        )
        if row:
            children_json.append(row)

    track_paths = _resolve_playlist_track_paths(
        pl.track_ids or [],
        db,
        engine_dir=engine_dir,
        library_root=library_root,
        path_replace=path_replace,
        path_set=path_set,
        engine_music_layout=engine_music_layout,
        music_path_occupied=music_path_occupied,
        music_source_to_rel=music_source_to_rel,
        patriot_path_index=patriot_path_index,
    )

    if not track_paths and not children_json:
        return None

    entry: dict = {"name": pl.name}
    if children_json or pl.is_folder:
        entry["is_folder"] = True
    if children_json:
        entry["children"] = children_json
    if track_paths:
        entry["track_paths"] = track_paths
    return entry


def unified_to_engine_export_doc(
    db: UnifiedDatabase,
    *,
    engine_dir: Optional[Path] = None,
    library_root: Optional[str] = None,
    path_replace: Optional[dict[str, str]] = None,
    clear_existing: bool = True,
    merge_mode: bool = False,
    replace_playlist_tracks: bool = True,
    playlist_prefix: str = "",
    cleanup_legacy_vdj_playlists: bool = False,
    prune_tracks_not_in_source: bool = False,
    sample_rate: int = 44100,
    engine_music_layout: bool = False,
    patriot_path_index: Optional[dict[str, list[dict]]] = None,
) -> dict:
    tracks_json = []
    path_set: set[str] = set()
    music_path_occupied: set[str] = set()
    music_source_to_rel: dict[str, str] = {}
    tracks_skipped = 0

    if engine_music_layout and patriot_path_index is None:
        from engine_stems import DEFAULT_PATRIOT_ENGINE, index_tracks_by_filename, patriot_engine_available

        if patriot_engine_available(DEFAULT_PATRIOT_ENGINE):
            patriot_path_index = index_tracks_by_filename(DEFAULT_PATRIOT_ENGINE)

    for t in db.tracks:
        row = track_to_engine_json(
            t,
            engine_dir=engine_dir,
            library_root=library_root,
            path_replace=path_replace,
            engine_music_layout=engine_music_layout,
            music_path_occupied=music_path_occupied,
            music_source_to_rel=music_source_to_rel,
            patriot_path_index=patriot_path_index,
        )
        if not row:
            if t.path and not str(t.path).startswith("netsearch:"):
                tracks_skipped += 1
            continue
        rel = row["relative_path"]
        if rel in path_set:
            continue
        path_set.add(rel)
        tracks_json.append(row)

    playlists_json = []
    for pl in db.playlists or []:
        row = _playlist_to_engine_json(
            pl,
            db,
            engine_dir=engine_dir,
            library_root=library_root,
            path_replace=path_replace,
            path_set=path_set,
            engine_music_layout=engine_music_layout,
            music_path_occupied=music_path_occupied,
            music_source_to_rel=music_source_to_rel,
            patriot_path_index=patriot_path_index,
        )
        if row:
            playlists_json.append(row)

    return {
        "clear_existing": False if merge_mode else clear_existing,
        "merge_mode": merge_mode,
        "replace_playlist_tracks": replace_playlist_tracks,
        "playlist_prefix": playlist_prefix or "",
        "cleanup_legacy_vdj_playlists": cleanup_legacy_vdj_playlists,
        "prune_tracks_not_in_source": prune_tracks_not_in_source,
        "engine_music_layout": engine_music_layout,
        "sample_rate": sample_rate,
        "tracks_skipped": tracks_skipped,
        "tracks": tracks_json,
        "playlists": playlists_json,
    }


def zip_engine_library(engine_dir: Path) -> bytes:
    """Pakuje folder Engine Library do ZIP (Database2/…)."""
    import io

    buf = io.BytesIO()
    engine_dir = engine_dir.resolve()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in engine_dir.rglob("*"):
            if f.is_file():
                arc = Path("Engine Library") / f.relative_to(engine_dir)
                zf.write(f, arc.as_posix())
    return buf.getvalue()
