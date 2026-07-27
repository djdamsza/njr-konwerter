"""
Uzupełnia bitrate i fileBytes w m.db — wymagane przez Engine DJ do renderu stemów.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from file_analyzer import _get_bitrate


def probe_audio_file_info(file_path: Path) -> tuple[int | None, int | None]:
    """Zwraca (bitrate_kbps, file_bytes) odczytane z pliku na dysku."""
    if not file_path.is_file():
        return None, None
    bitrate = _get_bitrate(str(file_path))
    try:
        file_bytes = file_path.stat().st_size
    except OSError:
        file_bytes = None
    return bitrate, file_bytes


def sync_engine_file_info(
    engine_dir: Path,
    paths: set[str] | None = None,
) -> dict:
    """
    Ustawia Track.bitrate i Track.fileBytes z metadanych / rozmiaru pliku.
    paths — opcjonalnie tylko te ścieżki względne (po merge: utwory z VDJ).
    """
    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file():
        return {"skipped": True, "reason": "no_m_db"}

    path_filter = None
    if paths:
        path_filter = {p.replace("\\", "/") for p in paths if p}

    conn = sqlite3.connect(str(mdb))
    updated = 0
    missing_file = 0
    no_bitrate = 0
    scanned = 0
    try:
        rows = conn.execute(
            "SELECT id, path, bitrate, fileBytes FROM Track WHERE isAvailable=1"
        ).fetchall()
        for track_id, rel_path, cur_br, cur_fb in rows:
            rel = (rel_path or "").replace("\\", "/")
            if path_filter is not None and rel not in path_filter:
                continue
            if cur_br and cur_fb:
                continue
            scanned += 1
            abs_path = engine_dir / rel
            if not abs_path.is_file():
                missing_file += 1
                continue
            bitrate, file_bytes = probe_audio_file_info(abs_path)
            if not bitrate and not file_bytes:
                no_bitrate += 1
                continue
            new_br = bitrate if bitrate else (cur_br or 0)
            new_fb = file_bytes if file_bytes else cur_fb
            if not new_br and new_fb:
                # WAV / edge case: Engine wymaga bitrate > 0 do stemów
                new_br = 1411
            if not new_fb:
                no_bitrate += 1
                continue
            if new_br == (cur_br or 0) and new_fb == (cur_fb or 0):
                continue
            conn.execute(
                """
                UPDATE Track
                SET bitrate = ?, fileBytes = ?
                WHERE id = ?
                """,
                (new_br, new_fb, track_id),
            )
            updated += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "file_info_scanned": scanned,
        "file_info_updated": updated,
        "file_info_missing_file": missing_file,
        "file_info_no_probe": no_bitrate,
    }
