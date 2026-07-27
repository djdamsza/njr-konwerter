"""
Po pobraniu utworu Tidal → dopisz metadane VDJ (tagi, BPM, key, rating, hot cues Serato).
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from unified_model import Track
from vdj_adapter import vdj_songs_to_unified
from vdj_streaming import extract_tidal_id

_meta_lock = threading.Lock()
_meta_state: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "applied": 0,
    "skipped": 0,
    "failed": 0,
    "errors": [],
    "started_at": None,
    "finished_at": None,
}


def _norm_meta(s: str) -> str:
    return str(s or "").strip().lower()


def _song_tidal_id(s: dict) -> Optional[str]:
    from vdj_tidal_cache import extract_netsearch_link

    fp = (s.get("FilePath") or "").strip()
    return extract_tidal_id(fp) or extract_netsearch_link(s)


def _vdj_song_score(s: dict) -> int:
    score = 0
    for xml in s.get("_children_xml") or []:
        if "Poi" in xml:
            low = xml.lower()
            if 'type="cue"' in low or "type='cue'" in low:
                score += 10
            if 'type="loop"' in low or "type='loop'" in low:
                score += 8
    if s.get("Tags.Stars"):
        score += 5
    if s.get("Tags.Key"):
        score += 3
    if s.get("Tags.User1") or s.get("Tags.User2") or s.get("Tags.Genre"):
        score += 2
    if s.get("Tags.Comment") or any("Comment" in x for x in (s.get("_children_xml") or [])):
        score += 1
    return score


def find_vdj_song_for_tidal_id(
    tidal_id: str,
    songs: list[dict],
    *,
    author: str = "",
    title: str = "",
) -> Optional[dict]:
    tid = str(tidal_id or "").strip()
    if not tid:
        return None
    matches: list[dict] = []
    for s in songs or []:
        if _song_tidal_id(s) == tid:
            matches.append(s)
    if matches:
        return max(matches, key=_vdj_song_score)
    return None


def vdj_song_to_track(song: dict) -> Optional[Track]:
    db = vdj_songs_to_unified([song])
    return db.tracks[0] if db.tracks else None


def apply_vdj_metadata_from_song(
    local_path: str,
    song: dict,
    *,
    skip_unchanged_cues: bool = True,
) -> dict:
    """Zapis tagów + Markers2 z konkretnego rekordu VDJ do lokalnego pliku."""
    p = (local_path or "").strip()
    if not p or not Path(p).is_file():
        return {"ok": False, "reason": "missing_file"}
    if not song:
        return {"ok": False, "reason": "no_song"}

    track = vdj_song_to_track(song)
    if not track:
        return {"ok": False, "reason": "track_convert_failed"}

    track = replace(track, path=p)
    out: dict = {
        "ok": True,
        "path": p,
        "cues_in_vdj": len(track.cue_points or []),
        "loops_in_vdj": len(track.loops or []),
    }

    from tag_writer import (
        unified_rating_to_stars,
        write_dj_extended_metadata,
        write_tags_to_file,
    )
    from serato_markers import write_serato_markers2_to_file

    ok_tags, msg_tags = write_tags_to_file(track, p)
    out["tags"] = msg_tags if ok_tags else f"skip:{msg_tags}"

    ok_ext, msg_ext = write_dj_extended_metadata(track, p)
    out["extended"] = msg_ext if ok_ext else f"skip:{msg_ext}"

    ok_cues, msg_cues = write_serato_markers2_to_file(
        track, p, skip_unchanged=skip_unchanged_cues
    )
    out["cues"] = msg_cues if ok_cues else f"skip:{msg_cues}"

    # Library SQLite: ★ w kolumnie Rating (0.0–1.0) + czysty comment
    stars = unified_rating_to_stars(track.rating or 0)
    if stars > 0 or (track.comment or ""):
        try:
            from serato_library_sqlite import update_local_asset_rating

            sq = update_local_asset_rating(
                p, stars, comment=track.comment or ""
            )
            out["sqlite_rating"] = sq
        except Exception as e:
            out["sqlite_rating"] = {"ok": False, "reason": str(e)}
    return out


def apply_vdj_metadata_to_tidal_file(
    local_path: str,
    tidal_id: str,
    songs: list[dict],
    *,
    author: str = "",
    title: str = "",
    skip_unchanged_cues: bool = True,
) -> dict:
    """Zapis tagów ID3, BPM/key/rating i Markers2 (hot cues) z rekordu VDJ."""
    song = find_vdj_song_for_tidal_id(tidal_id, songs, author=author, title=title)
    if not song:
        return {
            "ok": False,
            "reason": "Brak wpisu VDJ dla tego Tidal ID (nie znaleziono w załadowanej bazie)",
            "tidalId": tidal_id,
        }
    out = apply_vdj_metadata_from_song(
        local_path, song, skip_unchanged_cues=skip_unchanged_cues
    )
    out["tidalId"] = tidal_id
    return out


def apply_metadata_for_path_substitutes(
    songs: list[dict],
    path_substitutes: dict[str, str],
    *,
    skip_unchanged_cues: bool = True,
) -> dict:
    """
    Dla mapowań VDJ (netsearch/.vdjcache) → lokalny plik NJR/mp3
    przepisuje tagi i hot cues z VDJ do pliku (Markers2).
    """
    from vdjfolder import normalize_path
    from vdj_streaming import is_serato_tidal_path

    by_path: dict[str, dict] = {}
    for s in songs or []:
        fp = (s.get("FilePath") or "").strip()
        if not fp:
            continue
        key = normalize_path(fp)
        prev = by_path.get(key)
        if not prev or _vdj_song_score(s) > _vdj_song_score(prev):
            by_path[key] = s

    applied = 0
    skipped = 0
    failed = 0
    cues_written = 0
    errors: list[str] = []
    seen_dst: set[str] = set()

    for src, dst in (path_substitutes or {}).items():
        dst = (dst or "").strip()
        if not dst or is_serato_tidal_path(dst):
            skipped += 1
            continue
        if not Path(dst).is_file():
            skipped += 1
            continue
        dst_key = normalize_path(dst)
        if dst_key in seen_dst:
            skipped += 1
            continue
        seen_dst.add(dst_key)

        song = by_path.get(normalize_path(src))
        if not song:
            tid = extract_tidal_id(src)
            if tid:
                song = find_vdj_song_for_tidal_id(tid, songs)
        if not song:
            skipped += 1
            continue
        try:
            res = apply_vdj_metadata_from_song(
                dst, song, skip_unchanged_cues=skip_unchanged_cues
            )
        except Exception as e:
            failed += 1
            if len(errors) < 40:
                errors.append(f"{Path(dst).name}: {e}")
            continue
        if res.get("ok"):
            applied += 1
            if res.get("cues_in_vdj"):
                cues_written += 1
        else:
            failed += 1
            if len(errors) < 40:
                errors.append(f"{Path(dst).name}: {res.get('reason')}")

    return {
        "ok": True,
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "with_vdj_cues": cues_written,
        "errors": errors,
    }


def apply_vdj_metadata_to_local_paths(
    songs: list[dict],
    paths: list[str],
    *,
    path_substitutes: Optional[dict[str, str]] = None,
    path_replace: Optional[dict[str, str]] = None,
    skip_unchanged_cues: bool = True,
) -> dict:
    """
    Dla lokalnych plików (MP3/M4A/…) z playlisty Serato:
    tagi + rating (POPM/rate) + hot cues + SQLite rating — jak dla NJR substitutes.
    Mapowanie wyłącznie po ścieżce (export / FilePath), bez dopasowania po meta.
    """
    from vdj_path_mapping import build_export_to_song_map, build_vdj_song_by_path_index
    from vdjfolder import normalize_path
    from vdj_streaming import is_serato_tidal_path

    export_to_song = (
        build_export_to_song_map(
            songs, path_substitutes or {}, path_replace=path_replace
        )
        if path_substitutes
        else {}
    )
    by_vdj_path = build_vdj_song_by_path_index(songs)

    applied = skipped = failed = cues_written = loops_written = 0
    errors: list[str] = []
    seen: set[str] = set()

    for raw in paths or []:
        p = (raw or "").strip()
        if not p or is_serato_tidal_path(p):
            skipped += 1
            continue
        if not Path(p).is_file():
            skipped += 1
            continue
        key = normalize_path(p)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)

        song = export_to_song.get(key) or by_vdj_path.get(key)
        if not song:
            skipped += 1
            continue
        try:
            res = apply_vdj_metadata_from_song(
                p, song, skip_unchanged_cues=skip_unchanged_cues
            )
        except Exception as e:
            failed += 1
            if len(errors) < 40:
                errors.append(f"{Path(p).name}: {e}")
            continue
        if res.get("ok"):
            applied += 1
            if res.get("cues") == "OK":
                cues_written += 1
            if res.get("loops_in_vdj") and res.get("cues") == "OK":
                loops_written += 1
        else:
            failed += 1
            if len(errors) < 40:
                errors.append(f"{Path(p).name}: {res.get('reason')}")

    return {
        "ok": True,
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "cues_written": cues_written,
        "loops_written": loops_written,
        "errors": errors,
    }


def _downloaded_manifest_ids(tracks: dict) -> list[str]:
    out: list[str] = []
    for tid, entry in (tracks or {}).items():
        tid = str(tid).strip()
        if not tid.isdigit():
            continue
        path = (entry.get("path") or "").strip()
        if path and Path(path).is_file():
            out.append(tid)
    return out


def metadata_status() -> dict:
    with _meta_lock:
        return dict(_meta_state)


def _set_meta(**kwargs) -> None:
    with _meta_lock:
        _meta_state.update(kwargs)


def apply_vdj_metadata_batch(
    songs: list[dict],
    *,
    tidal_ids: Optional[list[str]] = None,
    only_missing: bool = False,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Uzupełnia metadane dla pobranych plików z manifestu."""
    from tidal_download import load_manifest, save_manifest

    manifest = load_manifest()
    tracks = manifest.get("tracks") or {}
    if tidal_ids:
        ids = [str(x).strip() for x in tidal_ids if str(x).strip().isdigit()]
    else:
        ids = _downloaded_manifest_ids(tracks)

    applied = 0
    skipped = 0
    failed = 0
    no_match = 0
    errors: list[str] = []

    for tid in ids:
        entry = tracks.get(tid) or {}
        if only_missing and entry.get("metadata_applied_at"):
            skipped += 1
            _set_meta(done=applied + skipped + failed, skipped=skipped)
            if on_progress:
                on_progress(metadata_status())
            continue
        path = (entry.get("path") or "").strip()
        if not path or not Path(path).is_file():
            skipped += 1
            _set_meta(done=applied + skipped + failed, skipped=skipped)
            if on_progress:
                on_progress(metadata_status())
            continue
        try:
            res = apply_vdj_metadata_to_tidal_file(
                path,
                tid,
                songs,
                author=(entry.get("author") or ""),
                title=(entry.get("title") or ""),
            )
        except Exception as e:
            failed += 1
            if len(errors) < 30:
                errors.append(f"{tid}: {e}")
            entry["metadata_error"] = str(e)
            _set_meta(done=applied + skipped + failed, failed=failed, errors=errors)
            if on_progress:
                on_progress(metadata_status())
            continue
        if res.get("ok"):
            applied += 1
            entry["metadata_applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            entry["metadata_error"] = ""
            entry["metadata_summary"] = {
                k: res.get(k) for k in ("tags", "extended", "cues") if k in res
            }
        else:
            failed += 1
            reason = res.get("reason") or "unknown"
            if "Brak wpisu VDJ" in reason:
                no_match += 1
            entry["metadata_error"] = reason
            if len(errors) < 30:
                errors.append(f"{tid}: {reason}")
        _set_meta(
            done=applied + skipped + failed,
            applied=applied,
            skipped=skipped,
            failed=failed,
            errors=errors,
        )
        if on_progress:
            on_progress(metadata_status())

    save_manifest(manifest)
    return {
        "ok": True,
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "no_vdj_match": no_match,
        "errors": errors,
        "total": len(ids),
    }


def start_metadata_batch_async(songs: list[dict], *, only_missing: bool = False) -> int:
    if metadata_status().get("running"):
        raise RuntimeError("Uzupełnianie metadanych już trwa")

    from tidal_download import load_manifest

    tracks = load_manifest().get("tracks") or {}
    total = len(_downloaded_manifest_ids(tracks))
    _set_meta(
        running=True,
        total=total,
        done=0,
        applied=0,
        skipped=0,
        failed=0,
        errors=[],
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        finished_at=None,
    )

    def _run() -> None:
        try:
            apply_vdj_metadata_batch(songs, only_missing=only_missing, on_progress=lambda _st: None)
        except Exception as e:
            _set_meta(running=False, errors=[str(e)], finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        finally:
            _set_meta(running=False, finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"))

    threading.Thread(target=_run, daemon=True).start()
    return total
