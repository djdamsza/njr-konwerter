"""
Synchronizacja metadanych i playlist Serato/VDJ → Patriot bez kopiowania plików.

Engine Sync Manager „Export to Drive” kopiuje utwory z Maca na Patriot jako nowe
ścieżki Music/ — podwaja pliki i wpisy w m.db. NJR mapuje istniejące utwory na
Patriot po nazwie pliku i aktualizuje tylko playlisty / cue / beatgrid.
"""
from __future__ import annotations

import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

from engine_libdjinterop import (
    assert_engine_library_safe_for_write,
    assert_engine_schema_compatible,
    backup_engine_database2,
    default_engine_desktop_library,
    diagnose_engine_playlists,
    repair_engine_post_merge,
    run_engine_desktop_merge,
)
from engine_generator import unified_to_engine_export_doc
from engine_stems import (
    DEFAULT_PATRIOT_ENGINE,
    ENGINE_SYNC_LIBRARY_WARNING,
    _pick_best_patriot_candidate,
    index_tracks_by_filename,
    patriot_engine_available,
    remap_unified_db_for_patriot,
)
from unified_model import UnifiedDatabase

# Gdy na Patriot jest już biblioteka — NIE używaj Export to Drive w Sync Manager.
ENGINE_EXPORT_TO_DRIVE_WARNING = (
    "NIE używaj „Export to Drive” / Pack w Sync Manager, gdy Patriot ma już bibliotekę "
    "(Engine Library/Music/). Engine skopiuje te same utwory pod nowymi ścieżkami Music/ "
    "i podwoi pliki oraz wpisy w bazie. "
    "Zamiast tego: Sync Serato → Engine na Macu, potem „Sync playlisty → Patriot” w NJR."
)


def _filename_key(path: str) -> str:
    return unicodedata.normalize("NFC", Path((path or "").replace("\\", "/")).name).lower()


def diagnose_engine_track_duplicates(engine_dir: Path) -> dict:
    """
    Wykrywa duplikaty utworów w m.db (ta sama nazwa pliku / fileBytes).
    Typowy objaw błędnego Export to Drive z Maca na Patriot.
    """
    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    out: dict = {
        "engine_dir": str(engine_dir),
        "ok": True,
        "track_count": 0,
        "duplicate_filename_groups": 0,
        "duplicate_filename_extra_rows": 0,
        "duplicate_file_bytes_groups": 0,
        "duplicate_file_bytes_extra_rows": 0,
        "mac_style_paths": 0,
        "likely_export_duplication": False,
        "samples": [],
        "warnings": [],
    }
    if not mdb.is_file():
        out["ok"] = False
        out["error"] = f"Brak {mdb}"
        return out

    conn = sqlite3.connect(str(mdb))
    try:
        rows = conn.execute(
            "SELECT path, filename, title, artist, fileBytes FROM Track"
        ).fetchall()
    finally:
        conn.close()

    out["track_count"] = len(rows)
    by_fn: dict[str, list] = defaultdict(list)
    by_bytes: dict[int, list] = defaultdict(list)
    mac_style = 0
    for path, fn, title, artist, fb in rows:
        by_fn[fn or _filename_key(path)].append(
            {"path": path, "title": title, "artist": artist, "file_bytes": fb}
        )
        if fb:
            by_bytes[int(fb)].append(path)
        p = (path or "").replace("\\", "/")
        if "POLSKIE-MP3.TK" in p or ("/WWW." in p and "_TK" not in p):
            mac_style += 1

    fn_dupes = {k: v for k, v in by_fn.items() if len(v) > 1}
    byte_dupes = {k: v for k, v in by_bytes.items() if len(v) > 1}
    extra_fn = sum(len(v) - 1 for v in fn_dupes.values())
    extra_bytes = sum(len(v) - 1 for v in byte_dupes.values())

    out["duplicate_filename_groups"] = len(fn_dupes)
    out["duplicate_filename_extra_rows"] = extra_fn
    out["duplicate_file_bytes_groups"] = len(byte_dupes)
    out["duplicate_file_bytes_extra_rows"] = extra_bytes
    out["mac_style_paths"] = mac_style

    if extra_fn > 500 or extra_bytes > 500:
        out["likely_export_duplication"] = True
        out["ok"] = False
        out["warnings"].append(ENGINE_EXPORT_TO_DRIVE_WARNING)

    for fn, entries in sorted(fn_dupes.items(), key=lambda x: -len(x[1]))[:5]:
        out["samples"].append(
            {
                "filename": fn,
                "count": len(entries),
                "paths": [e["path"] for e in entries[:4]],
            }
        )

    return out


def diagnose_patriot_library(patriot_engine: Path | None = None) -> dict:
    """Diagnostyka Patriot: duplikaty + playlisty."""
    target = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()
    dupes = diagnose_engine_track_duplicates(target)
    playlists = diagnose_engine_playlists(target)
    mac = default_engine_desktop_library()
    mac_n = 0
    if (mac / "Database2" / "m.db").is_file():
        conn = sqlite3.connect(str(mac / "Database2" / "m.db"))
        try:
            mac_n = conn.execute("SELECT COUNT(*) FROM Track").fetchone()[0]
        finally:
            conn.close()

    combined_ui_count = mac_n + dupes["track_count"]
    return {
        **dupes,
        "patriot_mounted": patriot_engine_available(target),
        "mac_track_count": mac_n,
        "engine_collection_ui_estimate": combined_ui_count,
        "collection_double_count_explanation": (
            "Engine DJ w widoku Collection sumuje Mac + podłączony Patriot — "
            f"~{mac_n} + ~{dupes['track_count']} ≈ {combined_ui_count} to nie błąd naprawy NJR, "
            "tylko agregacja dwóch bibliotek."
            if mac_n and dupes["track_count"]
            else ""
        ),
        "playlists": playlists,
        "sync_manager_warning": ENGINE_SYNC_LIBRARY_WARNING,
        "export_to_drive_warning": ENGINE_EXPORT_TO_DRIVE_WARNING,
    }


def build_patriot_metadata_export_doc(
    db: UnifiedDatabase,
    patriot_engine: Path,
    *,
    skip_loops: bool = True,
) -> tuple[dict, dict]:
    """
    Export doc dla merge na Patriot — istniejące ścieżki Music/, bez symlinków Mac.
    skip_loops: True (domyślnie) — Engine nie trzyma loopów pewnie; nie wysyłaj ich.
    """
    from dataclasses import replace

    patriot_engine = patriot_engine.resolve()
    remapped, remap_stats = remap_unified_db_for_patriot(db, patriot_engine)
    if not remapped.tracks:
        return {}, {**remap_stats, "error": "Brak utworów zmapowanych na Patriot"}

    tracks = remapped.tracks
    if skip_loops:
        tracks = [replace(t, loops=[]) for t in tracks]
        remapped = replace(remapped, tracks=tracks)
        remap_stats = {**remap_stats, "loops_stripped": True}

    export_doc = unified_to_engine_export_doc(
        remapped,
        engine_dir=patriot_engine,
        merge_mode=True,
        replace_playlist_tracks=True,
        playlist_prefix="",
        cleanup_legacy_vdj_playlists=False,
        prune_tracks_not_in_source=False,
        engine_music_layout=False,
    )
    if not export_doc.get("tracks") and not export_doc.get("playlists"):
        return export_doc, {**remap_stats, "error": "Pusty eksport Patriot"}

    return export_doc, remap_stats


def copy_local_files_to_patriot_music(
    source_files: list[Path | str],
    patriot_engine: Path | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Kopiuje brakujące pliki audio do Patriot Engine Library/Music/{Artist}/{plik}.
    Nie nadpisuje istniejących plików o tej samej nazwie (case-insensitive).
    """
    import shutil

    target = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()
    if not patriot_engine_available(target):
        return {"ok": False, "error": f"Patriot niedostępny: {target}", "copied": 0}

    music = target / "Music"
    music.mkdir(parents=True, exist_ok=True)
    existing = {
        unicodedata.normalize("NFC", p.name).lower(): p
        for p in music.rglob("*")
        if p.is_file() and p.suffix.lower() in {".mp3", ".m4a", ".flac", ".wav", ".aiff", ".aif"}
        and not p.name.startswith("._")
    }

    copied: list[str] = []
    skipped_exists: list[str] = []
    skipped_missing: list[str] = []
    errors: list[str] = []

    for raw in source_files or []:
        src = Path(raw).expanduser()
        if not src.is_file():
            skipped_missing.append(str(src))
            continue
        key = unicodedata.normalize("NFC", src.name).lower()
        if key in existing:
            skipped_exists.append(str(existing[key]))
            continue
        artist_dir = (src.parent.name or "Unknown").strip() or "Unknown"
        dest_dir = music / artist_dir
        dest = dest_dir / src.name
        try:
            if dry_run:
                copied.append(str(dest))
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            existing[key] = dest
            copied.append(str(dest))
        except OSError as e:
            errors.append(f"{src.name}: {e}")

    return {
        "ok": not errors,
        "copied": len(copied),
        "skipped_exists": len(skipped_exists),
        "skipped_missing": len(skipped_missing),
        "errors": errors[:20],
        "copied_paths": copied[:40],
        "dry_run": dry_run,
        "patriot_music": str(music),
    }


def sync_metadata_and_playlists_to_patriot(
    db: UnifiedDatabase,
    patriot_engine: Path | None = None,
    *,
    skip_loops: bool = True,
) -> dict:
    """
    Aktualizuje playlisty i metadane na Patriot bez kopiowania plików audio.
    Wymaga: Engine zamknięty, Patriot podłączony, utwory już na dysku.
    skip_loops: domyślnie True — nie zapisuj loopów do Engine.
    """
    target = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()
    if not patriot_engine_available(target):
        raise FileNotFoundError(f"Patriot niedostępny: {target}")

    assert_engine_library_safe_for_write(target)
    schema = assert_engine_schema_compatible(target)
    export_doc, remap_stats = build_patriot_metadata_export_doc(
        db, target, skip_loops=skip_loops
    )
    if remap_stats.get("error") or not export_doc.get("tracks"):
        err = remap_stats.get("error") or "Brak utworów do sync Patriot"
        raise RuntimeError(err)

    merge_stats = run_engine_desktop_merge(export_doc, target)
    after = diagnose_engine_playlists(target)
    return {
        "ok": True,
        "engine_dir": str(target),
        "patriot_remapped": remap_stats,
        "tracks_in_export": len(export_doc.get("tracks") or []),
        "playlists_in_export": len(export_doc.get("playlists") or []),
        "merge": merge_stats,
        "playlists_after": after,
        "engine_schema": schema.get("schema"),
        "skip_loops": skip_loops,
        "message": (
            f"Patriot: zaktualizowano {len(export_doc.get('tracks') or [])} utworów "
            f"i playlisty (bez kopiowania plików"
            f"{', bez loopów' if skip_loops else ''}). "
            f"Pominięto {remap_stats.get('tracks_skipped_not_on_patriot', 0)} brakujących na dysku."
        ),
    }


def auto_cleanup_patriot_export_duplicates(
    patriot_engine: Path | None = None,
) -> dict | None:
    """
    WYŁĄCZONE — dedupe na Patriot psuje playlisty (osierocone PlaylistEntity).
    Używaj sync_metadata_and_playlists_to_patriot zamiast Export to Drive + dedupe.
    """
    return None


def _track_dedupe_key(filename: str, path: str, file_bytes: int) -> tuple:
    fn = (filename or _filename_key(path)).lower()
    fb = int(file_bytes or 0)
    return (fn, fb) if fb > 0 else (fn,)


def _load_tracks_for_dedupe(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, path, filename, title, artist, fileBytes, isAnalyzed
        FROM Track
        """
    ).fetchall()
    out: list[dict] = []
    for tid, path, fn, title, artist, fb, analyzed in rows:
        out.append(
            {
                "id": int(tid),
                "path": path or "",
                "filename": fn or _filename_key(path or ""),
                "title": title or "",
                "artist": artist or "",
                "file_bytes": int(fb or 0),
                "is_analyzed": bool(analyzed),
            }
        )
    return out


def plan_patriot_dedupe(engine_dir: Path) -> dict:
    """Plan usuwania duplikatów (dry-run) — grupowanie po nazwie pliku + fileBytes."""
    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file():
        return {"ok": False, "error": f"Brak {mdb}"}

    conn = sqlite3.connect(str(mdb))
    try:
        tracks = _load_tracks_for_dedupe(conn)
    finally:
        conn.close()

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for t in tracks:
        groups[_track_dedupe_key(t["filename"], t["path"], t["file_bytes"])].append(t)

    drop_to_keep: dict[int, int] = {}
    keep_paths: dict[int, str] = {}
    drop_paths: dict[int, str] = {}
    files_to_delete: list[str] = []

    for _key, members in groups.items():
        if len(members) < 2:
            continue
        keeper = _pick_best_patriot_candidate(members)
        keep_id = int(keeper["id"])
        keep_paths[keep_id] = keeper["path"]
        for m in members:
            mid = int(m["id"])
            if mid == keep_id:
                continue
            drop_to_keep[mid] = keep_id
            drop_paths[mid] = m["path"]
            if m["path"] != keeper["path"]:
                files_to_delete.append(m["path"])

    return {
        "ok": True,
        "engine_dir": str(engine_dir),
        "track_count_before": len(tracks),
        "duplicate_groups": sum(1 for g in groups.values() if len(g) > 1),
        "tracks_to_remove": len(drop_to_keep),
        "track_count_after": len(tracks) - len(drop_to_keep),
        "files_to_delete": len(files_to_delete),
        "drop_to_keep": drop_to_keep,
        "drop_paths": drop_paths,
        "keep_paths": keep_paths,
        "files_to_delete_paths": files_to_delete[:20],
        "all_files_to_delete": files_to_delete,
        "samples": [
            {
                "keep_id": keep_id,
                "keep_path": keep_paths.get(keep_id),
                "drop_ids": [d for d, k in drop_to_keep.items() if k == keep_id][:3],
            }
            for keep_id in list({v for v in drop_to_keep.values()})[:5]
        ],
    }


def dedupe_patriot_library(
    patriot_engine: Path | None = None,
    *,
    dry_run: bool = True,
    delete_files: bool = False,
) -> dict:
    """
    Usuwa duplikaty utworów po Export to Drive (ta sama nazwa pliku + fileBytes).
    Zachowuje najlepszy wpis (analyzed, bez „ (2)”, bez Unknown Album).
    """
    target = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()
    if not patriot_engine_available(target):
        raise FileNotFoundError(f"Patriot niedostępny: {target}")

    plan = plan_patriot_dedupe(target)
    if not plan.get("ok"):
        raise RuntimeError(plan.get("error") or "Plan dedupe failed")
    if plan["tracks_to_remove"] == 0:
        return {
            **plan,
            "dry_run": dry_run,
            "message": "Brak duplikatów do usunięcia na Patriot.",
        }

    if dry_run:
        return {
            **plan,
            "dry_run": True,
            "message": (
                f"Patriot: do usunięcia {plan['tracks_to_remove']} duplikatów "
                f"(zostanie {plan['track_count_after']} utworów). "
                f"Pliki audio do skasowania: {plan['files_to_delete']}. "
                f"Uruchom ponownie z dryRun=false aby wykonać."
            ),
        }

    assert_engine_library_safe_for_write(target)
    backup_stats = backup_engine_database2(target, label="pre-dedupe")
    drop_to_keep: dict[int, int] = plan["drop_to_keep"]
    keep_paths: dict[int, str] = plan["keep_paths"]
    mdb = target / "Database2" / "m.db"

    conn = sqlite3.connect(str(mdb))
    pe_remapped = 0
    pe_dropped = 0
    tracks_removed = 0
    files_deleted = 0
    bytes_freed = 0

    try:
        conn.execute("PRAGMA foreign_keys=ON")
        cols_pe = {r[1] for r in conn.execute("PRAGMA table_info(PlaylistEntity)")}
        has_uuid = "databaseUuid" in cols_pe
        local_uuid = None
        if has_uuid:
            row = conn.execute("SELECT uuid FROM Information LIMIT 1").fetchone()
            local_uuid = str(row[0]) if row and row[0] else None

        for drop_id, keep_id in drop_to_keep.items():
            if has_uuid and local_uuid:
                rows = conn.execute(
                    "SELECT id, listId FROM PlaylistEntity WHERE trackId = ?",
                    (drop_id,),
                ).fetchall()
                for pe_id, list_id in rows:
                    exists = conn.execute(
                        """
                        SELECT id FROM PlaylistEntity
                        WHERE listId = ? AND trackId = ? AND databaseUuid = ?
                        LIMIT 1
                        """,
                        (list_id, keep_id, local_uuid),
                    ).fetchone()
                    if exists:
                        conn.execute("DELETE FROM PlaylistEntity WHERE id = ?", (pe_id,))
                        pe_dropped += 1
                    else:
                        conn.execute(
                            """
                            UPDATE PlaylistEntity
                            SET trackId = ?, databaseUuid = ?
                            WHERE id = ?
                            """,
                            (keep_id, local_uuid, pe_id),
                        )
                        pe_remapped += 1
            else:
                rows = conn.execute(
                    "SELECT id, listId FROM PlaylistEntity WHERE trackId = ?",
                    (drop_id,),
                ).fetchall()
                for pe_id, list_id in rows:
                    exists = conn.execute(
                        "SELECT id FROM PlaylistEntity WHERE listId = ? AND trackId = ? LIMIT 1",
                        (list_id, keep_id),
                    ).fetchone()
                    if exists:
                        conn.execute("DELETE FROM PlaylistEntity WHERE id = ?", (pe_id,))
                        pe_dropped += 1
                    else:
                        conn.execute(
                            "UPDATE PlaylistEntity SET trackId = ? WHERE id = ?",
                            (keep_id, pe_id),
                        )
                        pe_remapped += 1

            conn.execute("DELETE FROM PerformanceData WHERE trackId = ?", (drop_id,))
            conn.execute("DELETE FROM Track WHERE id = ?", (drop_id,))
            tracks_removed += 1

        conn.commit()
    finally:
        conn.close()

    repair_stats = repair_engine_post_merge(target)

    if delete_files:
        for rel_path in plan.get("all_files_to_delete") or []:
            fp = target / rel_path.replace("\\", "/")
            if not fp.is_file() or fp.is_symlink():
                continue
            try:
                sz = fp.stat().st_size
                fp.unlink()
                files_deleted += 1
                bytes_freed += sz
            except OSError:
                continue

    after = diagnose_engine_track_duplicates(target)
    return {
        **plan,
        "dry_run": False,
        "delete_files": delete_files,
        "tracks_removed": tracks_removed,
        "playlist_entities_remapped": pe_remapped,
        "playlist_entities_dropped": pe_dropped,
        "files_deleted": files_deleted,
        "bytes_freed": bytes_freed,
        "bytes_freed_mb": round(bytes_freed / (1024 * 1024), 1),
        "engine_backup": backup_stats,
        "repair": repair_stats,
        "track_count_after_actual": after.get("track_count"),
        "duplicate_filename_extra_rows_after": after.get("duplicate_filename_extra_rows"),
        "message": (
            f"Patriot: usunięto {tracks_removed} duplikatów utworów. "
            f"Zostało ~{after.get('track_count')} wpisów. "
            f"{'Skasowano ' + str(files_deleted) + ' plików (' + str(round(bytes_freed/(1024*1024),1)) + ' MB).' if delete_files else 'Pliki audio na dysku nietknięte (deleteFiles=false).'}"
        ),
    }
