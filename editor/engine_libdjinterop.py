"""
Uruchamia binarkę njr-engine-export (libdjinterop).
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from engine_album_art import sync_engine_album_art


def _binary_names() -> list[str]:
    if platform.system() == "Windows":
        return ["njr-engine-export.exe", "njr-engine-export"]
    return ["njr-engine-export"]


def find_engine_export_binary() -> Path | None:
    """Szuka njr-engine-export obok exe, w _MEIPASS, engine_bridge/build."""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        for name in _binary_names():
            candidates.append(base / name)
            candidates.append(base / "engine_bridge" / name)
    exe = Path(sys.executable).resolve()
    for name in _binary_names():
        candidates.append(exe.parent / name)
    here = Path(__file__).resolve().parent
    for name in _binary_names():
        candidates.append(here / "engine_bridge" / "build" / name)
        candidates.append(here / "engine_bridge" / "build" / "Release" / name)
        candidates.append(here / "engine_bridge" / "build" / "Debug" / name)
    env = os.environ.get("NJR_ENGINE_EXPORT_BIN", "").strip()
    if env:
        candidates.insert(0, Path(env))
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def default_engine_desktop_library() -> Path:
    """
    Domyślna biblioteka Engine DJ Desktop.
    Mac: ~/Music/Engine Library. Windows: %USERPROFILE%\\Music\\Engine Library.
    """
    env = os.environ.get("NJR_ENGINE_LIBRARY", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / "Music" / "Engine Library").resolve()


def is_engine_desktop_running() -> bool:
    """True jeśli Engine DJ Desktop jest uruchomiony (nie synchronizuj wtedy)."""
    if platform.system() == "Darwin":
        try:
            r = subprocess.run(
                ["pgrep", "-xq", "Engine DJ"],
                capture_output=True,
                timeout=5,
            )
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    if platform.system() == "Windows":
        try:
            r = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    "IMAGENAME eq Engine DJ.exe",
                    "/NH",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "Engine DJ.exe" in (r.stdout or "")
        except (OSError, subprocess.TimeoutExpired):
            return False
    return False


def assert_engine_library_safe_for_write(engine_dir: Path) -> None:
    """
    Walidacja przed zapisem do Engine Library (wytyczne Engine DJ 3rd-party tools).
    - Engine DJ zamknięty
    - brak konfliktu legacy m.db + Database2/m.db (libdjinterop/database_not_found)
    """
    if is_engine_desktop_running():
        raise RuntimeError(
            "Zamknij Engine DJ Desktop przed synchronizacją (Cmd+Q). "
            "Równoległa praca grozi korupcją bazy (Engine DJ developer guidelines)."
        )
    engine_dir = engine_dir.resolve()
    legacy_mdb = engine_dir / "m.db"
    database2_mdb = engine_dir / "Database2" / "m.db"
    if legacy_mdb.is_file() and database2_mdb.is_file():
        raise RuntimeError(
            "Konflikt biblioteki Engine: istnieją jednocześnie "
            f"{legacy_mdb} i {database2_mdb}. "
            "Usuń pusty/legacy m.db z korzenia Engine Library (zachowaj Database2/)."
        )


def backup_engine_database2(
    engine_dir: Path,
    *,
    label: str = "pre-merge",
    keep: int = 5,
) -> dict:
    """
    Kopia zapasowa Database2/ przed merge lub naprawą (Engine DJ: backup przed migracją).
    """
    import shutil
    from datetime import datetime

    engine_dir = engine_dir.resolve()
    dbdir = engine_dir / "Database2"
    if not dbdir.is_dir():
        return {"skipped": True, "reason": "no_database2"}

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = engine_dir / f"_njr-backup-{stamp}-{label}"
    shutil.copytree(dbdir, dest / "Database2")
    legacy = engine_dir / "m.db"
    if legacy.is_file():
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, dest / "m.db-root")

    backups = sorted(
        engine_dir.glob("_njr-backup-*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for old in backups[keep:]:
        try:
            shutil.rmtree(old)
            removed.append(old.name)
        except OSError:
            pass

    return {
        "backup_dir": str(dest),
        "label": label,
        "removed_old_backups": removed,
    }


# libdjinterop latest_schema = schema_3_0_2 (engine_schema.hpp)
NJR_ENGINE_SCHEMA_MIN = (2, 18, 0)
NJR_ENGINE_SCHEMA_MAX = (3, 0, 2)
NJR_ENGINE_AUXILIARY_DBS = ("hm.db", "sm.db", "stm.db")


def _schema_tuple(major: int | None, minor: int | None, patch: int | None) -> tuple[int, int, int]:
    return (int(major or 0), int(minor or 0), int(patch or 0))


def _format_schema(t: tuple[int, int, int]) -> str:
    return f"{t[0]}.{t[1]}.{t[2]}"


def read_engine_schema_info(engine_dir: Path) -> dict:
    """Odczyt Information + PRAGMA z Database2/m.db (read-only)."""
    import sqlite3

    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    out: dict = {
        "mdb_path": str(mdb),
        "mdb_exists": mdb.is_file(),
        "mdb_size": mdb.stat().st_size if mdb.is_file() else 0,
        "schema_tuple": None,
        "schema": None,
        "library_uuid": None,
        "integrity": None,
        "track_count": None,
        "missing_auxiliary_dbs": [],
    }
    if not mdb.is_file() or mdb.stat().st_size == 0:
        return out

    conn = sqlite3.connect(f"file:{mdb}?mode=ro", uri=True)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "Information" not in tables:
            out["error"] = "missing_information_table"
            return out

        row = conn.execute(
            """
            SELECT uuid, schemaVersionMajor, schemaVersionMinor, schemaVersionPatch
            FROM Information LIMIT 1
            """
        ).fetchone()
        if row:
            out["library_uuid"] = row[0]
            st = _schema_tuple(row[1], row[2], row[3])
            out["schema_tuple"] = st
            out["schema"] = _format_schema(st)

        if "Track" in tables:
            out["track_count"] = conn.execute("SELECT COUNT(*) FROM Track").fetchone()[0]

        try:
            ic = conn.execute("PRAGMA integrity_check").fetchone()
            out["integrity"] = ic[0] if ic else None
        except sqlite3.Error:
            out["integrity"] = "error"
    finally:
        conn.close()

    dbdir = engine_dir / "Database2"
    if out["mdb_size"] > 1024 * 1024:
        out["missing_auxiliary_dbs"] = [
            name for name in NJR_ENGINE_AUXILIARY_DBS
            if not (dbdir / name).is_file()
        ]
    return out


def validate_engine_schema(engine_dir: Path) -> dict:
    """
    Walidacja wersji schematu Engine przed merge (Engine DJ developer guidelines).
    libdjinterop obsługuje 2.18.0 … 3.0.2; nowszy schemat Engine = blokada merge.
    """
    engine_dir = engine_dir.resolve()
    legacy_mdb = engine_dir / "m.db"
    info = read_engine_schema_info(engine_dir)
    warnings: list[str] = []
    errors: list[str] = []

    if not info["mdb_exists"] or info["mdb_size"] == 0:
        if legacy_mdb.is_file() and legacy_mdb.stat().st_size > 0:
            errors.append(
                "Wykryto legacy bibliotekę Engine (tylko root m.db). "
                "Otwórz Engine DJ Desktop raz — zmigruje do Database2/ — "
                "potem ponów sync NJR."
            )
        return {
            "ok": len(errors) == 0,
            "new_library": True,
            "schema": None,
            "njr_schema_max": _format_schema(NJR_ENGINE_SCHEMA_MAX),
            "warnings": warnings,
            "errors": errors,
            **info,
        }

    if info.get("error") == "missing_information_table":
        errors.append(f"Brak tabeli Information w {info['mdb_path']} — baza uszkodzona.")
        return {
            "ok": False,
            "new_library": False,
            "schema": None,
            "njr_schema_max": _format_schema(NJR_ENGINE_SCHEMA_MAX),
            "warnings": warnings,
            "errors": errors,
            **info,
        }

    if info.get("integrity") not in (None, "ok"):
        errors.append(
            f"PRAGMA integrity_check: {info.get('integrity')} — "
            "przywróć kopię z _njr-backup-* przed merge."
        )

    st = info.get("schema_tuple")
    if not st:
        errors.append("Nie odczytano wersji schematu z Information.")
    else:
        if st < NJR_ENGINE_SCHEMA_MIN:
            errors.append(
                f"Schemat Engine {_format_schema(st)} jest za stary "
                f"(minimum {_format_schema(NJR_ENGINE_SCHEMA_MIN)}). "
                "Zaktualizuj Engine DJ Desktop i otwórz bibliotekę, aby zmigrować schemat."
            )
        elif st > NJR_ENGINE_SCHEMA_MAX:
            errors.append(
                f"Schemat Engine {_format_schema(st)} jest nowszy niż obsługiwany przez "
                f"NJR/libdjinterop ({_format_schema(NJR_ENGINE_SCHEMA_MAX)}). "
                "Zaktualizuj NJR konwerter (njr-engine-export) przed synchronizacją."
            )
        elif st < NJR_ENGINE_SCHEMA_MAX:
            warnings.append(
                f"Schemat {_format_schema(st)} — Engine DJ może wykonać forward migration "
                f"do {_format_schema(NJR_ENGINE_SCHEMA_MAX)} przy następnym uruchomieniu. "
                "Kopia zapasowa zostanie utworzona automatycznie."
            )

    missing_aux = info.get("missing_auxiliary_dbs") or []
    if missing_aux:
        warnings.append(
            "Brak plików pomocniczych Database2/: "
            + ", ".join(missing_aux)
            + ". Engine DJ może zgłosić „corrupt library” — przywróć je z kopii "
            "_njr-backup-* (nie usuwaj całego Database2/ bez backupu)."
        )

    return {
        "ok": len(errors) == 0,
        "new_library": False,
        "schema": info.get("schema"),
        "njr_schema_min": _format_schema(NJR_ENGINE_SCHEMA_MIN),
        "njr_schema_max": _format_schema(NJR_ENGINE_SCHEMA_MAX),
        "warnings": warnings,
        "errors": errors,
        **info,
    }


def assert_engine_schema_compatible(engine_dir: Path) -> dict:
    """Rzuca RuntimeError gdy schemat blokuje merge; zwraca wynik walidacji."""
    result = validate_engine_schema(engine_dir)
    if not result["ok"]:
        raise RuntimeError(
            "Walidacja biblioteki Engine nie powiodła się:\n"
            + "\n".join(f"• {e}" for e in result["errors"])
        )
    return result


def _engine_export_timeout_sec() -> int:
    """Timeout njr-engine-export (domyślnie 3600 s; env NJR_ENGINE_EXPORT_TIMEOUT)."""
    raw = os.environ.get("NJR_ENGINE_EXPORT_TIMEOUT", "").strip()
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    return 3600


def run_engine_export(export_doc: dict, engine_dir: Path) -> dict:
    """
    Zapisuje bibliotekę Engine DJ w engine_dir (folder „Engine Library”).
    export_doc: dokument z unified_to_engine_export_doc (bez engine_dir).
    """
    binary = find_engine_export_binary()
    if not binary:
        raise FileNotFoundError(
            "Brak njr-engine-export (libdjinterop). "
            "Zbuduj: cd editor/engine_bridge && cmake -B build && cmake --build build"
        )

    engine_dir = engine_dir.resolve()
    engine_dir.mkdir(parents=True, exist_ok=True)

    payload = dict(export_doc)
    payload["engine_dir"] = str(engine_dir)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tf:
        json.dump(payload, tf, ensure_ascii=False)
        json_path = tf.name

    try:
        proc = subprocess.run(
            [str(binary), json_path],
            capture_output=True,
            text=True,
            timeout=_engine_export_timeout_sec(),
        )
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            err = stderr or stdout or f"exit {proc.returncode}"
            try:
                err_json = json.loads(stderr or stdout)
                err = err_json.get("error", err)
            except json.JSONDecodeError:
                pass
            raise RuntimeError(f"njr-engine-export: {err}")
        if stdout:
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return {"ok": True, "raw": stdout}
        return {"ok": True}
    finally:
        try:
            os.unlink(json_path)
        except OSError:
            pass


def repair_engine_track_paths(engine_dir: Path) -> dict:
    """
    Naprawia ścieżki w m.db gdy były zapisane względem folderu z muzyką zamiast Engine Library.
    Engine DJ oczekuje ścieżek względem folderu „Engine Library” (np. ../../Desktop/…).
    """
    import os
    import sqlite3

    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file():
        return {"fixed": 0, "checked": 0, "skipped": True}

    search_roots = [
        Path.home() / "Desktop",
        Path.home() / "Music",
        Path.home() / "Downloads",
        Path("/Volumes"),
    ]

    fixed = 0
    checked = 0
    collisions = 0
    conn = sqlite3.connect(str(mdb))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, path FROM Track")
        rows = cur.fetchall()
        occupied = {
            (p or "").replace("\\", "/")
            for _, p in rows
            if p
        }
        for tid, path in rows:
            if not path:
                continue
            checked += 1
            rel = path.replace("\\", "/")
            try:
                if (engine_dir / rel).resolve().is_file():
                    continue
            except OSError:
                pass
            if rel.startswith("../"):
                try:
                    if (engine_dir / rel).resolve().is_file():
                        continue
                except OSError:
                    pass

            new_rel = None
            for root in search_roots:
                if not root.exists():
                    continue
                candidate = root / rel
                if candidate.is_file():
                    new_rel = os.path.relpath(
                        str(candidate.resolve()), str(engine_dir)
                    ).replace("\\", "/")
                    break
            if not new_rel or new_rel == rel:
                continue
            # Dwa „zepsute” path mogą wskazać ten sam plik — UNIQUE(path).
            if new_rel in occupied:
                collisions += 1
                continue
            try:
                cur.execute(
                    "UPDATE Track SET path = ? WHERE id = ?",
                    (new_rel, tid),
                )
            except sqlite3.IntegrityError:
                collisions += 1
                continue
            occupied.discard(rel)
            occupied.add(new_rel)
            fixed += 1
        conn.commit()
    finally:
        conn.close()
    return {
        "fixed": fixed,
        "checked": checked,
        "collisions": collisions,
        "engine_dir": str(engine_dir),
    }


# Minimalna długość overviewWaveFormData uznawana za prawdziwy waveform Engine DJ.
_ENGINE_MIN_WAVEFORM_BYTES = 500
# Pusty szablon quickCues Engine (8 slotów bez cue).
_ENGINE_STUB_CUE_BYTES = 28


def _merged_paths_from_export(export_doc: dict) -> set[str]:
    paths: set[str] = set()
    for track in export_doc.get("tracks") or []:
        rel = (track.get("relative_path") or "").replace("\\", "/")
        if rel:
            paths.add(rel)
    return paths


def snapshot_engine_performance(
    engine_dir: Path,
    paths: set[str],
    *,
    min_waveform_bytes: int = _ENGINE_MIN_WAVEFORM_BYTES,
) -> dict[str, dict]:
    """
    Kopie zapasowe waveformów, cue i stanu analizy (klucz: Track.path).
    Snapshot obejmuje wszystkie ścieżki z merge — waveform tylko gdy ≥ min_waveform_bytes.
    """
    import sqlite3

    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file() or not paths:
        return {}

    normalized = {p.replace("\\", "/") for p in paths if p}
    placeholders = ",".join("?" for _ in normalized)
    conn = sqlite3.connect(str(mdb))
    try:
        rows = conn.execute(
            f"""
            SELECT t.path, t.isAnalyzed, t.bpm, t.bpmAnalyzed,
                   p.overviewWaveFormData, p.beatData, p.trackData,
                   p.quickCues, p.loops,
                   IFNULL(length(p.overviewWaveFormData), 0),
                   IFNULL(length(p.quickCues), 0)
            FROM Track t
            JOIN PerformanceData p ON p.trackId = t.id
            WHERE t.path IN ({placeholders})
            """,
            tuple(sorted(normalized)),
        ).fetchall()
    finally:
        conn.close()

    snapshots: dict[str, dict] = {}
    for row in rows:
        path = row[0]
        wave_len = row[9]
        cue_len = row[10]
        if wave_len < min_waveform_bytes and cue_len <= _ENGINE_STUB_CUE_BYTES:
            continue
        snapshots[path] = {
            "is_analyzed": row[1],
            "bpm": row[2],
            "bpm_analyzed": row[3],
            "overview_waveform_data": row[4],
            "beat_data": row[5],
            "track_data": row[6],
            "quick_cues": row[7],
            "loops": row[8],
            "had_waveform": wave_len >= min_waveform_bytes,
            "had_cues": cue_len > _ENGINE_STUB_CUE_BYTES,
        }
    return snapshots


def restore_engine_performance(
    engine_dir: Path,
    snapshots: dict[str, dict],
    *,
    min_waveform_bytes: int = _ENGINE_MIN_WAVEFORM_BYTES,
) -> dict:
    """Przywraca waveformy i cue z kopii po merge, gdy libdjinterop nadpisał je stubem."""
    import sqlite3

    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file() or not snapshots:
        return {
            "waveforms_restored": 0,
            "cues_restored": 0,
            "snapshots_total": len(snapshots),
        }

    waveforms_restored = 0
    cues_restored = 0
    conn = sqlite3.connect(str(mdb))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        for path, snap in snapshots.items():
            row = conn.execute(
                """
                SELECT t.id,
                       IFNULL(length(p.overviewWaveFormData), 0),
                       IFNULL(length(p.quickCues), 0)
                FROM Track t
                JOIN PerformanceData p ON p.trackId = t.id
                WHERE t.path = ?
                """,
                (path,),
            ).fetchone()
            if not row:
                continue
            track_id, new_wave_len, new_cue_len = row

            restore_wave = (
                snap.get("had_waveform")
                and new_wave_len < min_waveform_bytes
            )
            restore_cues = (
                snap.get("had_cues")
                and new_cue_len <= _ENGINE_STUB_CUE_BYTES
            )
            if not restore_wave and not restore_cues:
                continue

            if restore_wave and restore_cues:
                conn.execute(
                    """
                    UPDATE PerformanceData
                    SET overviewWaveFormData = ?,
                        beatData = ?,
                        trackData = ?,
                        quickCues = ?,
                        loops = ?
                    WHERE trackId = ?
                    """,
                    (
                        snap["overview_waveform_data"],
                        snap["beat_data"],
                        snap["track_data"],
                        snap["quick_cues"],
                        snap["loops"],
                        track_id,
                    ),
                )
                conn.execute(
                    """
                    UPDATE Track
                    SET isAnalyzed = ?, bpm = ?, bpmAnalyzed = ?
                    WHERE id = ?
                    """,
                    (
                        snap["is_analyzed"],
                        snap["bpm"],
                        snap["bpm_analyzed"],
                        track_id,
                    ),
                )
                waveforms_restored += 1
                cues_restored += 1
            elif restore_wave:
                conn.execute(
                    """
                    UPDATE PerformanceData
                    SET overviewWaveFormData = ?,
                        beatData = ?,
                        trackData = ?
                    WHERE trackId = ?
                    """,
                    (
                        snap["overview_waveform_data"],
                        snap["beat_data"],
                        snap["track_data"],
                        track_id,
                    ),
                )
                conn.execute(
                    """
                    UPDATE Track
                    SET isAnalyzed = ?, bpm = ?, bpmAnalyzed = ?
                    WHERE id = ?
                    """,
                    (
                        snap["is_analyzed"],
                        snap["bpm"],
                        snap["bpm_analyzed"],
                        track_id,
                    ),
                )
                waveforms_restored += 1
            elif restore_cues:
                conn.execute(
                    """
                    UPDATE PerformanceData
                    SET quickCues = ?, loops = ?
                    WHERE trackId = ?
                    """,
                    (snap["quick_cues"], snap["loops"], track_id),
                )
                cues_restored += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "waveforms_restored": waveforms_restored,
        "cues_restored": cues_restored,
        "snapshots_total": len(snapshots),
    }


def repair_engine_playlist_entity_refs(conn) -> dict:
    """
    Naprawia PlaylistEntity po eksporcie Sync Manager / kopiowaniu biblioteki.

    Engine Sync na dysk zewnętrzny często zostawia trackId = ID z Maca
    (Track.originTrackId) oraz databaseUuid = UUID Maca, podczas gdy lokalne
    Track.id są 1…N, a Information.uuid jest nowe. Na Rane/OS playlisty
    wyglądają na puste (nazwy są, utwory znikają).

    Mapuje PE.trackId przez Track.originTrackId → Track.id i ustawia
    databaseUuid na lokalne Information.uuid. Dopiero potem wolno usuwać
    prawdziwe orphany.
    """
    import sqlite3

    cols_pe = {r[1] for r in conn.execute("PRAGMA table_info(PlaylistEntity)")}
    cols_tr = {r[1] for r in conn.execute("PRAGMA table_info(Track)")}
    has_uuid = "databaseUuid" in cols_pe
    has_origin = "originTrackId" in cols_tr
    if not has_origin:
        return {
            "playlist_entities_remapped": 0,
            "playlist_entities_uuid_fixed": 0,
            "playlist_entities_remap_dropped": 0,
            "skipped": True,
            "reason": "no_originTrackId",
        }

    local_uuid = None
    try:
        row = conn.execute("SELECT uuid FROM Information LIMIT 1").fetchone()
        if row and row[0]:
            local_uuid = str(row[0])
    except sqlite3.Error:
        local_uuid = None

    origin_to_local = {
        int(origin): int(local_id)
        for origin, local_id in conn.execute(
            """
            SELECT originTrackId, id FROM Track
            WHERE originTrackId IS NOT NULL AND originTrackId > 0
            """
        )
        if origin is not None
    }
    # PE.trackId = ID Maca, które nadal istnieje jako osobny wiersz Track po dedupe / eksporcie
    origin_as_id_to_local = dict(origin_to_local)

    remapped = 0
    uuid_fixed = 0
    dropped = 0

    if has_uuid:
        rows = conn.execute(
            "SELECT id, listId, trackId, databaseUuid FROM PlaylistEntity WHERE trackId > 0"
        ).fetchall()
    else:
        rows = [
            (r[0], r[1], r[2], None)
            for r in conn.execute(
                "SELECT id, listId, trackId FROM PlaylistEntity WHERE trackId > 0"
            )
        ]

    local_ids = {r[0] for r in conn.execute("SELECT id FROM Track")}

    for pe_id, list_id, track_id, db_uuid in rows:
        tid = int(track_id)
        if tid in origin_as_id_to_local and tid != origin_as_id_to_local[tid]:
            new_tid = origin_as_id_to_local[tid]
        else:
            new_tid = tid if tid in local_ids else origin_to_local.get(tid)
        if new_tid is None:
            continue
        new_uuid = local_uuid if (has_uuid and local_uuid) else db_uuid
        needs_id = new_tid != tid
        needs_uuid = bool(has_uuid and local_uuid and (db_uuid or "") != local_uuid)
        if not needs_id and not needs_uuid:
            continue
        try:
            if has_uuid and local_uuid:
                conn.execute(
                    """
                    UPDATE PlaylistEntity
                    SET trackId = ?, databaseUuid = ?
                    WHERE id = ?
                    """,
                    (new_tid, local_uuid, pe_id),
                )
            else:
                conn.execute(
                    "UPDATE PlaylistEntity SET trackId = ? WHERE id = ?",
                    (new_tid, pe_id),
                )
            if needs_id:
                remapped += 1
            elif needs_uuid:
                uuid_fixed += 1
        except sqlite3.IntegrityError:
            # Duplikat (listId, databaseUuid, trackId) po remap — zostaw poprawny wpis.
            conn.execute("DELETE FROM PlaylistEntity WHERE id = ?", (pe_id,))
            dropped += 1

    return {
        "playlist_entities_remapped": remapped,
        "playlist_entities_uuid_fixed": uuid_fixed,
        "playlist_entities_remap_dropped": dropped,
    }


def diagnose_engine_playlists(engine_dir: Path) -> dict:
    """
    Diagnostyka PlaylistEntity na dysku Engine (Mac / Patriot).
    Wykrywa typowy błąd Sync Manager: PE.trackId = ID Maca, databaseUuid = UUID Maca.
    """
    import sqlite3

    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file():
        return {"ok": False, "error": "no_m_db", "engine_dir": str(engine_dir)}

    conn = sqlite3.connect(str(mdb))
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "PlaylistEntity" not in tables or "Track" not in tables:
            return {"ok": False, "error": "missing_tables", "engine_dir": str(engine_dir)}

        local_uuid = None
        if "Information" in tables:
            row = conn.execute("SELECT uuid FROM Information LIMIT 1").fetchone()
            local_uuid = row[0] if row and row[0] else None

        track_count = conn.execute("SELECT COUNT(*) FROM Track").fetchone()[0]
        pe_total = conn.execute(
            "SELECT COUNT(*) FROM PlaylistEntity WHERE trackId > 0"
        ).fetchone()[0]
        pe_linked = conn.execute(
            """
            SELECT COUNT(*) FROM PlaylistEntity pe
            JOIN Track t ON t.id = pe.trackId
            WHERE pe.trackId > 0
            """
        ).fetchone()[0]
        pe_orphans = pe_total - pe_linked

        pe_wrong_uuid = 0
        if local_uuid and "databaseUuid" in {
            r[1] for r in conn.execute("PRAGMA table_info(PlaylistEntity)")
        }:
            pe_wrong_uuid = conn.execute(
                """
                SELECT COUNT(*) FROM PlaylistEntity
                WHERE trackId > 0 AND IFNULL(databaseUuid, '') != ?
                """,
                (local_uuid,),
            ).fetchone()[0]

        pe_mac_ids = 0
        if "originTrackId" in {r[1] for r in conn.execute("PRAGMA table_info(Track)")}:
            pe_mac_ids = conn.execute(
                """
                SELECT COUNT(*) FROM PlaylistEntity pe
                JOIN Track t ON t.originTrackId = pe.trackId AND t.id != pe.trackId
                WHERE pe.trackId > 0
                """
            ).fetchone()[0]

        broken_chains = 0
        for (list_id,) in conn.execute(
            "SELECT DISTINCT listId FROM PlaylistEntity WHERE trackId > 0"
        ):
            rows = list(
                conn.execute(
                    """
                    SELECT id, nextEntityId FROM PlaylistEntity
                    WHERE listId = ? AND trackId > 0
                    """,
                    (list_id,),
                )
            )
            if not rows:
                continue
            nxt_map: dict[int, int] = {}
            for eid, nxt in rows:
                if nxt in nxt_map:
                    broken_chains += 1
                    break
                nxt_map[nxt] = eid
            else:
                if 0 not in nxt_map:
                    broken_chains += 1
                else:
                    curr = nxt_map.get(0)
                    seen: set[int] = set()
                    walked = 0
                    while curr and curr not in seen:
                        seen.add(curr)
                        walked += 1
                        curr = nxt_map.get(curr)
                    if walked != len(rows):
                        broken_chains += 1

        sample_playlists: list[dict] = []
        for lid, title, cnt in conn.execute(
            """
            SELECT p.id, p.title, COUNT(pe.id) AS track_count
            FROM Playlist p
            LEFT JOIN PlaylistEntity pe ON pe.listId = p.id AND pe.trackId > 0
            WHERE p.isPersisted = 1
            GROUP BY p.id
            ORDER BY track_count DESC
            LIMIT 3
            """
        ):
            if cnt <= 0:
                continue
            sample_playlists.append(
                {"id": lid, "title": title, "track_count": cnt}
            )

        healthy = (
            pe_orphans == 0
            and pe_wrong_uuid == 0
            and pe_mac_ids == 0
            and broken_chains == 0
        )
        return {
            "ok": True,
            "healthy": healthy,
            "engine_dir": str(engine_dir),
            "library_uuid": local_uuid,
            "track_count": track_count,
            "playlist_entities_total": pe_total,
            "playlist_entities_linked": pe_linked,
            "playlist_entities_orphans": pe_orphans,
            "playlist_entities_wrong_uuid": pe_wrong_uuid,
            "playlist_entities_mac_track_ids": pe_mac_ids,
            "playlist_chain_errors": broken_chains,
            "sample_playlists": sample_playlists,
        }
    finally:
        conn.close()


def repair_engine_post_merge(
    engine_dir: Path,
    *,
    merged_paths: set[str] | None = None,
    min_waveform_bytes: int = _ENGINE_MIN_WAVEFORM_BYTES,
) -> dict:
    """
    Naprawia m.db po merge libdjinterop:
    - remap PlaylistEntity (originTrackId / UUID Maca → lokalne ID),
    - usuwa osierocone PerformanceData / PlaylistEntity (po prune tracków),
    - resetuje isAnalyzed gdy brak prawdziwego waveformu (libdjinterop ustawia isAnalyzed=1
      przy imporcie metadanych VDJ bez danych Engine),
    - uzupełnia kolumnę bpm z bpmAnalyzed gdy analiza już była, ale bpm=0.
    """
    import sqlite3

    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file():
        return {"skipped": True, "reason": "no_m_db"}

    paths_filter = None
    if merged_paths:
        paths_filter = {p.replace("\\", "/") for p in merged_paths if p}

    conn = sqlite3.connect(str(mdb))
    try:
        conn.execute("PRAGMA foreign_keys=ON")

        pe_remap = repair_engine_playlist_entity_refs(conn)

        orphan_perf = conn.execute(
            """
            SELECT COUNT(*) FROM PerformanceData p
            LEFT JOIN Track t ON t.id = p.trackId
            WHERE t.id IS NULL
            """
        ).fetchone()[0]
        conn.execute(
            """
            DELETE FROM PerformanceData
            WHERE trackId NOT IN (SELECT id FROM Track)
            """
        )

        orphan_pe = conn.execute(
            """
            SELECT COUNT(*) FROM PlaylistEntity pe
            LEFT JOIN Track t ON t.id = pe.trackId
            WHERE pe.trackId > 0 AND t.id IS NULL
            """
        ).fetchone()[0]
        conn.execute(
            """
            DELETE FROM PlaylistEntity
            WHERE trackId > 0 AND trackId NOT IN (SELECT id FROM Track)
            """
        )

        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        dangling_art = 0
        if "AlbumArt" in tables and "albumArtId" in {
            r[1] for r in conn.execute("PRAGMA table_info(Track)")
        }:
            dangling_art = conn.execute(
                """
                SELECT COUNT(*) FROM Track
                WHERE albumArtId IS NOT NULL
                  AND albumArtId NOT IN (SELECT id FROM AlbumArt)
                """
            ).fetchone()[0]
            conn.execute(
                """
                UPDATE Track SET albumArtId = NULL, albumArtSourceHash = NULL
                WHERE albumArtId IS NOT NULL
                  AND albumArtId NOT IN (SELECT id FROM AlbumArt)
                """
            )

        playlists_touched = 0
        if "Playlist" in tables and "lastEditTime" in {
            r[1] for r in conn.execute("PRAGMA table_info(Playlist)")
        }:
            import time

            now = int(time.time())
            playlists_touched = conn.execute(
                """
                UPDATE Playlist
                SET lastEditTime = ?
                WHERE isPersisted = 1
                  AND id IN (
                    SELECT DISTINCT listId FROM PlaylistEntity WHERE trackId > 0
                  )
                """,
                (now,),
            ).rowcount

        path_clause = ""
        path_params: tuple = ()
        if paths_filter:
            placeholders = ",".join("?" for _ in paths_filter)
            path_clause = f" AND t.path IN ({placeholders})"
            path_params = tuple(sorted(paths_filter))

        stub_count = conn.execute(
            f"""
            SELECT COUNT(*) FROM Track t
            JOIN PerformanceData p ON p.trackId = t.id
            WHERE IFNULL(length(p.overviewWaveFormData), 0) < ?
            {path_clause}
            """,
            (min_waveform_bytes, *path_params),
        ).fetchone()[0]

        # Zachowaj widoczne BPM z importu Serato/VDJ zanim wyczyścimy bpmAnalyzed stubu.
        conn.execute(
            f"""
            UPDATE Track
            SET bpm = CAST(ROUND(bpmAnalyzed) AS INTEGER)
            WHERE bpm = 0
              AND bpmAnalyzed IS NOT NULL
              AND bpmAnalyzed > 0
              AND id IN (
                SELECT t.id FROM Track t
                JOIN PerformanceData p ON p.trackId = t.id
                WHERE IFNULL(length(p.overviewWaveFormData), 0) < ?
                {path_clause}
              )
            """,
            (min_waveform_bytes, *path_params),
        )

        conn.execute(
            f"""
            UPDATE Track
            SET isAnalyzed = 0, bpmAnalyzed = NULL
            WHERE id IN (
                SELECT t.id FROM Track t
                JOIN PerformanceData p ON p.trackId = t.id
                WHERE IFNULL(length(p.overviewWaveFormData), 0) < ?
                {path_clause}
            )
            """,
            (min_waveform_bytes, *path_params),
        )
        conn.execute(
            f"""
            UPDATE PerformanceData
            SET overviewWaveFormData = NULL,
                beatData = NULL,
                trackData = NULL
            WHERE trackId IN (
                SELECT t.id FROM Track t
                JOIN PerformanceData p ON p.trackId = t.id
                WHERE IFNULL(length(p.overviewWaveFormData), 0) < ?
                {path_clause}
            )
            """,
            (min_waveform_bytes, *path_params),
        )
        # Nie usuwaj quickCues/loops — mogą pochodzić z importu Serato bez waveformu.

        bpm_synced = conn.execute(
            f"""
            SELECT COUNT(*) FROM Track t
            JOIN PerformanceData p ON p.trackId = t.id
            WHERE t.bpm = 0
              AND t.bpmAnalyzed IS NOT NULL
              AND t.bpmAnalyzed > 0
              AND t.isAnalyzed = 1
              AND IFNULL(length(p.overviewWaveFormData), 0) >= ?
            {path_clause}
            """,
            (min_waveform_bytes, *path_params),
        ).fetchone()[0]
        conn.execute(
            f"""
            UPDATE Track
            SET bpm = CAST(ROUND(bpmAnalyzed) AS INTEGER)
            WHERE id IN (
                SELECT t.id FROM Track t
                JOIN PerformanceData p ON p.trackId = t.id
                WHERE t.bpm = 0
                  AND t.bpmAnalyzed IS NOT NULL
                  AND t.bpmAnalyzed > 0
                  AND t.isAnalyzed = 1
                  AND IFNULL(length(p.overviewWaveFormData), 0) >= ?
                {path_clause}
            )
            """,
            (min_waveform_bytes, *path_params),
        )

        conn.commit()
        fk_violations = len(list(conn.execute("PRAGMA foreign_key_check")))
    finally:
        conn.close()

    return {
        "orphan_performance_data_removed": orphan_perf,
        "orphan_playlist_entities_removed": orphan_pe,
        "dangling_album_art_cleared": dangling_art,
        "playlists_last_edit_bumped": playlists_touched,
        "stub_analyzed_reset": stub_count,
        "bpm_synced_from_analyzed": bpm_synced,
        "fk_violations_remaining": fk_violations,
        "min_waveform_bytes": min_waveform_bytes,
        "merged_paths_scoped": bool(paths_filter),
        **pe_remap,
    }


def _resolve_engine_library_file(engine_dir: Path, rel: str) -> str | None:
    """Absolutna ścieżka pliku audio z symlinku Music/… w Engine Library."""
    raw = (rel or "").replace("\\", "/").strip()
    if not raw:
        return None
    p = engine_dir / raw
    try:
        if p.is_symlink() or p.is_file():
            return str(p.resolve())
    except OSError:
        pass
    return None


def sync_engine_track_metadata_from_export(
    engine_dir: Path,
    export_doc: dict,
    *,
    merged_paths: set[str] | None = None,
) -> dict:
    """
    Uzupełnia metadane Track w m.db po merge libdjinterop.
    Dopasowuje utwory po absolutnej ścieżce pliku (symlink Music/…), nie tylko po path w m.db.
    """
    import sqlite3
    from tag_writer import strip_rating_hack_from_comment

    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    tracks = export_doc.get("tracks") or []
    if not mdb.is_file() or not tracks:
        return {"skipped": True, "reason": "no_m_db_or_tracks"}

    paths_filter = None
    if merged_paths:
        paths_filter = {p.replace("\\", "/") for p in merged_paths if p}

    export_rows: list[tuple[str, dict]] = []
    for row in tracks:
        rel = (row.get("relative_path") or "").replace("\\", "/")
        if rel and (paths_filter is None or rel in paths_filter):
            export_rows.append((rel, row))

    updated = 0
    bpm_filled = 0
    rating_filled = 0
    path_realigned = 0
    matched_by_abs = 0
    conn = sqlite3.connect(str(mdb))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        abs_to_tid: dict[str, int] = {}
        path_to_tid: dict[str, int] = {}
        fn_bytes_to_tid: dict[tuple[str, int], int] = {}
        fn_to_tid: dict[str, int] = {}
        for tid, db_path, fn, fb in conn.execute(
            "SELECT id, path, filename, fileBytes FROM Track"
        ):
            tid = int(tid)
            norm_path = (db_path or "").replace("\\", "/")
            path_to_tid[norm_path] = tid
            abs_key = _resolve_engine_library_file(engine_dir, db_path or "")
            if abs_key:
                abs_to_tid[abs_key] = tid
            filename = (fn or Path(norm_path).name).lower()
            file_bytes = int(fb or 0)
            if file_bytes > 0:
                fn_bytes_to_tid[(filename, file_bytes)] = tid
            fn_to_tid.setdefault(filename, tid)

        used_paths = set(path_to_tid.keys())

        matched_by_filename = 0
        for rel, row in export_rows:
            tid = path_to_tid.get(rel)
            if tid is None:
                abs_key = _resolve_engine_library_file(engine_dir, rel)
                if abs_key:
                    tid = abs_to_tid.get(abs_key)
                    if tid is not None:
                        matched_by_abs += 1
            if tid is None:
                export_fn = Path(rel).name.lower()
                export_bytes = int(row.get("file_bytes") or 0)
                if export_bytes > 0:
                    tid = fn_bytes_to_tid.get((export_fn, export_bytes))
                    if tid is not None:
                        matched_by_filename += 1
                if tid is None:
                    tid = fn_to_tid.get(export_fn)
                    if tid is not None:
                        matched_by_filename += 1
            if tid is None:
                continue

            cur = conn.execute(
                """
                SELECT id, path, title, artist, album, genre, comment, year, bpm, rating
                FROM Track WHERE id = ?
                """,
                (tid,),
            ).fetchone()
            if not cur:
                continue
            _, cur_path, cur_title, cur_artist, cur_album, cur_genre, cur_comment, cur_year, cur_bpm, cur_rating = cur

            new_title = (row.get("title") or "").strip()
            new_artist = (row.get("artist") or "").strip()
            new_album = (row.get("album") or "").strip()
            new_genre = (row.get("genre") or "").strip()
            new_comment = strip_rating_hack_from_comment(row.get("comment") or "")
            new_year = int(row.get("year") or 0)
            new_bpm = int(round(float(row.get("bpm") or 0)))
            new_rating = int(row.get("rating") or 0)

            title = new_title or (cur_title or "")
            artist = new_artist or (cur_artist or "")
            album = new_album if new_album else (cur_album or "")
            genre = new_genre if new_genre else (cur_genre or "")
            comment = new_comment
            if not comment and new_rating <= 0:
                comment = strip_rating_hack_from_comment(cur_comment or "")
            year = new_year if new_year > 0 else int(cur_year or 0)
            bpm = new_bpm if new_bpm > 0 else int(cur_bpm or 0)
            rating = new_rating if new_rating > 0 else int(cur_rating or 0)
            out_path = (cur_path or "").replace("\\", "/")
            if rel != out_path and rel not in used_paths:
                out_path = rel
                path_realigned += 1

            if new_bpm > 0 and not (cur_bpm or 0):
                bpm_filled += 1
            if new_rating > 0 and not (cur_rating or 0):
                rating_filled += 1

            if (
                out_path == (cur_path or "").replace("\\", "/")
                and title == (cur_title or "")
                and artist == (cur_artist or "")
                and album == (cur_album or "")
                and genre == (cur_genre or "")
                and comment == (cur_comment or "")
                and year == int(cur_year or 0)
                and bpm == int(cur_bpm or 0)
                and rating == int(cur_rating or 0)
            ):
                continue

            conn.execute(
                """
                UPDATE Track
                SET path = ?, title = ?, artist = ?, album = ?, genre = ?, comment = ?,
                    year = ?, bpm = ?, rating = ?
                WHERE id = ?
                """,
                (out_path, title, artist, album, genre, comment, year, bpm, rating, tid),
            )
            if out_path != (cur_path or "").replace("\\", "/"):
                used_paths.discard((cur_path or "").replace("\\", "/"))
                used_paths.add(out_path)
                path_to_tid[out_path] = tid
            updated += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "tracks_metadata_updated": updated,
        "bpm_filled": bpm_filled,
        "rating_filled": rating_filled,
        "path_realigned": path_realigned,
        "matched_by_abs": matched_by_abs,
        "matched_by_filename": matched_by_filename,
        "export_paths": len(export_rows),
    }


def audit_serato_engine_metadata(
    serato_dir: Path | None = None,
    engine_dir: Path | None = None,
    *,
    read_file_cues: bool = True,
) -> dict:
    """
    Porównuje metadane Serato (unified) vs Engine m.db.
    Cue/loops: PerformanceData.quickCues/loops > _ENGINE_STUB_CUE_BYTES (28 B), nie >8 B.
    """
    from serato_parser import prepare_serato_unified_for_engine
    from engine_generator import unified_to_engine_export_doc

    serato_base = serato_dir or (Path.home() / "Music" / "_Serato_")
    target = (engine_dir or default_engine_desktop_library()).resolve()
    mdb = target / "Database2" / "m.db"

    db = prepare_serato_unified_for_engine(serato_base, read_file_cues=read_file_cues)
    tracks = db.tracks or []
    serato = {
        "total": len(tracks),
        "title": sum(1 for t in tracks if t.title),
        "bpm": sum(1 for t in tracks if t.bpm and t.bpm > 0),
        "key": sum(1 for t in tracks if t.key),
        "rating": sum(1 for t in tracks if t.rating and t.rating > 0),
        "genre": sum(1 for t in tracks if t.genre),
        "comment": sum(1 for t in tracks if t.comment),
        "cues": sum(1 for t in tracks if t.cue_points),
        "loops": sum(1 for t in tracks if t.loops),
        "beatgrid": sum(1 for t in tracks if t.beatgrid),
    }

    export_doc = unified_to_engine_export_doc(
        db,
        engine_dir=target,
        merge_mode=True,
        engine_music_layout=True,
        prune_tracks_not_in_source=True,
    )
    exp_tracks = export_doc.get("tracks") or []
    exportable = {
        "total": len(exp_tracks),
        "bpm": sum(1 for t in exp_tracks if (t.get("bpm") or 0) > 0),
        "key": sum(1 for t in exp_tracks if t.get("key_camelot")),
        "rating": sum(1 for t in exp_tracks if (t.get("rating") or 0) > 0),
        "genre": sum(1 for t in exp_tracks if t.get("genre")),
        "comment": sum(1 for t in exp_tracks if t.get("comment")),
        "cues": sum(1 for t in exp_tracks if t.get("hot_cues")),
        "loops": sum(1 for t in exp_tracks if t.get("loops")),
        "beatgrid": sum(1 for t in exp_tracks if t.get("beatgrid")),
        "tracks_skipped": export_doc.get("tracks_skipped", 0),
    }

    engine: dict = {"mdb_ready": False}
    gaps: dict = {}
    if mdb.is_file():
        import sqlite3

        conn = sqlite3.connect(str(mdb))
        cols_p = [r[1] for r in conn.execute("PRAGMA table_info(PerformanceData)")]
        cue_threshold = _ENGINE_STUB_CUE_BYTES
        engine = {
            "mdb_ready": True,
            "performance_data_columns": cols_p,
            "total": conn.execute("SELECT COUNT(*) FROM Track").fetchone()[0],
            "title": conn.execute(
                "SELECT COUNT(*) FROM Track WHERE title IS NOT NULL AND title != ''"
            ).fetchone()[0],
            "bpm": conn.execute("SELECT COUNT(*) FROM Track WHERE bpm > 0").fetchone()[0],
            "bpmAnalyzed": conn.execute(
                "SELECT COUNT(*) FROM Track WHERE bpmAnalyzed IS NOT NULL AND bpmAnalyzed > 0"
            ).fetchone()[0],
            "key": conn.execute(
                "SELECT COUNT(*) FROM Track WHERE key IS NOT NULL AND key != 0"
            ).fetchone()[0],
            "rating": conn.execute(
                "SELECT COUNT(*) FROM Track WHERE rating > 0"
            ).fetchone()[0],
            "genre": conn.execute(
                "SELECT COUNT(*) FROM Track WHERE genre IS NOT NULL AND genre != ''"
            ).fetchone()[0],
            "comment": conn.execute(
                "SELECT COUNT(*) FROM Track WHERE comment IS NOT NULL AND comment != ''"
            ).fetchone()[0],
            "isAnalyzed": conn.execute(
                "SELECT COUNT(*) FROM Track WHERE isAnalyzed = 1"
            ).fetchone()[0],
        }
        if "quickCues" in cols_p:
            engine["cues"] = conn.execute(
                "SELECT COUNT(*) FROM PerformanceData "
                f"WHERE IFNULL(length(quickCues), 0) > {cue_threshold}"
            ).fetchone()[0]
        if "loops" in cols_p:
            engine["loops"] = conn.execute(
                "SELECT COUNT(*) FROM PerformanceData "
                f"WHERE IFNULL(length(loops), 0) > {cue_threshold}"
            ).fetchone()[0]
        if "beatData" in cols_p:
            engine["beatgrid"] = conn.execute(
                "SELECT COUNT(*) FROM PerformanceData "
                "WHERE IFNULL(length(beatData), 0) > 0"
            ).fetchone()[0]
        if "overviewWaveFormData" in cols_p:
            engine["waveforms"] = conn.execute(
                "SELECT COUNT(*) FROM PerformanceData "
                f"WHERE IFNULL(length(overviewWaveFormData), 0) >= {_ENGINE_MIN_WAVEFORM_BYTES}"
            ).fetchone()[0]
        conn.close()

        for key in (
            "total", "title", "bpm", "key", "rating", "genre", "comment", "cues", "loops", "beatgrid"
        ):
            if key in serato and key in engine:
                gaps[key] = serato[key] - engine[key]

    return {
        "ok": True,
        "serato_dir": str(serato_base),
        "engine_dir": str(target),
        "serato": serato,
        "exportable": exportable,
        "engine": engine,
        "gaps_serato_minus_engine": gaps,
        "note": (
            "Ujemne luki bpm/key oznaczają więcej danych w Engine (analiza). "
            "total: różnica = utwory Serato bez lokalnego pliku do eksportu."
        ),
    }


def cleanup_engine_legacy_playlists(engine_dir: Path | None = None) -> dict:
    """Usuwa stare płaskie playlisty „VDJ / …” z biblioteki Engine DJ."""
    target = (engine_dir or default_engine_desktop_library()).resolve()
    payload = {
        'engine_dir': str(target),
        'merge_mode': True,
        'clear_existing': False,
        'cleanup_legacy_vdj_playlists': True,
        'tracks': [],
        'playlists': [],
    }
    return run_engine_export(payload, target)


def run_engine_desktop_merge(export_doc: dict, engine_dir: Path | None = None) -> dict:
    """Bezpieczny merge VDJ → istniejąca biblioteka Engine DJ Desktop."""
    target = (engine_dir or default_engine_desktop_library()).resolve()
    if not target.is_dir():
        raise FileNotFoundError(
            f"Brak biblioteki Engine DJ: {target}. Uruchom Engine DJ Desktop raz, aby ją utworzyć."
        )
    assert_engine_library_safe_for_write(target)
    schema_validation = assert_engine_schema_compatible(target)
    backup_stats = backup_engine_database2(target, label="pre-merge")

    doc = dict(export_doc)
    doc["merge_mode"] = True
    doc["clear_existing"] = False

    merged_paths = _merged_paths_from_export(export_doc)
    perf_snapshots = snapshot_engine_performance(target, merged_paths)

    result = run_engine_export(doc, target)

    restore_stats = restore_engine_performance(target, perf_snapshots)
    metadata_stats = sync_engine_track_metadata_from_export(
        target, export_doc, merged_paths=merged_paths
    )
    repair_stats = repair_engine_post_merge(target, merged_paths=merged_paths)
    # Ponownie po repair — stub reset mógł wyczyścić bpmAnalyzed, ale bpm z importu zostaje.
    metadata_stats_after = sync_engine_track_metadata_from_export(
        target, export_doc, merged_paths=merged_paths
    )
    art_stats = sync_engine_album_art(target, merged_paths)
    from engine_file_info import sync_engine_file_info

    file_info_stats = sync_engine_file_info(target, merged_paths)
    result.update(restore_stats)
    result.update(repair_stats)
    result.update(metadata_stats)
    result["metadata_sync_after_repair"] = metadata_stats_after
    result.update(art_stats)
    result.update(file_info_stats)
    result["performance_snapshots"] = len(perf_snapshots)
    result["engine_backup"] = backup_stats
    result["engine_schema_validation"] = schema_validation
    return result
