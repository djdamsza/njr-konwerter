#!/usr/bin/env python3
"""
Naprawa ścieżek Serato (database V2 + crates + root.sqlite) z backupem.

Użycie — Serato MUSI być zamknięty:
  cd editor && python3 scripts/fix_serato_paths_with_backup.py
  python3 scripts/fix_serato_paths_with_backup.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

EDITOR = Path(__file__).resolve().parent.parent
if str(EDITOR) not in sys.path:
    sys.path.insert(0, str(EDITOR))

from serato_library_sqlite import repair_root_sqlite_path_links
from serato_parser import load_serato_database_v2, normalize_and_dedupe_serato_library


def _serato_dirs() -> tuple[Path, Path]:
    serato_dir = Path.home() / "Music" / "_Serato_"
    library_dir = Path.home() / "Library/Application Support/Serato/Library"
    return serato_dir, library_dir


def _count_broken_paths(db_bytes: bytes) -> int:
    user = Path.home().name
    needle = f"Users/{user}/Music/Users/{user}/"
    db = load_serato_database_v2(db_bytes)
    n = 0
    for t in db.tracks:
        p = (t.path or "").replace("\\", "/")
        if needle in p:
            n += 1
    return n


def _backup_files(backup_dir: Path, serato_dir: Path, library_dir: Path) -> list[str]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for label, src in (
        ("database V2", serato_dir / "database V2"),
        ("Database V2", serato_dir / "Database V2"),
        ("root.sqlite", library_dir / "root.sqlite"),
    ):
        if src.is_file():
            dst = backup_dir / src.name.replace(" ", "_")
            shutil.copy2(src, dst)
            copied.append(str(dst))
    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "serato_dir": str(serato_dir),
        "library_dir": str(library_dir),
        "files": copied,
        "note": "Przywrócenie: zamknij Serato, skopiuj pliki z powrotem, uruchom Serato.",
    }
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    copied.append(str(manifest_path))
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Napraw ścieżki Serato z backupem")
    parser.add_argument("--dry-run", action="store_true", help="Tylko raport, bez zapisu")
    args = parser.parse_args()

    serato_dir, library_dir = _serato_dirs()
    db_file = serato_dir / "database V2"
    if not db_file.is_file():
        db_file = serato_dir / "Database V2"
    if not db_file.is_file():
        print(f"Brak database V2 w {serato_dir}", file=sys.stderr)
        return 1

    raw = db_file.read_bytes()
    broken_before = _count_broken_paths(raw)
    print(f"database V2: {db_file}")
    print(f"Zepsute ścieżki (podwójny Music/Users): {broken_before}")

    if args.dry_run:
        from serato_parser import normalize_serato_blob_to_relative, dedupe_serato_database_v2, purge_serato_stale_duplicates

        norm, rewrites = normalize_serato_blob_to_relative(raw)
        broken_after_norm = _count_broken_paths(norm)
        cleaned, dstats = dedupe_serato_database_v2(norm, prefer_style="relative")
        cleaned2, pst = purge_serato_stale_duplicates(cleaned)
        broken_after = _count_broken_paths(cleaned2)
        root_preview = repair_root_sqlite_path_links(library_dir, dry_run=True)
        print("\n[dry-run]")
        print(f"  path rewrites (V2): {rewrites}")
        print(f"  broken after normalize: {broken_after_norm}")
        print(f"  removed clones: {dstats.get('removed', 0)}")
        print(f"  purge remapped: {pst.get('remapped', 0)}, removed: {pst.get('removed', 0)}")
        print(f"  broken after full V2 pipeline: {broken_after}")
        print(f"  root.sqlite preview: {root_preview}")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = serato_dir / "backups" / f"njr-path-fix-{stamp}"
    copied = _backup_files(backup_dir, serato_dir, library_dir)
    print(f"\nBackup: {backup_dir}")
    for p in copied:
        print(f"  - {p}")

    stats = normalize_and_dedupe_serato_library(serato_dir, purge_stale=True)
    root_stats = repair_root_sqlite_path_links(library_dir, dry_run=False)

    raw_after = db_file.read_bytes()
    broken_after = _count_broken_paths(raw_after)

    print("\n=== database V2 / crates ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  broken_paths_remaining: {broken_after}")

    print("\n=== root.sqlite ===")
    for k, v in root_stats.items():
        print(f"  {k}: {v}")

    print("\nGotowe. Uruchom Serato i przetestuj Autoplay na crate imprezowym.")
    print(f"Przywracanie (gdyby coś poszło nie tak): pliki w {backup_dir}")
    return 0 if root_stats.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
