"""Przy podmianie utworu stary rekord oddaje tagi, a przy tym samym czasie także cue, BPM i tonację."""
from __future__ import annotations

from vdj_parser import join_tags, parse_tags_value

TAG_FIELDS = ("Tags.Genre", "Tags.User1", "Tags.User2")
LENGTH_TOLERANCE = 2.0


def song_seconds(song: dict) -> float:
    for key in ("Infos.SongLength", "SongLength", "duration"):
        raw = song.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if value > 10000:
            value = value / 1000.0
        return value
    return 0.0


def same_length(source: dict, dest: dict, tolerance: float = LENGTH_TOLERANCE) -> bool:
    left = song_seconds(source)
    right = song_seconds(dest)
    if left <= 0 or right <= 0:
        return False
    return abs(left - right) <= tolerance


def _is_cue(xml: str) -> bool:
    low = (xml or "").lower()
    return 'type="cue"' in low or "type='cue'" in low


def _merge_tags(source_value: str, dest_value: str) -> str:
    incoming = parse_tags_value(source_value)
    if not incoming:
        return dest_value or ""
    kept = parse_tags_value(dest_value)
    return join_tags(list(dict.fromkeys([*kept, *incoming])))


def inherit_record(source: dict, dest: dict) -> dict:
    """Dopisuje tagi zawsze. Cue, BPM i tonację tylko gdy czas jest ten sam."""
    notes = {"tags": False, "cues": False, "bpm": False, "key": False, "sameLength": False}
    if source is dest:
        return notes
    for field in TAG_FIELDS:
        src = (source.get(field) or "").strip()
        if not src:
            continue
        merged = _merge_tags(src, dest.get(field) or "")
        if merged and merged != (dest.get(field) or ""):
            dest[field] = merged
            notes["tags"] = True
    if not same_length(source, dest):
        return notes
    notes["sameLength"] = True
    src_bpm = str(source.get("Tags.Bpm") or "").strip()
    if src_bpm and not str(dest.get("Tags.Bpm") or "").strip():
        dest["Tags.Bpm"] = src_bpm
        notes["bpm"] = True
    src_key = str(source.get("Tags.Key") or "").strip()
    if src_key and not str(dest.get("Tags.Key") or "").strip():
        dest["Tags.Key"] = src_key
        notes["key"] = True
    src_cues = [xml for xml in (source.get("_children_xml") or []) if _is_cue(xml)]
    if src_cues:
        kept = [xml for xml in (dest.get("_children_xml") or []) if not _is_cue(xml)]
        dest["_children_xml"] = kept + list(src_cues)
        notes["cues"] = True
    return notes


def write_inherited_file(source: dict, path: str, copy_analysis: bool) -> dict:
    """Zapisuje tagi do pliku. Cue, BPM i tonację tylko przy tym samym czasie. Tytułu nie rusza."""
    from dataclasses import replace
    from pathlib import Path

    target = (path or "").strip()
    if not target or not Path(target).is_file():
        return {"ok": False, "reason": "brak pliku"}
    from tidal_vdj_metadata import vdj_song_to_track

    track = vdj_song_to_track(source)
    if track is None:
        return {"ok": False, "reason": "brak rekordu"}
    track = replace(
        track,
        path=target,
        title="",
        artist="",
        album="",
        year=0,
        rating=0,
        comment="",
        play_count=0,
        bpm=track.bpm if copy_analysis else 0,
        key=track.key if copy_analysis else "",
        cue_points=list(track.cue_points or []) if copy_analysis else [],
        loops=list(track.loops or []) if copy_analysis else [],
        beatgrid=[],
    )
    out = {"ok": True, "tags": "", "analysis": "", "cues": ""}
    from tag_writer import write_dj_extended_metadata, write_tags_to_file

    if track.genre or track.tags:
        ok, msg = write_tags_to_file(track, target)
        out["tags"] = msg if ok else f"skip:{msg}"
    if copy_analysis and (track.bpm or track.key):
        ok, msg = write_dj_extended_metadata(track, target)
        out["analysis"] = msg if ok else f"skip:{msg}"
    if copy_analysis and track.cue_points:
        from serato_markers import write_serato_markers2_to_file

        ok, msg = write_serato_markers2_to_file(track, target, skip_unchanged=True, preserve_existing=True)
        out["cues"] = msg if ok else f"skip:{msg}"
    return out
