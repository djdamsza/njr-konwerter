"""
Mapowanie VDJ → Serato po ścieżce pliku i linku Tidal (FilePath / Link.NetSearch),
bez dopasowania po samym artyście i tytule.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from vdjfolder import normalize_path
from vdj_streaming import extract_tidal_id, is_tidal_path, vdj_to_serato_tidal_path


def extract_song_tidal_id(song: dict) -> Optional[str]:
    """Tidal ID z FilePath (netsearch/cache) lub Link.NetSearch / pola Link.NetSearch."""
    from vdj_tidal_cache import extract_netsearch_link

    fp = (song.get("FilePath") or "").strip()
    tid = extract_tidal_id(fp)
    if tid:
        return tid
    link = (song.get("Link.NetSearch") or "").strip()
    if link:
        tid = extract_tidal_id(link) or (link if link.isdigit() else None)
        if tid:
            return tid
    return extract_netsearch_link(song)


def resolve_vdj_local_path(
    song: dict,
    *,
    path_replace: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Istniejący plik audio dla rekordu VDJ (po remapie prefixu użytkownika)."""
    from serato_offline import is_vdj_cache_path
    from serato_parser import resolve_local_audio_path

    fp = (song.get("FilePath") or "").strip()
    if not fp or is_vdj_cache_path(fp):
        return None
    if is_tidal_path(fp) or fp.startswith(("netsearch:", "soundcloud:", "beatport:", "deezer:")):
        return None
    return resolve_local_audio_path(fp, path_replace)


def _local_path_score(song: dict, fp: str) -> int:
    score = 0
    if fp and not fp.lower().endswith(".vdjcache"):
        score += 20
    for key in ("Tags.Title", "Tags.Author", "Tags.Bpm", "Tags.Key", "Tags.Stars"):
        if str(song.get(key) or "").strip():
            score += 1
    score += len(song.get("_children_xml") or [])
    return score


def build_vdj_song_by_path_index(songs: list[dict]) -> dict[str, dict]:
    """FilePath (znormalizowany) → rekord VDJ (najbogatszy przy duplikatach)."""
    out: dict[str, dict] = {}
    for s in songs or []:
        fp = normalize_path((s.get("FilePath") or "").strip())
        if not fp:
            continue
        prev = out.get(fp)
        if not prev or _local_path_score(s, fp) > _local_path_score(prev, fp):
            out[fp] = s
    return out


def build_export_to_song_map(
    songs: list[dict],
    path_substitutes: dict[str, str],
    *,
    path_replace: Optional[dict[str, str]] = None,
) -> dict[str, dict]:
    """
    Ścieżka eksportu Serato (lokalna) → rekord VDJ źródłowy.
    Jeden wpis bazy → jeden plik (bez dopasowania po meta).
    """
    from vdj_streaming import is_serato_tidal_path

    # Lazy import avoids circular import at module load
    from serato_parser import resolve_serato_export_path

    out: dict[str, dict] = {}
    for s in songs or []:
        fp = (s.get("FilePath") or "").strip()
        if not fp:
            continue
        export = resolve_serato_export_path(
            fp,
            path_replace,
            path_substitutes,
            song=s,
        )
        if not export or is_serato_tidal_path(export):
            continue
        key = normalize_path(export)
        prev = out.get(key)
        if not prev or _local_path_score(s, fp) > _local_path_score(prev, fp):
            out[key] = s
    return out


def resolve_vdj_song_export_path(
    song: dict,
    path_substitutes: Optional[dict[str, str]] = None,
    *,
    path_replace: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Ścieżka Serato dla pojedynczego rekordu VDJ (path-first)."""
    from serato_parser import resolve_serato_export_path

    fp = (song.get("FilePath") or "").strip()
    if not fp:
        return None
    return resolve_serato_export_path(
        fp,
        path_replace,
        path_substitutes,
        song=song,
    )


def build_tid_to_resolved_local(
    songs: list[dict],
    *,
    path_replace: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """
    Tidal ID → lokalna ścieżka tylko gdy ten sam rekord VDJ ma FilePath na dysku
    i Link.NetSearch / tid (nie używa related_tracks — to powiązania DJ, nie kopie pliku).
    """
    buckets: dict[str, list[tuple[str, int]]] = {}
    for s in songs or []:
        local = resolve_vdj_local_path(s, path_replace=path_replace)
        if not local:
            continue
        tid = extract_song_tidal_id(s)
        if not tid:
            continue
        score = _local_path_score(s, (s.get("FilePath") or "").strip())
        buckets.setdefault(tid, []).append((local, score))
    return {tid: max(items, key=lambda x: x[1])[0] for tid, items in buckets.items()}


def register_link_and_path_substitutes(
    songs: list[dict],
    substitutes: dict[str, str],
    *,
    path_replace: Optional[dict[str, str]] = None,
) -> dict[str, int]:
    """
    Rejestruje:
    - FilePath → resolve_local(FilePath) dla lokalnych utworów,
    - netsearch/td/streaming aliasy → lokalna ścieżka gdy utwór ma Link.NetSearch.
    """
    from serato_offline import _register_substitute

    stats = {"local_paths": 0, "link_aliases": 0}
    for s in songs or []:
        fp = (s.get("FilePath") or "").strip()
        if not fp:
            continue
        local = resolve_vdj_local_path(s, path_replace=path_replace)
        if local:
            before = len(substitutes)
            _register_substitute(substitutes, fp, local)
            if len(substitutes) > before:
                stats["local_paths"] += 1
        tid = extract_song_tidal_id(s)
        if tid and local:
            before = len(substitutes)
            for alias in (
                f"td{tid}",
                f"netsearch://td{tid}",
                f"streaming://tidal/{tid}",
                f"tidal:tracks:{tid}",
            ):
                _register_substitute(substitutes, alias, local)
            if len(substitutes) > before:
                stats["link_aliases"] += 1
    return stats


def resolve_path_first_export(
    song: dict,
    *,
    manifest_subs: dict[str, str],
    tid_locals: dict[str, str],
    path_replace: Optional[dict[str, str]] = None,
) -> tuple[Optional[str], str]:
    """
    Ścieżka eksportu Serato dla jednego rekordu VDJ.
    Zwraca (path, reason): manifest | local_path | link_local | streaming | unmapped.
    """
    from serato_offline import is_vdj_cache_path, lookup_serato_offline_substitute

    fp = (song.get("FilePath") or "").strip()
    if not fp:
        return None, "unmapped"

    local_direct = resolve_vdj_local_path(song, path_replace=path_replace)
    if local_direct and not is_vdj_cache_path(fp) and not is_tidal_path(fp):
        return local_direct, "local_path"

    tid = extract_song_tidal_id(song)
    if tid:
        manifest = lookup_serato_offline_substitute(f"netsearch://td{tid}", manifest_subs)
        if manifest and Path(manifest).is_file():
            return manifest, "manifest"
        link_local = tid_locals.get(tid)
        if link_local and Path(link_local).is_file():
            return link_local, "link_local"
        if is_vdj_cache_path(fp):
            return f"streaming://tidal/{tid}", "streaming"
        serato = vdj_to_serato_tidal_path(fp)
        if serato:
            return serato, "streaming"

    if is_vdj_cache_path(fp):
        return None, "unmapped"
    return local_direct, "local_path" if local_direct else "unmapped"


def _legacy_meta_substitutes(
    songs: list[dict],
    *,
    min_local_score: float = 70.0,
) -> tuple[dict[str, str], dict]:
    from serato_offline import _build_serato_offline_substitutes_meta_legacy

    return _build_serato_offline_substitutes_meta_legacy(
        songs, min_local_score=min_local_score
    )


def _build_meta_substitutes_legacy(
    songs: list[dict],
    *,
    min_local_score: float = 70.0,
) -> dict[str, str]:
    subs, _ = _legacy_meta_substitutes(songs, min_local_score=min_local_score)
    return subs


def compare_vdj_serato_mapping(
    songs: list[dict],
    *,
    min_local_score: float = 70.0,
) -> dict:
    """
    Porównuje mapowanie meta (legacy) vs path/link (nowe) dla utworów Tidal/cache.
    """
    from serato_offline import is_vdj_cache_path, lookup_serato_offline_substitute
    from vdj_streaming import is_tidal_path

    old_subs, _ = _legacy_meta_substitutes(songs, min_local_score=min_local_score)
    new_subs, new_stats = build_path_first_substitutes(songs)

    discrepancies: list[dict] = []
    same = 0
    checked = 0

    for s in songs or []:
        fp = (s.get("FilePath") or "").strip()
        if not fp:
            continue
        if not (is_tidal_path(fp) or is_vdj_cache_path(fp)):
            continue
        checked += 1
        old_hit = lookup_serato_offline_substitute(fp, old_subs)
        new_hit = lookup_serato_offline_substitute(fp, new_subs)
        if old_hit == new_hit:
            same += 1
            continue
        author = (s.get("Tags.Author") or s.get("Tags.Artist") or "").strip()
        title = (s.get("Tags.Title") or "").strip()
        tid = extract_song_tidal_id(s) or ""
        discrepancies.append(
            {
                "vdj_path": fp,
                "artist": author,
                "title": title,
                "tidal_id": tid,
                "old_export": old_hit or "",
                "new_export": new_hit or "",
                "old_strategy": _guess_strategy(old_hit, tid, "meta"),
                "new_strategy": _guess_strategy(new_hit, tid, "path"),
            }
        )

    return {
        "checked": checked,
        "same": same,
        "discrepancies": discrepancies,
        "discrepancy_count": len(discrepancies),
        "new_stats": new_stats,
    }


def _guess_strategy(export: Optional[str], tid: str, default: str) -> str:
    if not export:
        return "unmapped"
    if export.startswith("streaming:") or export.startswith("tidal:"):
        return "streaming"
    if tid and f"/{tid}" not in export:
        return default
    return default


def build_path_first_substitutes(
    songs: list[dict],
    *,
    path_replace: Optional[dict[str, str]] = None,
    vdj_cache_path: Optional[str] = None,
) -> tuple[dict[str, str], dict]:
    """Nowe mapowanie: manifest (tid) → link/path → streaming."""
    from serato_offline import (
        _parse_vdjcache_artist_title,
        _register_substitute,
        is_vdj_cache_path,
        lookup_serato_offline_substitute,
    )
    from vdj_streaming import is_tidal_path

    try:
        from tidal_download import manifest_substitutes

        manifest_subs = manifest_substitutes()
    except (ImportError, OSError):
        manifest_subs = {}

    substitutes: dict[str, str] = dict(manifest_subs)
    link_stats = register_link_and_path_substitutes(
        songs, substitutes, path_replace=path_replace
    )
    tid_locals = build_tid_to_resolved_local(songs, path_replace=path_replace)

    stats = {
        "tidal_njr_download": 0,
        "tidal_link_local": 0,
        "tidal_local_path": 0,
        "tidal_streaming": 0,
        "cache_njr_download": 0,
        "cache_link_local": 0,
        "cache_tidal_streaming": 0,
        "cache_unmapped": 0,
        "manifest_entries": len(manifest_subs),
        "tid_link_index": len(tid_locals),
        "registered_local_paths": link_stats["local_paths"],
        "registered_link_aliases": link_stats["link_aliases"],
        "mapping": "path_first",
    }

    tidal_songs: list[dict] = []
    cache_songs: list[dict] = []
    for s in songs or []:
        fp = (s.get("FilePath") or "").strip()
        if not fp:
            continue
        if is_vdj_cache_path(fp):
            cache_songs.append(s)
        elif is_tidal_path(fp):
            tidal_songs.append(s)

    for s in tidal_songs:
        fp = (s.get("FilePath") or "").strip()
        export, reason = resolve_path_first_export(
            s,
            manifest_subs=manifest_subs,
            tid_locals=tid_locals,
            path_replace=path_replace,
        )
        if not export:
            continue
        _register_substitute(substitutes, fp, export)
        if reason == "manifest":
            stats["tidal_njr_download"] += 1
        elif reason == "link_local":
            stats["tidal_link_local"] += 1
        elif reason == "local_path":
            stats["tidal_local_path"] += 1
        elif reason == "streaming":
            stats["tidal_streaming"] += 1

    offline_crate_paths: list[str] = []
    seen_crate: set[str] = set()

    for s in cache_songs:
        fp = (s.get("FilePath") or "").strip()
        if not fp or not Path(fp).is_file():
            continue
        tid = extract_song_tidal_id(s)
        manifest = lookup_serato_offline_substitute(
            f"netsearch://td{tid}", manifest_subs
        ) if tid else None
        if manifest and Path(manifest).is_file():
            _register_substitute(substitutes, fp, manifest)
            stats["cache_njr_download"] += 1
            export = manifest
        elif tid:
            link_local = tid_locals.get(tid)
            if link_local and Path(link_local).is_file():
                _register_substitute(substitutes, fp, link_local)
                stats["cache_link_local"] += 1
                export = link_local
            else:
                export = f"streaming://tidal/{tid}"
                _register_substitute(substitutes, fp, export)
                stats["cache_tidal_streaming"] += 1
        else:
            author, title = _parse_vdjcache_artist_title(fp)
            if not author and not title:
                stats["cache_unmapped"] += 1
                continue
            stats["cache_unmapped"] += 1
            continue
        key = normalize_path(export)
        if key not in seen_crate:
            seen_crate.add(key)
            offline_crate_paths.append(export)

    stats["offline_cache_crate_paths"] = len(offline_crate_paths)
    stats["offline_cache_crate_track_paths"] = offline_crate_paths
    stats["vdj_cache_path"] = vdj_cache_path or ""

    try:
        from tidal_download import manifest_tracks

        for _tid, entry in (manifest_tracks() or {}).items():
            path = (entry.get("path") or "").strip()
            if not path or not Path(path).is_file():
                continue
            key = normalize_path(path)
            if key in seen_crate:
                continue
            seen_crate.add(key)
            offline_crate_paths.append(path)
        stats["offline_cache_crate_paths"] = len(offline_crate_paths)
        stats["offline_cache_crate_track_paths"] = offline_crate_paths
    except ImportError:
        pass

    return substitutes, stats
