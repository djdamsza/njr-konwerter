#!/usr/bin/env python3
"""Porównanie mapowania VDJ→Serato: meta (legacy) vs path/link (nowe)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

EDITOR = Path(__file__).resolve().parent
if str(EDITOR) not in sys.path:
    sys.path.insert(0, str(EDITOR))


def main() -> int:
    from vdj_parser import load_database
    from vdj_path_mapping import compare_vdj_serato_mapping

    vdj_db = Path.home() / "Library/Application Support/VirtualDJ/database.xml"
    if not vdj_db.is_file():
        print(f"Brak bazy VDJ: {vdj_db}", file=sys.stderr)
        return 1

    print(f"Ładowanie {vdj_db} …")
    songs, version = load_database(str(vdj_db))
    print(f"Utworów w bazie: {len(songs)} (VDJ {version})")

    result = compare_vdj_serato_mapping(songs)
    print(f"\nSprawdzono Tidal/cache: {result['checked']}")
    print(f"Identyczne mapowanie: {result['same']}")
    print(f"Rozbieżności (poprawione): {result['discrepancy_count']}")
    print(f"\nNowe statystyki: {json.dumps(result['new_stats'], indent=2, default=str)}")

    disc = result["discrepancies"]
    # meta → inny plik (najważniejsze)
    wrong_file = [
        d
        for d in disc
        if d.get("old_export")
        and d.get("new_export")
        and not str(d["old_export"]).startswith("streaming:")
        and not str(d["new_export"]).startswith("streaming:")
        and d["old_export"] != d["new_export"]
    ]
    meta_to_stream = [
        d
        for d in disc
        if d.get("old_export")
        and not str(d["old_export"]).startswith("streaming:")
        and (
            not d.get("new_export")
            or str(d["new_export"]).startswith("streaming:")
        )
    ]
    stream_to_local = [
        d
        for d in disc
        if str(d.get("old_export") or "").startswith("streaming:")
        and d.get("new_export")
        and not str(d["new_export"]).startswith("streaming:")
    ]

    print(f"\n--- Meta trafiła w INNY plik ({len(wrong_file)}) ---")
    for row in wrong_file[:30]:
        print(
            f"  {row['artist']} — {row['title'][:50]}\n"
            f"    VDJ: {row['vdj_path'][:80]}\n"
            f"    STARE (meta): {Path(row['old_export']).name}\n"
            f"    NOWE (path):  {Path(row['new_export']).name}"
        )
    if len(wrong_file) > 30:
        print(f"  … i {len(wrong_file) - 30} więcej")

    print(f"\n--- Meta → lokalny, teraz streaming/brak ({len(meta_to_stream)}) ---")
    for row in meta_to_stream[:15]:
        print(
            f"  {row['artist']} — {row['title'][:40]}\n"
            f"    było: {Path(row['old_export']).name if row['old_export'] else '?'}\n"
            f"    jest: {row['new_export'] or '(brak)'}"
        )

    print(f"\n--- Streaming → lokalny po linku ({len(stream_to_local)}) ---")
    for row in stream_to_local[:15]:
        print(
            f"  {row['artist']} — {row['title'][:40]}\n"
            f"    link → {Path(row['new_export']).name}"
        )

    out = EDITOR / "vdj_serato_mapping_discrepancies.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nPełny raport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
