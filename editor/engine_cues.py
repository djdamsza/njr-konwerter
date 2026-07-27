"""
Przywracanie i synchronizacja cue pointów Engine DJ (PerformanceData.quickCues).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_ENGINE_STUB_CUE_BYTES = 28


def restore_engine_cues_from_reference(
    engine_dir: Path,
    reference_mdb: Path,
    *,
    paths: set[str] | None = None,
) -> dict:
    """
    Kopiuje quickCues (i loops) z innej bazy m.db do aktywnej biblioteki.
    Przywraca tylko gdy bieżący blob to pusty stub (≤28 B), a referencja ma prawdziwe cue.
    """
    engine_dir = engine_dir.resolve()
    reference_mdb = reference_mdb.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file():
        return {"skipped": True, "reason": "no_m_db"}
    if not reference_mdb.is_file():
        return {"skipped": True, "reason": "no_reference_mdb"}

    path_filter = None
    if paths:
        path_filter = {p.replace("\\", "/") for p in paths if p}

    ref = sqlite3.connect(str(reference_mdb))
    cur = sqlite3.connect(str(mdb))
    restored = 0
    skipped_has_cues = 0
    no_match = 0
    try:
        ref_rows = ref.execute(
            """
            SELECT t.path, p.quickCues, p.loops, IFNULL(length(p.quickCues), 0)
            FROM Track t
            JOIN PerformanceData p ON p.trackId = t.id
            WHERE IFNULL(length(p.quickCues), 0) > ?
            """,
            (_ENGINE_STUB_CUE_BYTES,),
        ).fetchall()

        for rel_path, quick_cues, loops, _ in ref_rows:
            rel = (rel_path or "").replace("\\", "/")
            if path_filter is not None and rel not in path_filter:
                continue
            row = cur.execute(
                """
                SELECT t.id, IFNULL(length(p.quickCues), 0)
                FROM Track t
                JOIN PerformanceData p ON p.trackId = t.id
                WHERE t.path = ?
                """,
                (rel,),
            ).fetchone()
            if not row:
                no_match += 1
                continue
            track_id, cur_len = row
            if cur_len > _ENGINE_STUB_CUE_BYTES:
                skipped_has_cues += 1
                continue
            cur.execute(
                """
                UPDATE PerformanceData
                SET quickCues = ?, loops = COALESCE(?, loops)
                WHERE trackId = ?
                """,
                (quick_cues, loops, track_id),
            )
            restored += 1
        cur.commit()
    finally:
        ref.close()
        cur.close()

    return {
        "cues_restored_from_reference": restored,
        "cues_skipped_already_present": skipped_has_cues,
        "cues_no_matching_track": no_match,
        "reference_mdb": str(reference_mdb),
    }


def default_pre_repair_backup(engine_dir: Path) -> Path | None:
    """Najnowszy backup m.db.pre-repair-* w Database2."""
    dbdir = engine_dir.resolve() / "Database2"
    if not dbdir.is_dir():
        return None
    backups = sorted(dbdir.glob("m.db.pre-repair-*"), reverse=True)
    return backups[0] if backups else None
