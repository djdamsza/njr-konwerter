"""
Serato export: Tidal / VDJ cache → odtwarzalne ścieżki (mp3/m4a lub tidal:tracks:ID).

Pliki .vdjcache są szyfrowanym cache VirtualDJ — Serato ich nie odtwarza.
Strategia: dopasuj lokalny plik audio z bazy VDJ; inaczej tidal:tracks:ID (Serato 4+ streaming).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional

from vdjfolder import normalize_path
from vdj_streaming import (
    extract_tidal_id,
    is_serato_tidal_path,
    is_tidal_path,
    vdj_to_serato_tidal_path,
)

_LOCAL_AUDIO_EXT = frozenset({".mp3", ".m4a", ".mp4", ".wav", ".flac", ".ogg", ".aac"})


def is_vdj_cache_path(path: str) -> bool:
    return bool(path and str(path).strip().lower().endswith(".vdjcache"))


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", str(s or "").strip().lower())


def _artist_words(artist: str) -> set[str]:
    a = _norm(artist)
    a = re.sub(r"\s*feat\.?\s*.*$", "", a, flags=re.I)
    a = re.sub(r"\s*ft\.?\s*.*$", "", a, flags=re.I)
    return {w for w in re.split(r"[\s,&/+\-]+", a) if len(w) > 1}


def _title_core(title: str) -> str:
    t = _norm(title)
    t = re.sub(r"\s*\([^)]*\)\s*", " ", t)
    t = re.sub(r"\s*\[[^\]]*\]\s*", " ", t)
    return " ".join(t.split())


def _song_meta(s: dict) -> tuple[str, str, float]:
    author = _norm(s.get("Tags.Author") or s.get("Tags.Artist") or "")
    title = _norm(s.get("Tags.Title") or "")
    raw_len = s.get("Infos.SongLength") or s.get("Infos.Duration") or ""
    try:
        length = float(raw_len) if raw_len not in ("", None) else 0.0
    except (TypeError, ValueError):
        length = 0.0
    return author, title, length


def match_songs_for_local_substitute(query: dict, candidate: dict) -> tuple[float, str]:
    """Score 0–100 + confidence (high/low/reject). Uproszczony wariant online-match."""
    oa, ot, od = _song_meta(query)
    ca, ct, cd = _song_meta(candidate)
    oa_words = _artist_words(oa)
    ca_words = _artist_words(ca)
    ot_core = _title_core(ot)
    ct_core = _title_core(ct)

    artist_overlap = bool(oa_words & ca_words)
    main_match = False
    if oa and ca:
        oa_first = oa.split(",")[0].split(" feat")[0].strip()
        ca_first = ca.split(",")[0].split(" feat")[0].strip()
        if oa_first and (oa_first == ca_first or oa_first in ca_first or ca_first in oa_first):
            main_match = True
        if oa_words and ca_words and not artist_overlap and not main_match:
            return 0.0, "reject"

    ot_words = set(ot_core.split())
    ct_words = set(ct_core.split())
    title_overlap = bool(ot_words & ct_words) or (ot_core in ct_core or ct_core in ot_core)
    if ot and ct and not title_overlap:
        return 0.0, "reject"
    if title_overlap and oa_words and ca_words and not artist_overlap and not main_match:
        return 0.0, "reject"

    score = 0.0
    if oa and ca:
        if oa == ca or main_match:
            score += 45
        elif artist_overlap:
            score += 30
        elif oa in ca or ca in oa:
            score += 25
    if ot and ct:
        if ot == ct or ot_core == ct_core:
            score += 45
        elif ot in ct or ct in ot:
            score += 25
        elif title_overlap:
            score += 15
    if od and cd and cd > 0:
        diff = abs(od - cd)
        if diff < 2:
            score += 10
        elif diff < 5:
            score += 5
        elif diff < 10:
            score += 2
    score = min(100.0, score)
    if score >= 70 and (artist_overlap or main_match) and title_overlap:
        confidence = "high"
    elif score >= 55 and title_overlap:
        confidence = "low"
    else:
        confidence = "reject"
    return score, confidence


def _is_local_audio_path(path: str) -> bool:
    p = (path or "").strip()
    if not p or is_tidal_path(p) or is_vdj_cache_path(p):
        return False
    if p.startswith(("netsearch:", "soundcloud:", "beatport:", "deezer:")):
        return False
    ext = Path(p).suffix.lower()
    return ext in _LOCAL_AUDIO_EXT


def _register_substitute(out: dict[str, str], vdj_path: str, export_path: str) -> None:
    if not vdj_path or not export_path:
        return
    out[normalize_path(vdj_path)] = export_path
    tid = extract_tidal_id(vdj_path)
    if tid:
        for alias in (
            f"td{tid}",
            f"netsearch://td{tid}",
            f"streaming://tidal/{tid}",
            f"tidal:tracks:{tid}",
        ):
            out[normalize_path(alias)] = export_path


def _parse_vdjcache_artist_title(path: str) -> tuple[str, str]:
    """'…/Cher - Strong Enough.vdjcache' → ('cher', 'strong enough')."""
    stem = Path((path or "").replace("\\", "/")).stem
    if " - " in stem:
        a, t = stem.split(" - ", 1)
        return a.strip().lower(), t.strip().lower()
    return "", stem.strip().lower()


def _build_manifest_meta_index() -> dict[tuple[str, str], str]:
    """(author, title) → lokalna ścieżka NJR z manifestu."""
    try:
        from tidal_download import manifest_tracks
    except ImportError:
        return {}
    out: dict[tuple[str, str], str] = {}
    for _tid, entry in (manifest_tracks() or {}).items():
        path = (entry.get("path") or "").strip()
        if not path or not Path(path).is_file():
            continue
        author = (entry.get("artist") or entry.get("author") or "").strip().lower()
        title = (entry.get("title") or "").strip().lower()
        if author or title:
            out[(author, title)] = path
        fa, ft = _parse_vdjcache_artist_title(path)
        if (fa or ft) and (fa, ft) not in out:
            out[(fa, ft)] = path
    return out


def _best_local_match(query: dict, local_songs: list[dict], *, min_score: float) -> Optional[str]:
    best_path: Optional[str] = None
    best_score = 0.0
    for cand in local_songs:
        fp = (cand.get("FilePath") or "").strip()
        if not fp or not Path(fp).is_file():
            continue
        score, confidence = match_songs_for_local_substitute(query, cand)
        if confidence == "reject" or score < min_score:
            continue
        if score > best_score:
            best_score = score
            best_path = fp
    return best_path


def build_serato_offline_substitutes(
    songs: list[dict],
    *,
    min_local_score: float = 70.0,
    vdj_cache_path: Optional[str] = None,
) -> tuple[dict[str, str], dict]:
    """
    Mapuje ścieżki VDJ (Tidal, cache) na odtwarzalne w Serato:
    - manifest NJR po Tidal ID,
    - lokalny FilePath / Link.NetSearch (path-first, bez meta-fuzzy),
    - streaming://tidal/ID gdy brak pliku.
    Nigdy .vdjcache.
    """
    from vdj_path_mapping import build_path_first_substitutes

    _ = min_local_score  # legacy param — meta-fuzzy usunięte
    return build_path_first_substitutes(
        songs,
        vdj_cache_path=vdj_cache_path,
    )


def _build_serato_offline_substitutes_meta_legacy(
    songs: list[dict],
    *,
    min_local_score: float = 70.0,
    vdj_cache_path: Optional[str] = None,
) -> tuple[dict[str, str], dict]:
    """Stara implementacja (meta) — tylko do porównań w testach."""
    from file_analyzer import is_streaming

    try:
        from tidal_download import manifest_substitutes

        manifest_subs = manifest_substitutes()
    except (ImportError, OSError):
        manifest_subs = {}

    local_songs: list[dict] = []
    tidal_songs: list[dict] = []
    cache_songs: list[dict] = []
    tidal_by_meta: dict[tuple[str, str], str] = {}

    for s in songs or []:
        fp = (s.get("FilePath") or "").strip()
        if not fp:
            continue
        if is_vdj_cache_path(fp):
            cache_songs.append(s)
            continue
        if is_tidal_path(fp) or is_streaming(fp):
            tidal_songs.append(s)
            tid = extract_tidal_id(fp)
            if tid:
                author, title, _ = _song_meta(s)
                if author or title:
                    tidal_by_meta[(author, title)] = tid
            continue
        if _is_local_audio_path(fp) and Path(fp).is_file():
            local_songs.append(s)

    substitutes: dict[str, str] = dict(manifest_subs)
    manifest_by_meta = _build_manifest_meta_index()
    # Szybkie dopasowanie 1:1 po (artist, title) — bez O(tidal×local)
    local_by_meta: dict[tuple[str, str], str] = {}
    for s in local_songs:
        a, t, _ = _song_meta(s)
        if not a and not t:
            continue
        fp_local = (s.get("FilePath") or "").strip()
        if fp_local:
            local_by_meta.setdefault((a, t), fp_local)
            # też po samym rdzeniu tytułu + artyście
            tc = _title_core(t)
            if tc and tc != t:
                local_by_meta.setdefault((a, tc), fp_local)

    stats = {
        "tidal_njr_download": 0,
        "tidal_local_substitute": 0,
        "tidal_streaming": 0,
        "cache_njr_download": 0,
        "cache_local_substitute": 0,
        "cache_tidal_streaming": 0,
        "cache_unmapped": 0,
        "offline_cache_crate_paths": 0,
        "manifest_entries": len(manifest_subs),
        "manifest_meta_entries": len(manifest_by_meta),
        "local_meta_index": len(local_by_meta),
    }
    # Dopasowanie „ten sam utwór lokalnie” to O(tidal × local) — przy dużej bazie trwa wiele minut.
    fuzzy_ok = len(tidal_songs) * max(1, len(local_songs)) <= 250_000
    stats["fuzzy_local_match"] = fuzzy_ok

    def _manifest_path_for_tid(tid: Optional[str]) -> Optional[str]:
        if not tid:
            return None
        hit = manifest_subs.get(normalize_path(f"netsearch://td{tid}"))
        if hit and Path(hit).is_file():
            return hit
        return None

    def _manifest_path_for_meta(author: str, title: str) -> Optional[str]:
        if not author and not title:
            return None
        hit = manifest_by_meta.get((author, title))
        if hit and Path(hit).is_file():
            return hit
        return None

    def _exact_local_path(author: str, title: str) -> Optional[str]:
        if not author and not title:
            return None
        hit = local_by_meta.get((author, title))
        if hit and Path(hit).is_file():
            return hit
        tc = _title_core(title)
        if tc:
            hit = local_by_meta.get((author, tc))
            if hit and Path(hit).is_file():
                return hit
        return None

    for s in tidal_songs:
        fp = (s.get("FilePath") or "").strip()
        tid = extract_tidal_id(fp)
        author, title, _ = _song_meta(s)
        manifest_path = _manifest_path_for_tid(tid) or _manifest_path_for_meta(author, title)
        if manifest_path:
            _register_substitute(substitutes, fp, manifest_path)
            stats["tidal_njr_download"] += 1
            continue
        local = _exact_local_path(author, title)
        if not local and fuzzy_ok:
            local = _best_local_match(s, local_songs, min_score=min_local_score)
        if local:
            _register_substitute(substitutes, fp, local)
            stats["tidal_local_substitute"] += 1
        else:
            serato = vdj_to_serato_tidal_path(fp)
            if serato:
                _register_substitute(substitutes, fp, serato)
                stats["tidal_streaming"] += 1

    offline_crate_paths: list[str] = []
    seen_crate: set[str] = set()

    for s in cache_songs:
        fp = (s.get("FilePath") or "").strip()
        if not fp or not Path(fp).is_file():
            continue
        tid = extract_tidal_id(fp) or None
        author, title, _ = _song_meta(s)
        if not tid:
            tid = tidal_by_meta.get((author, title))
        if not author and not title:
            author, title = _parse_vdjcache_artist_title(fp)
        manifest_path = (
            _manifest_path_for_tid(tid)
            or _manifest_path_for_meta(author, title)
        )
        if manifest_path:
            _register_substitute(substitutes, fp, manifest_path)
            stats["cache_njr_download"] += 1
            export = manifest_path
        elif tid:
            export = f"streaming://tidal/{tid}"
            _register_substitute(substitutes, fp, export)
            stats["cache_tidal_streaming"] += 1
        else:
            local = _exact_local_path(author, title)
            if not local and fuzzy_ok:
                local = _best_local_match(s, local_songs, min_score=min_local_score)
            if local:
                _register_substitute(substitutes, fp, local)
                stats["cache_local_substitute"] += 1
                export = local
            else:
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


def lookup_serato_offline_substitute(
    path: str,
    substitutes: Optional[dict[str, str]],
) -> Optional[str]:
    if not path or not substitutes:
        return None
    key = normalize_path(path.strip())
    hit = substitutes.get(key)
    if hit:
        return hit
    tid = extract_tidal_id(path)
    if tid:
        for alias in (
            f"td{tid}",
            f"netsearch://td{tid}",
            f"streaming://tidal/{tid}",
            f"tidal:tracks:{tid}",
        ):
            hit = substitutes.get(normalize_path(alias))
            if hit:
                return hit
    return None
