#!/usr/bin/env python3
"""
Diagnoza i naprawa utworów blokujących „Create stems” na całej kolekcji.

Engine DJ: „Stem render skipped — One or more tracks are missing”
= w zaznaczeniu jest choć jeden utwór bez pliku / bez bitrate / streaming.

Użycie:
  python3 scripts/fix_stems_blockers.py diagnose
  # Zamknij Engine DJ (Cmd+Q), potem:
  python3 scripts/fix_stems_blockers.py fix
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine_file_info import sync_engine_file_info
from engine_libdjinterop import default_engine_desktop_library, is_engine_desktop_running


def diagnose_stem_render_blockers(engine_dir: Path | None = None) -> dict:
    engine_dir = (engine_dir or default_engine_desktop_library()).resolve()
    mdb = engine_dir / "Database2" / "m.db"
    conn = sqlite3.connect(f"file:{mdb.as_posix()}?mode=ro", uri=True, timeout=60)

    rows = conn.execute(
        """
        SELECT id, path, title, artist, bitrate, fileBytes, isAvailable
        FROM Track
        """
    ).fetchall()
    conn.close()

    blockers: list[dict] = []
    for tid, path, title, artist, br, fb, avail in rows:
        p = (path or "").replace("\\", "/")
        reasons: list[str] = []
        low = p.lower()
        if any(x in low for x in ("soundcloud", "tidal", "beatport", "beatsource", "://")):
            reasons.append("streaming")
        if not p:
            reasons.append("empty_path")
        else:
            try:
                if not (engine_dir / p).resolve().is_file():
                    reasons.append("missing_file")
            except OSError:
                reasons.append("missing_file")
        if avail in (0, None):
            reasons.append("marked_unavailable")
        if (not br or br == 0) or (not fb or fb == 0):
            reasons.append("no_bitrate_or_size")
        if reasons:
            blockers.append(
                {
                    "id": tid,
                    "title": title or "",
                    "artist": artist or "",
                    "path": p,
                    "reasons": reasons,
                    "bitrate": br,
                    "fileBytes": fb,
                    "isAvailable": avail,
                }
            )

    fixable_file_info = sum(
        1
        for b in blockers
        if "no_bitrate_or_size" in b["reasons"]
        and "missing_file" not in b["reasons"]
        and "streaming" not in b["reasons"]
    )
    hard_blockers = [
        b
        for b in blockers
        if "missing_file" in b["reasons"] or "streaming" in b["reasons"]
    ]

    return {
        "ok": True,
        "engine_dir": str(engine_dir),
        "total_tracks": len(rows),
        "blocker_count": len(blockers),
        "fixable_file_info": fixable_file_info,
        "hard_blocker_count": len(hard_blockers),
        "hard_blockers": hard_blockers,
        "blockers": blockers,
        "hint": (
            "Zamknij Engine DJ → fix → Create stems na kolekcji bez "
            f"{len(hard_blockers)} utworów na stałe (lub usuń je z biblioteki)."
        ),
    }


def fix_stem_render_blockers(engine_dir: Path | None = None) -> dict:
    if is_engine_desktop_running():
        raise RuntimeError("Zamknij Engine DJ (Cmd+Q) przed naprawą m.db.")

    engine_dir = (engine_dir or default_engine_desktop_library()).resolve()
    diag = diagnose_stem_render_blockers(engine_dir)

    file_info = sync_engine_file_info(engine_dir)

    mdb = engine_dir / "Database2" / "m.db"
    conn = sqlite3.connect(str(mdb))
    marked_unavailable = 0
    try:
        for b in diag["hard_blockers"]:
            if "missing_file" in b["reasons"] or "streaming" in b["reasons"]:
                conn.execute(
                    "UPDATE Track SET isAvailable = 0 WHERE id = ?",
                    (b["id"],),
                )
                marked_unavailable += 1
        conn.commit()
    finally:
        conn.close()

    after = diagnose_stem_render_blockers(engine_dir)
    return {
        "ok": True,
        "file_info": file_info,
        "marked_unavailable": marked_unavailable,
        "before_blockers": diag["blocker_count"],
        "after_blockers": after["blocker_count"],
        "remaining_hard_blockers": after["hard_blockers"],
        "remaining_blockers": after["blockers"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnoza blokad stemów Engine DJ")
    parser.add_argument("--mac", type=Path, default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diagnose", help="Lista utworów blokujących render")
    sub.add_parser("fix", help="Uzupełnij bitrate + oznacz brakujące jako niedostępne")
    args = parser.parse_args()
    mac = args.mac or default_engine_desktop_library()

    try:
        if args.cmd == "diagnose":
            out = diagnose_stem_render_blockers(mac)
        else:
            out = fix_stem_render_blockers(mac)
    except RuntimeError as ex:
        print(json.dumps({"ok": False, "error": str(ex)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
