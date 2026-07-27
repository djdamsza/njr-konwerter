"""
Skan Tidal w bazie VDJ: online vs cache (.vdjcache) + mapowanie tidal track ID.
"""
from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from vdj_streaming import extract_tidal_id, get_path_status, is_tidal_path, is_vdj_cache_path


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", str(s or "").strip().lower())


def _meta(s: dict) -> tuple[str, str, float]:
    author = _norm(s.get("Tags.Author") or s.get("Tags.Artist") or "")
    title = _norm(s.get("Tags.Title") or "")
    raw = s.get("Infos.SongLength") or s.get("Infos.Duration") or ""
    try:
        length = float(raw) if raw not in ("", None) else 0.0
    except (TypeError, ValueError):
        length = 0.0
    return author, title, length


def extract_netsearch_link(s: dict) -> Optional[str]:
    """Tidal ID z <Link NetSearch="td123" /> w _children_xml."""
    for xml_str in s.get("_children_xml") or []:
        if "NetSearch" not in xml_str:
            continue
        try:
            el = ET.fromstring(xml_str)
        except ET.ParseError:
            continue
        if el.tag != "Link":
            continue
        raw = (el.get("NetSearch") or "").strip()
        if not raw:
            continue
        if raw.lower().startswith("td") and raw[2:].isdigit():
            return raw[2:]
        if raw.isdigit():
            return raw
    return None


def default_vdj_cache_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "VirtualDJ" / "Cache"


def _index_disk_cache(cache_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """tid -> path, norm_stem -> path."""
    by_tid: dict[str, str] = {}
    by_stem: dict[str, str] = {}
    if not cache_dir.is_dir():
        return by_tid, by_stem
    for f in cache_dir.glob("*.vdjcache"):
        if not f.is_file():
            continue
        p = str(f)
        stem = f.stem
        if stem.lower().startswith("td") and stem[2:].isdigit():
            by_tid[stem[2:]] = p
        by_stem[_norm(stem)] = p
    return by_tid, by_stem


def resolve_vdjcache_path(
    *,
    tidal_id: Optional[str],
    author: str,
    title: str,
    cache_dir: Path,
    disk_by_tid: dict[str, str],
    disk_by_stem: dict[str, str],
    cache_db_by_meta: dict[tuple[str, str], str],
) -> Optional[str]:
    if tidal_id and tidal_id in disk_by_tid and Path(disk_by_tid[tidal_id]).is_file():
        return disk_by_tid[tidal_id]
    key = _norm(f"{author} - {title}")
    if key in disk_by_stem and Path(disk_by_stem[key]).is_file():
        return disk_by_stem[key]
    meta_key = (_norm(author), _norm(title))
    db_path = cache_db_by_meta.get(meta_key)
    if db_path and Path(db_path).is_file():
        return db_path
    if tidal_id:
        for name in (f"td{tidal_id}.vdjcache", f"{tidal_id}.vdjcache"):
            cand = cache_dir / name
            if cand.is_file():
                return str(cand)
    return None


def scan_tidal_cache_entries(
    songs: list[dict],
    *,
    vdj_cache_path: Optional[str] = None,
    manifest_tracks: Optional[dict] = None,
) -> dict:
    """
    Zwraca listę utworów Tidal z statusem online/cache/pobrany oraz statystyki.
    """
    cache_dir = Path(vdj_cache_path).expanduser() if vdj_cache_path else default_vdj_cache_dir()
    disk_by_tid, disk_by_stem = _index_disk_cache(cache_dir)
    manifest_tracks = manifest_tracks or {}

    cache_db_by_meta: dict[tuple[str, str], str] = {}
    tidal_rows: list[dict] = []
    seen_tid: set[str] = set()

    for idx, s in enumerate(songs or []):
        fp = (s.get("FilePath") or "").strip()
        if not fp:
            continue
        author_raw = (s.get("Tags.Author") or s.get("Tags.Artist") or "").strip()
        title_raw = (s.get("Tags.Title") or "").strip()
        author, title, length = _meta(s)

        if is_vdj_cache_path(fp):
            if Path(fp).is_file():
                cache_db_by_meta[(author, title)] = fp
            tid = extract_tidal_id(fp) or extract_netsearch_link(s)
            if not tid:
                # dopasuj do istniejącego tidal po meta później
                continue
            if tid in seen_tid:
                continue
            seen_tid.add(tid)
            vdjcache = fp if Path(fp).is_file() else resolve_vdjcache_path(
                tidal_id=tid,
                author=author_raw,
                title=title_raw,
                cache_dir=cache_dir,
                disk_by_tid=disk_by_tid,
                disk_by_stem=disk_by_stem,
                cache_db_by_meta=cache_db_by_meta,
            )
            tidal_rows.append(_entry(
                idx, tid, author_raw, title_raw, length,
                vdj_path=f"netsearch://td{tid}",
                vdjcache_path=vdjcache,
                cached=bool(vdjcache),
                source="cache_db",
                manifest_tracks=manifest_tracks,
            ))
            continue

        if not is_tidal_path(fp):
            continue

        tid = extract_tidal_id(fp) or extract_netsearch_link(s)
        if not tid or tid in seen_tid:
            continue
        seen_tid.add(tid)

        vdjcache = resolve_vdjcache_path(
            tidal_id=tid,
            author=author_raw,
            title=title_raw,
            cache_dir=cache_dir,
            disk_by_tid=disk_by_tid,
            disk_by_stem=disk_by_stem,
            cache_db_by_meta=cache_db_by_meta,
        )
        if not vdjcache:
            status = get_path_status(fp, str(cache_dir))
            if status == "offline":
                vdjcache = resolve_vdjcache_path(
                    tidal_id=tid,
                    author=author_raw,
                    title=title_raw,
                    cache_dir=cache_dir,
                    disk_by_tid=disk_by_tid,
                    disk_by_stem=disk_by_stem,
                    cache_db_by_meta=cache_db_by_meta,
                )

        tidal_rows.append(_entry(
            idx, tid, author_raw, title_raw, length,
            vdj_path=fp,
            vdjcache_path=vdjcache,
            cached=bool(vdjcache),
            source="tidal",
            manifest_tracks=manifest_tracks,
        ))

    # cache-only bez tidal ID — spróbuj dopisać po meta z tidal_rows
    tidal_by_meta = {( _norm(r["author"]), _norm(r["title"]) ): r["tidalId"] for r in tidal_rows}
    for idx, s in enumerate(songs or []):
        fp = (s.get("FilePath") or "").strip()
        if not is_vdj_cache_path(fp) or not Path(fp).is_file():
            continue
        author_raw = (s.get("Tags.Author") or s.get("Tags.Artist") or "").strip()
        title_raw = (s.get("Tags.Title") or "").strip()
        author, title, length = _meta(s)
        tid = extract_tidal_id(fp) or extract_netsearch_link(s) or tidal_by_meta.get((author, title))
        if not tid or tid in seen_tid:
            continue
        seen_tid.add(tid)
        tidal_rows.append(_entry(
            idx, tid, author_raw, title_raw, length,
            vdj_path=f"netsearch://td{tid}",
            vdjcache_path=fp,
            cached=True,
            source="cache_only",
            manifest_tracks=manifest_tracks,
        ))

    tidal_rows.sort(key=lambda r: (not r["cached"], r["author"].lower(), r["title"].lower()))

    used_cache_paths = {r["vdjcachePath"] for r in tidal_rows if r.get("vdjcachePath")}
    tidal_by_meta_full: dict[tuple[str, str], str] = {}
    for idx, s in enumerate(songs or []):
        fp = (s.get("FilePath") or "").strip()
        if not is_tidal_path(fp):
            continue
        tid = extract_tidal_id(fp) or extract_netsearch_link(s)
        if not tid:
            continue
        author, title, _ = _meta(s)
        if author or title:
            tidal_by_meta_full[(author, title)] = tid

    disk_orphans = 0
    for path in disk_by_stem.values():
        if path in used_cache_paths:
            continue
        stem = Path(path).stem
        if " - " in stem:
            author_raw, title_raw = stem.split(" - ", 1)
            author_raw, title_raw = author_raw.strip(), title_raw.strip()
        else:
            author_raw, title_raw = "", stem.strip()
        author, title, _ = _meta({"Tags.Author": author_raw, "Tags.Title": title_raw})
        tid = extract_tidal_id(path) or tidal_by_meta_full.get((author, title))
        if tid and tid in seen_tid:
            # uzupełnij istniejący wpis ścieżką cache jeśli brak
            for row in tidal_rows:
                if row["tidalId"] == tid and not row.get("vdjcachePath"):
                    row["vdjcachePath"] = path
                    row["cached"] = True
                    row["cacheStatus"] = "cached"
                    if row.get("downloadStatus") == "not_applicable":
                        row["downloadStatus"] = "pending"
                    used_cache_paths.add(path)
                    break
            continue
        if not tid:
            disk_orphans += 1
            pseudo = f"disk:{_norm(stem)}"
            if pseudo in seen_tid:
                continue
            seen_tid.add(pseudo)
            tidal_rows.append(_entry(
                -1,
                "",
                author_raw,
                title_raw,
                0.0,
                vdj_path=path,
                vdjcache_path=path,
                cached=True,
                source="disk_orphan",
                manifest_tracks=manifest_tracks,
            ))
            used_cache_paths.add(path)
            continue
        seen_tid.add(tid)
        tidal_rows.append(_entry(
            -1,
            tid,
            author_raw,
            title_raw,
            0.0,
            vdj_path=f"netsearch://td{tid}",
            vdjcache_path=path,
            cached=True,
            source="disk_only",
            manifest_tracks=manifest_tracks,
        ))
        used_cache_paths.add(path)

    tidal_rows.sort(key=lambda r: (not r["cached"], r["author"].lower(), r["title"].lower()))

    cached = [r for r in tidal_rows if r["cached"]]
    downloaded = [r for r in tidal_rows if r["downloadStatus"] == "downloaded"]
    failed_removed = [r for r in tidal_rows if r.get("downloadErrorKind") == "tidal_removed"]
    orphans_no_id = [r for r in tidal_rows if r.get("downloadErrorKind") == "no_tidal_id" or (r.get("cached") and not r.get("tidalId"))]
    stats = {
        "total_tidal": len(tidal_rows),
        "cached_vdj": len(cached),
        "online_only": len(tidal_rows) - len(cached),
        "downloaded_njr": len(downloaded),
        "pending_download": len([r for r in cached if r["downloadStatus"] == "pending"]),
        "failed_tidal_removed": len(failed_removed),
        "orphans_no_tidal_id": len(orphans_no_id),
        "cache_dir": str(cache_dir),
        "disk_cache_files": len(list(cache_dir.glob("*.vdjcache"))) if cache_dir.is_dir() else 0,
        "disk_orphans_no_id": disk_orphans,
    }
    return {"entries": tidal_rows, "stats": stats}


def _download_error_kind(err: str, *, has_tidal_id: bool) -> str:
    if not has_tidal_id:
        return "no_tidal_id"
    e = (err or "").lower()
    if "404" in e or "usunięty z tidal" in e or "not found" in e:
        return "tidal_removed"
    if "login" in e:
        return "auth"
    if err:
        return "download_failed"
    return ""


def _entry(
    song_idx: int,
    tidal_id: str,
    author: str,
    title: str,
    length: float,
    *,
    vdj_path: str,
    vdjcache_path: Optional[str],
    cached: bool,
    source: str,
    manifest_tracks: dict,
) -> dict:
    m = manifest_tracks.get(str(tidal_id)) or {}
    local_path = (m.get("path") or "").strip()
    if local_path and Path(local_path).is_file():
        dl_status = "downloaded"
    elif m.get("error"):
        dl_status = "error"
    elif local_path:
        dl_status = "missing_file"
    elif cached:
        dl_status = "pending"
    else:
        dl_status = "not_applicable"

    err_text = m.get("error") or ""
    err_kind = _download_error_kind(err_text, has_tidal_id=bool(str(tidal_id).strip()))

    return {
        "songIdx": song_idx,
        "tidalId": str(tidal_id),
        "author": author,
        "title": title,
        "length": length,
        "vdjPath": vdj_path,
        "vdjcachePath": vdjcache_path or "",
        "cached": cached,
        "cacheStatus": "cached" if cached else "online",
        "source": source,
        "localPath": local_path,
        "downloadStatus": dl_status,
        "downloadError": err_text,
        "downloadErrorKind": err_kind if dl_status == "error" else ("no_tidal_id" if cached and not str(tidal_id).strip() else ""),
        "downloadedAt": m.get("downloaded_at") or "",
        "tidalUrl": f"https://tidal.com/browse/track/{tidal_id}",
    }
