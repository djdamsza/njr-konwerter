"""
Automatyzacja stemów Engine DJ: status, playlista partii, migracja Mac → Patriot.

Stemy to pliki ``{trackId} {databaseUuid}.stems`` w folderze ``Stems/``.
Na Patriot (po eksporcie z Mac) w nazwie pliku zostaje UUID biblioteki Mac,
ale ``trackId`` musi odpowiadać utworowi w bibliotece Patriot.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
import unicodedata
from pathlib import Path

from engine_libdjinterop import default_engine_desktop_library, is_engine_desktop_running

DEFAULT_PATRIOT_ENGINE = Path("/Volumes/Patriot/Engine Library")
STEMS_BATCH_PLAYLIST = "NJR Stems Batch"
STEMS_BATCH_PARENT = "NJR"
SQLITE_BUSY_TIMEOUT_SEC = 60

# Ostrzeżenie Engine DJ Sync Manager (Export Stems + wybrana playlista).
ENGINE_SYNC_STEMS_WARNING = (
    "NIE używaj „Export Stems” w Sync Manager przy synchronizacji pojedynczej playlisty. "
    "Engine usuwa stemy na dysku Rane, których nie ma w kolekcji desktopowej dla eksportowanych utworów — "
    "nawet jeśli chcesz je tylko „przenieść”. Użyj migracji NJR (Przenieś na Patriot) zamiast Sync Manager."
)

# Export to Drive na istniejącym Patriot podwaja biblioteke — playlisty przez NJR.
ENGINE_SYNC_LIBRARY_WARNING = (
    "NIE używaj „Export to Drive” w Sync Manager gdy Patriot ma już Engine Library/Music/. "
    "Workflow NJR: Sync Serato → Engine (Mac + Patriot automatycznie gdy dysk podłączony)."
)


def _norm_path(path: str) -> str:
    return (path or "").replace("\\", "/")


def _filename_key(path: str) -> str:
    # NFC: macOS (NFD) vs Serato/Linux (NFC) — ta sama litera „ę” to inne bajty.
    return unicodedata.normalize("NFC", Path(_norm_path(path)).name).lower()


def _open_engine_mdb(mdb: Path, *, readonly: bool = True) -> sqlite3.Connection:
    """Połączenie z m.db — read-only + długi busy_timeout (Engine DJ trzyma lock)."""
    mdb = mdb.resolve()
    if readonly:
        uri = f"file:{mdb.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=SQLITE_BUSY_TIMEOUT_SEC)
    else:
        conn = sqlite3.connect(str(mdb), timeout=SQLITE_BUSY_TIMEOUT_SEC)
    conn.execute(f"PRAGMA busy_timeout = {int(SQLITE_BUSY_TIMEOUT_SEC * 1000)}")
    return conn


def _with_db_retry(fn, *, attempts: int = 8, delay_sec: float = 0.5):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except sqlite3.OperationalError as ex:
            last = ex
            if "locked" not in str(ex).lower() and "busy" not in str(ex).lower():
                raise
            time.sleep(delay_sec * (1 + i * 0.25))
    if last:
        raise last
    raise RuntimeError("DB retry failed")


def infer_library_uuid_from_stems(stems_dir: Path) -> str | None:
    """UUID biblioteki z nazwy pliku .stems (bez odczytu m.db)."""
    stems_dir = stems_dir.resolve()
    if not stems_dir.is_dir():
        return None
    for entry in stems_dir.glob("*.stems"):
        head = entry.name[: -len(".stems")]
        space = head.rfind(" ")
        if space <= 0:
            continue
        track_part = head[:space]
        uuid_part = head[space + 1 :]
        if track_part.isdigit() and len(uuid_part) >= 32:
            return uuid_part
    return None


def get_library_uuid(engine_dir: Path) -> str:
    mdb = engine_dir.resolve() / "Database2" / "m.db"
    stems_uuid = infer_library_uuid_from_stems(engine_dir / "Stems")
    if stems_uuid:
        return stems_uuid

    def _read() -> str:
        conn = _open_engine_mdb(mdb, readonly=True)
        try:
            row = conn.execute("SELECT uuid FROM Information LIMIT 1").fetchone()
            if not row or not row[0]:
                raise RuntimeError(f"Brak UUID w {mdb}")
            return str(row[0])
        finally:
            conn.close()

    return _with_db_retry(_read)


def list_stem_files(engine_dir: Path, *, library_uuid: str | None = None) -> dict[int, Path]:
    """Mapuje trackId → plik .stems w danej bibliotece."""
    engine_dir = engine_dir.resolve()
    stems_dir = engine_dir / "Stems"
    if not stems_dir.is_dir():
        return {}
    if library_uuid is None:
        library_uuid = get_library_uuid(engine_dir)

    out: dict[int, Path] = {}
    suffix = f" {library_uuid}.stems"
    for entry in stems_dir.iterdir():
        if not entry.is_file() or not entry.name.endswith(suffix):
            continue
        head = entry.name[: -len(suffix)]
        if not head.isdigit():
            continue
        out[int(head)] = entry
    return out


def _stem_bytes(engine_dir: Path, stem_map: dict[int, Path] | None = None) -> int:
    stem_map = stem_map if stem_map is not None else list_stem_files(engine_dir)
    return sum(p.stat().st_size for p in stem_map.values() if p.is_file())


def index_tracks_by_filename(engine_dir: Path) -> dict[str, list[dict]]:
    """Indeks filename.lower() → lista utworów (możliwe duplikaty)."""
    mdb = engine_dir.resolve() / "Database2" / "m.db"

    def _read() -> list:
        conn = _open_engine_mdb(mdb, readonly=True)
        try:
            return conn.execute(
                """
                SELECT id, path, title, artist, isAnalyzed, bitrate, fileBytes
                FROM Track
                WHERE isAvailable = 1
                """
            ).fetchall()
        finally:
            conn.close()

    rows = _with_db_retry(_read)

    index: dict[str, list[dict]] = {}
    for tid, path, title, artist, analyzed, bitrate, file_bytes in rows:
        key = _filename_key(path)
        if not key:
            continue
        index.setdefault(key, []).append(
            {
                "id": tid,
                "path": _norm_path(path),
                "title": title or "",
                "artist": artist or "",
                "is_analyzed": bool(analyzed),
                "bitrate": bitrate or 0,
                "file_bytes": file_bytes or 0,
            }
        )
    return index


def patriot_engine_available(patriot_engine: Path | None = None) -> bool:
    """True gdy podłączona biblioteka Engine na dysku Rane (Patriot)."""
    target = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()
    return (target / "Database2" / "m.db").is_file()


def _patriot_absolute_path(patriot_engine: Path, rel_path: str) -> str:
    rel = _norm_path(rel_path)
    patriot_engine = patriot_engine.resolve()
    if rel.startswith("/"):
        return rel
    return str((patriot_engine / rel).resolve())


def _pick_best_patriot_candidate(
    candidates: list[dict],
    *,
    title: str = "",
    source_file_bytes: int = 0,
) -> dict:
    """Przy wielu wpisach tej samej nazwy pliku — preferuj analyzed, fileBytes, bez „ (2)”."""
    if len(candidates) == 1:
        return candidates[0]

    def score(pt: dict) -> tuple:
        path = pt.get("path") or ""
        stem = Path(path).stem
        dup_suffix = 1 if re.search(r"\s\(\d+\)$", stem) else 0
        title_match = (
            1
            if title
            and title.lower() == (pt.get("title") or "").lower()
            else 0
        )
        bytes_match = (
            1
            if source_file_bytes
            and int(pt.get("file_bytes") or 0) == int(source_file_bytes)
            else 0
        )
        analyzed = 1 if pt.get("is_analyzed") else 0
        return (bytes_match, title_match, analyzed, -dup_suffix)

    return max(candidates, key=score)


_AUDIO_SUFFIXES = {".mp3", ".m4a", ".flac", ".wav", ".aiff", ".aif", ".aac", ".ogg"}


def index_patriot_music_files_by_filename(patriot_engine: Path) -> dict[str, list[str]]:
    """
    Indeks filename.lower() → absolutne ścieżki w Music/ (pliki na dysku).
    Pozwala dodać do m.db utwory skopiowane wcześniej, jeszcze bez wpisu Track.
    """
    music = patriot_engine.resolve() / "Music"
    index: dict[str, list[str]] = {}
    if not music.is_dir():
        return index
    for p in music.rglob("*"):
        if not p.is_file():
            continue
        name = p.name
        if name.startswith("._") or name.startswith("."):
            continue
        if p.suffix.lower() not in _AUDIO_SUFFIXES:
            continue
        try:
            abs_p = str(p.resolve())
        except OSError:
            continue
        index.setdefault(unicodedata.normalize("NFC", name).lower(), []).append(abs_p)
    return index


def match_source_path_to_patriot(
    source_path: str,
    title: str,
    pat_index: dict[str, list[dict]],
    patriot_engine: Path,
    *,
    source_file_bytes: int = 0,
    music_file_index: dict[str, list[str]] | None = None,
) -> str | None:
    """Mapuje ścieżkę Mac/Serato → absolutna ścieżka pliku na Patriot (po nazwie pliku)."""
    key = _filename_key(source_path)
    if not key:
        return None
    candidates = pat_index.get(key)
    if candidates:
        best = _pick_best_patriot_candidate(
            candidates,
            title=title,
            source_file_bytes=source_file_bytes,
        )
        abs_path = _patriot_absolute_path(patriot_engine, best["path"])
        if Path(abs_path).is_file():
            return abs_path
    # Plik jest na Patriot Music/, ale jeszcze nie w m.db (świeża kopia).
    if music_file_index is not None:
        fs_hits = music_file_index.get(key) or []
        for abs_path in fs_hits:
            if Path(abs_path).is_file():
                return abs_path
    return None


def remap_unified_db_for_patriot(db, patriot_engine: Path):
    """
    Kopiuje UnifiedDatabase ze ścieżkami wskazującymi pliki na Patriot.
    Playlisty dostają zremapowane track_ids. Utwory bez pliku na Patriot są pomijane.
    """
    from dataclasses import replace

    from unified_model import Playlist, UnifiedDatabase

    patriot_engine = patriot_engine.resolve()
    pat_index = index_tracks_by_filename(patriot_engine)
    music_file_index = index_patriot_music_files_by_filename(patriot_engine)
    path_map: dict[str, str] = {}
    new_tracks = []
    skipped = 0
    mapped_from_disk = 0

    for track in db.tracks or []:
        file_bytes = 0
        try:
            from engine_file_info import probe_audio_file_info

            src = Path(track.path)
            if src.is_file():
                _, file_bytes = probe_audio_file_info(src)
        except Exception:
            file_bytes = 0
        key = _filename_key(track.path)
        in_db = bool(key and pat_index.get(key))
        hit = match_source_path_to_patriot(
            track.path,
            track.title or "",
            pat_index,
            patriot_engine,
            source_file_bytes=int(file_bytes or 0),
            music_file_index=music_file_index,
        )
        if not hit:
            skipped += 1
            continue
        if not in_db:
            mapped_from_disk += 1
        path_map[track.path] = hit
        new_tracks.append(replace(track, path=hit))

    def _remap_playlist(pl: Playlist) -> Playlist | None:
        new_ids: list[str] = []
        seen: set[str] = set()
        for tid in pl.track_ids or []:
            mapped = path_map.get(tid)
            if not mapped or mapped in seen:
                continue
            seen.add(mapped)
            new_ids.append(mapped)
        new_children = []
        for child in pl.children or []:
            remapped = _remap_playlist(child)
            if remapped:
                new_children.append(remapped)
        if not new_ids and not new_children:
            return None
        return Playlist(
            name=pl.name,
            track_ids=new_ids,
            is_folder=bool(new_children) or pl.is_folder,
            children=new_children,
            filter_text=pl.filter_text or "",
        )

    new_playlists = []
    for pl in db.playlists or []:
        remapped = _remap_playlist(pl)
        if remapped:
            new_playlists.append(remapped)

    stats = {
        "tracks_mapped": len(new_tracks),
        "tracks_mapped_from_disk_only": mapped_from_disk,
        "tracks_skipped_not_on_patriot": skipped,
        "playlists_kept": len(new_playlists),
    }
    return (
        UnifiedDatabase(
            tracks=new_tracks,
            playlists=new_playlists,
            smart_playlists=list(db.smart_playlists or []),
            source=getattr(db, "source", "") or "",
        ),
        stats,
    )


def match_mac_to_patriot_tracks(
    mac_engine: Path,
    patriot_engine: Path,
    *,
    mac_index: dict[str, list[dict]] | None = None,
    pat_index: dict[str, list[dict]] | None = None,
) -> dict[int, int]:
    """
    Mapuje Mac trackId → Patriot trackId (dopasowanie po nazwie pliku).
    Przy wielu kandydatach wybiera ten z tym samym tytułem (case-insensitive).
    """
    mac_engine = mac_engine.resolve()
    patriot_engine = patriot_engine.resolve()
    if mac_index is None:
        mac_index = index_tracks_by_filename(mac_engine)
    if pat_index is None:
        pat_index = index_tracks_by_filename(patriot_engine)

    mapping: dict[int, int] = {}
    for key, mac_tracks in mac_index.items():
        pat_tracks = pat_index.get(key)
        if not pat_tracks:
            continue
        for mt in mac_tracks:
            best = None
            for pt in pat_tracks:
                if (mt["title"] or "").lower() == (pt["title"] or "").lower():
                    best = pt
                    break
            if best is None:
                best = pat_tracks[0]
            mapping[int(mt["id"])] = int(best["id"])
    return mapping


def _disk_free_gb(path: Path) -> float | None:
    try:
        usage = shutil.disk_usage(path)
        return round(usage.free / (1024**3), 2)
    except OSError:
        return None


def stems_migration_status(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
) -> dict:
    """Podsumowanie stemów i kolejki do migracji / renderu."""
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    patriot_engine = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()

    if not mac_engine.is_dir():
        return {"ok": False, "error": f"Brak biblioteki Mac: {mac_engine}"}
    if not patriot_engine.is_dir():
        return {
            "ok": False,
            "error": f"Brak Patriot ({patriot_engine}). Podłącz dysk Rane.",
        }

    mac_uuid = get_library_uuid(mac_engine)
    pat_uuid = get_library_uuid(patriot_engine)
    mac_stems = list_stem_files(mac_engine, library_uuid=mac_uuid)
    pat_stems = list_stem_files(patriot_engine, library_uuid=mac_uuid)
    if not pat_stems:
        pat_stems = list_stem_files(patriot_engine, library_uuid=pat_uuid)

    mac_index = index_tracks_by_filename(mac_engine)
    pat_index = index_tracks_by_filename(patriot_engine)
    id_map = match_mac_to_patriot_tracks(mac_engine, patriot_engine)

    pat_ids_with_stems = set(pat_stems)
    mac_ids_with_stems = set(mac_stems)

    patriot_total = sum(len(v) for v in pat_index.values())
    patriot_with_stems = len(pat_stems)
    patriot_needing_stems = max(patriot_total - patriot_with_stems, 0)

    mac_ready_for_batch: list[dict] = []
    for mac_id, pat_id in id_map.items():
        if pat_id in pat_ids_with_stems:
            continue
        key = None
        for tracks in mac_index.values():
            for t in tracks:
                if t["id"] == mac_id:
                    key = t
                    break
        if not key:
            continue
        if not key["is_analyzed"] or not key["bitrate"] or not key["file_bytes"]:
            continue
        mac_ready_for_batch.append(
            {
                "mac_track_id": mac_id,
                "patriot_track_id": pat_id,
                "title": key["title"],
                "artist": key["artist"],
                "has_mac_stem": mac_id in mac_ids_with_stems,
            }
        )

    mac_ready_for_batch.sort(key=lambda x: (not x["has_mac_stem"], x["title"].lower()))

    return {
        "ok": True,
        "mac_engine": str(mac_engine),
        "patriot_engine": str(patriot_engine),
        "mac_library_uuid": mac_uuid,
        "patriot_library_uuid": pat_uuid,
        "engine_running": is_engine_desktop_running(),
        "sync_manager_warning": ENGINE_SYNC_STEMS_WARNING,
        "mac_stems_count": len(mac_stems),
        "mac_stems_gb": round(_stem_bytes(mac_engine, mac_stems) / (1024**3), 3),
        "patriot_stems_count": len(pat_stems),
        "patriot_stems_gb": round(_stem_bytes(patriot_engine, pat_stems) / (1024**3), 3),
        "patriot_tracks_total": patriot_total,
        "patriot_tracks_needing_stems": patriot_needing_stems,
        "mac_stems_ready_to_migrate": sum(
            1 for x in mac_ready_for_batch if x["has_mac_stem"]
        ),
        "mac_tracks_ready_for_stem_render": sum(
            1 for x in mac_ready_for_batch if not x["has_mac_stem"]
        ),
        "mac_free_gb": _disk_free_gb(mac_engine),
        "patriot_free_gb": _disk_free_gb(patriot_engine),
        "matched_mac_to_patriot": len(id_map),
    }


def diagnose_stems_incident(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
) -> dict:
    """
    Diagnoza po błędnym użyciu Sync Manager → Export Stems.
    Sprawdza osierocone pliki i różnice Mac vs Patriot.
    """
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    patriot_engine = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()
    status = stems_migration_status(mac_engine, patriot_engine)

    mac_stems_dir = mac_engine / "Stems"
    pat_stems_dir = patriot_engine / "Stems"
    mac_uuid = status.get("mac_library_uuid") or get_library_uuid(mac_engine)

    orphan_mac: list[str] = []
    if mac_stems_dir.is_dir():
        mdb = mac_engine / "Database2" / "m.db"
        conn = sqlite3.connect(str(mdb))
        try:
            valid_ids = {r[0] for r in conn.execute("SELECT id FROM Track")}
        finally:
            conn.close()
        for f in mac_stems_dir.glob("*.stems"):
            head = f.name.split()[0]
            if head.isdigit() and int(head) not in valid_ids:
                orphan_mac.append(f.name)

    import shutil

    engine_prime = (
        Path.home()
        / "Library/Application Support/AIR Music Technology/EnginePrime"
    )
    reclaimable_gb = 0.0
    old_bins: list[str] = []
    for name in (
        "bin.v1.0.0.backup",
        "bin.old.20260714_220401",
        "bin.before-1.2.0.20260714_230152",
    ):
        p = engine_prime / name
        if p.is_dir():
            try:
                size = sum(
                    f.stat().st_size for f in p.rglob("*") if f.is_file()
                )
                reclaimable_gb += size / (1024**3)
                old_bins.append(name)
            except OSError:
                pass

    likely_cause = None
    if status.get("patriot_stems_count", 0) == 0 and status.get(
        "patriot_tracks_total", 0
    ) < 1000:
        likely_cause = (
            "Sync Manager z „Export Stems” przy eksporcie playlisty (np. EPIC PARTY) "
            "prawdopodobnie usunął wszystkie stemy z Patriot, które nie były w "
            "kolekcji desktopowej dla wybranych utworów."
        )

    return {
        "ok": True,
        "likely_cause": likely_cause,
        "sync_manager_warning": ENGINE_SYNC_STEMS_WARNING,
        **status,
        "orphan_stem_files_on_mac": orphan_mac,
        "reclaimable_engine_prime_backups_gb": round(reclaimable_gb, 2),
        "engine_prime_old_bins": old_bins,
        "recovery_steps": [
            "Stemy usunięte z Patriot trzeba wyrenderować ponownie (Sync Manager ich nie odzyska).",
            "Renderuj partiami na Mac (NJR → Przygotuj partię → Create stems w Engine).",
            "Przenoś NJR → Przenieś na Patriot — NIE Sync Manager → Export Stems.",
            "Muzykę na Patriot syncuj BEZ zaznaczonego Export Stems.",
            f"Opcjonalnie zwolnij ~{reclaimable_gb:.1f} GB: usuń stare kopie stems-processor w EnginePrime (patrz engine_prime_old_bins).",
        ],
    }


def _find_or_create_playlist_parent(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM Playlist WHERE title = ? AND parentListId = 0 LIMIT 1",
        (STEMS_BATCH_PARENT,),
    ).fetchone()
    if row:
        return int(row[0])
    now = int(time.time())
    cur = conn.execute(
        """
        INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported)
        VALUES (?, 0, 1, 0, ?, 0)
        """,
        (STEMS_BATCH_PARENT, now),
    )
    return int(cur.lastrowid)


def _upsert_batch_playlist(
    engine_dir: Path,
    playlist_name: str,
    track_ids: list[int],
    *,
    parent_list_id: int | None = None,
) -> dict:
    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    database_uuid = get_library_uuid(engine_dir)
    conn = sqlite3.connect(str(mdb))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        if parent_list_id is None:
            parent_list_id = _find_or_create_playlist_parent(conn)

        row = conn.execute(
            "SELECT id FROM Playlist WHERE title = ? AND parentListId = ? LIMIT 1",
            (playlist_name, parent_list_id),
        ).fetchone()
        now = int(time.time())
        if row:
            list_id = int(row[0])
            conn.execute(
                "UPDATE Playlist SET lastEditTime = ? WHERE id = ?",
                (now, list_id),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, isExplicitlyExported)
                VALUES (?, ?, 1, 0, ?, 0)
                """,
                (playlist_name, parent_list_id, now),
            )
            list_id = int(cur.lastrowid)

        conn.execute("DELETE FROM PlaylistEntity WHERE listId = ?", (list_id,))

        max_entity = conn.execute("SELECT IFNULL(MAX(id), 0) FROM PlaylistEntity").fetchone()[0]
        next_id = int(max_entity) + 1
        entity_ids: list[int] = []
        for track_id in track_ids:
            entity_ids.append(next_id)
            next_id += 1

        for idx, track_id in enumerate(track_ids):
            entity_id = entity_ids[idx]
            next_entity = entity_ids[idx + 1] if idx + 1 < len(entity_ids) else 0
            conn.execute(
                """
                INSERT INTO PlaylistEntity (id, listId, trackId, databaseUuid, nextEntityId, membershipReference)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (entity_id, list_id, track_id, database_uuid, next_entity),
            )

        conn.commit()
        return {
            "playlist_id": list_id,
            "playlist_name": playlist_name,
            "parent_list_id": parent_list_id,
            "track_count": len(track_ids),
        }
    finally:
        conn.close()


def prepare_stems_batch_playlist(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
    *,
    batch_size: int = 20,
    prefer_rendered: bool = True,
) -> dict:
    """
    Tworzy playlistę ``NJR / NJR Stems Batch`` na Mac z kolejną partią utworów
    do stemów (brak stemów na Patriot, gotowe do analizy na Mac).
    """
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    patriot_engine = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()
    if is_engine_desktop_running():
        raise RuntimeError(
            "Zamknij Engine DJ Desktop (Cmd+Q) przed utworzeniem playlisty partii."
        )

    status = stems_migration_status(mac_engine, patriot_engine)
    if not status.get("ok"):
        return status

    mac_uuid = status["mac_library_uuid"]
    mac_stems = list_stem_files(mac_engine, library_uuid=mac_uuid)
    pat_stems = list_stem_files(patriot_engine, library_uuid=mac_uuid)
    if not pat_stems:
        pat_stems = list_stem_files(
            patriot_engine, library_uuid=status["patriot_library_uuid"]
        )
    pat_ids_with_stems = set(pat_stems)

    id_map = match_mac_to_patriot_tracks(mac_engine, patriot_engine)
    mac_index = index_tracks_by_filename(mac_engine)

    candidates: list[tuple[int, bool, str]] = []
    for mac_id, pat_id in id_map.items():
        if pat_id in pat_ids_with_stems:
            continue
        meta = None
        for tracks in mac_index.values():
            for t in tracks:
                if t["id"] == mac_id:
                    meta = t
                    break
        if not meta:
            continue
        if not meta["is_analyzed"] or not meta["bitrate"] or not meta["file_bytes"]:
            continue
        has_stem = mac_id in mac_stems
        candidates.append((mac_id, has_stem, (meta["title"] or "").lower()))

    if prefer_rendered:
        candidates.sort(key=lambda x: (not x[1], x[2]))
    else:
        candidates.sort(key=lambda x: (x[1], x[2]))

    batch_ids = [c[0] for c in candidates[: max(1, batch_size)]]
    if not batch_ids:
        return {
            "ok": True,
            "message": "Brak utworów do kolejnej partii (wszystko ma stemy na Patriot lub brak dopasowania).",
            "track_count": 0,
        }

    pl = _upsert_batch_playlist(mac_engine, STEMS_BATCH_PLAYLIST, batch_ids)
    rendered_in_batch = sum(1 for i in batch_ids if i in mac_stems)
    return {
        "ok": True,
        "playlist": f"{STEMS_BATCH_PARENT} / {STEMS_BATCH_PLAYLIST}",
        "track_ids": batch_ids,
        "track_count": len(batch_ids),
        "already_rendered_on_mac": rendered_in_batch,
        "need_render_in_engine": len(batch_ids) - rendered_in_batch,
        **pl,
        "next_steps": [
            "Otwórz Engine DJ → playlista „NJR / NJR Stems Batch”.",
            "Zaznacz utwory → Create stems (jeśli jeszcze nie mają).",
            "Po renderze: migrate_stems_to_patriot (API lub skrypt).",
        ],
    }


def _stem_file_stable(
    path: Path,
    *,
    min_bytes: int = 100_000,
    last_size: int | None = None,
) -> tuple[bool, int]:
    """Czy plik .stems wygląda na gotowy (wystarczająco duży, nie rośnie)."""
    try:
        size = path.stat().st_size
    except OSError:
        return False, 0
    if size < min_bytes:
        return False, size
    if last_size is None:
        return False, size
    if last_size != size:
        return False, size
    return True, size


def migrate_stems_to_patriot(
    mac_engine: Path | None = None,
    patriot_engine: Path | None = None,
    *,
    batch_size: int | None = None,
    delete_mac: bool = True,
    dry_run: bool = False,
    mac_track_ids: list[int] | None = None,
    allow_engine_running: bool = False,
    only_stable: bool = False,
    min_stem_bytes: int = 100_000,
    stable_sizes: dict[str, int] | None = None,
    id_map: dict[int, int] | None = None,
    mac_library_uuid: str | None = None,
) -> dict:
    """
    Kopiuje gotowe stemy z Mac ``Stems/`` na Patriot (właściwe trackId + UUID Mac),
    opcjonalnie usuwa pliki z Maca.
    """
    mac_engine = (mac_engine or default_engine_desktop_library()).resolve()
    patriot_engine = (patriot_engine or DEFAULT_PATRIOT_ENGINE).resolve()

    if not patriot_engine.is_dir():
        return {"ok": False, "error": f"Brak Patriot: {patriot_engine}"}
    if not allow_engine_running and is_engine_desktop_running():
        raise RuntimeError(
            "Zamknij Engine DJ Desktop (Cmd+Q) przed migracją stemów."
        )

    mac_uuid = mac_library_uuid or infer_library_uuid_from_stems(
        mac_engine / "Stems"
    )
    if not mac_uuid:
        mac_uuid = get_library_uuid(mac_engine)
    mac_stems = list_stem_files(mac_engine, library_uuid=mac_uuid)
    if not mac_stems:
        return {"ok": True, "migrated": 0, "message": "Brak stemów na Mac do przeniesienia."}

    if id_map is None:
        id_map = match_mac_to_patriot_tracks(mac_engine, patriot_engine)
    pat_stems_dir = patriot_engine / "Stems"
    pat_stems_dir.mkdir(parents=True, exist_ok=True)

    existing_pat = list_stem_files(patriot_engine, library_uuid=mac_uuid)
    if not existing_pat:
        pat_uuid = infer_library_uuid_from_stems(pat_stems_dir)
        if pat_uuid:
            existing_pat = list_stem_files(patriot_engine, library_uuid=pat_uuid)

    to_process: list[tuple[int, int, Path]] = []
    skipped_unstable = 0
    for mac_id, src in sorted(mac_stems.items(), key=lambda x: x[0]):
        if mac_track_ids is not None and mac_id not in mac_track_ids:
            continue
        pat_id = id_map.get(mac_id)
        if pat_id is None:
            continue
        if pat_id in existing_pat:
            continue
        if only_stable:
            prev = (stable_sizes or {}).get(str(src))
            stable, cur_size = _stem_file_stable(
                src, min_bytes=min_stem_bytes, last_size=prev
            )
            if stable_sizes is not None:
                stable_sizes[str(src)] = cur_size
            if not stable:
                skipped_unstable += 1
                continue
        to_process.append((mac_id, pat_id, src))

    if batch_size is not None and batch_size > 0:
        to_process = to_process[:batch_size]

    migrated = 0
    skipped_no_match = 0
    skipped_exists = 0
    bytes_moved = 0
    errors: list[str] = []
    items: list[dict] = []

    for mac_id, pat_id, src in to_process:
        dest_name = f"{pat_id} {mac_uuid}.stems"
        dest = pat_stems_dir / dest_name
        try:
            size = src.stat().st_size
            if dry_run:
                items.append(
                    {
                        "mac_track_id": mac_id,
                        "patriot_track_id": pat_id,
                        "src": str(src),
                        "dest": str(dest),
                        "bytes": size,
                    }
                )
                migrated += 1
                bytes_moved += size
                continue
            shutil.copy2(src, dest)
            if delete_mac:
                src.unlink()
            migrated += 1
            bytes_moved += size
            items.append(
                {
                    "mac_track_id": mac_id,
                    "patriot_track_id": pat_id,
                    "dest": str(dest),
                    "bytes": size,
                    "deleted_mac": delete_mac,
                }
            )
        except OSError as ex:
            errors.append(f"{src.name}: {ex}")

    for mac_id in mac_stems:
        if mac_track_ids is not None and mac_id not in mac_track_ids:
            continue
        if mac_id not in id_map:
            skipped_no_match += 1
        elif id_map[mac_id] in existing_pat:
            skipped_exists += 1

    return {
        "ok": len(errors) == 0,
        "dry_run": dry_run,
        "migrated": migrated,
        "bytes_moved": bytes_moved,
        "bytes_moved_gb": round(bytes_moved / (1024**3), 3),
        "skipped_no_patriot_match": skipped_no_match,
        "skipped_already_on_patriot": skipped_exists,
        "skipped_unstable": skipped_unstable,
        "delete_mac": delete_mac and not dry_run,
        "errors": errors,
        "items": items[:50],
    }
