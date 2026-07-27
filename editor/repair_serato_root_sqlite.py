#!/usr/bin/env python3
"""Naprawa złych ścieżek / duplikatów w bibliotece Serato (root.sqlite + database V2).

Użycie (Serato ZAMKNIĘTE):
  python3 repair_serato_root_sqlite.py
  python3 repair_serato_root_sqlite.py --dry-run
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

EDITOR = Path(__file__).resolve().parent
if str(EDITOR) not in sys.path:
    sys.path.insert(0, str(EDITOR))

from serato_library_sqlite import repair_serato_library_paths

LIB = Path.home() / "Library/Application Support/Serato/Library"
ROOT = LIB / "root.sqlite"


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    if not ROOT.is_file():
        print(f"Brak {ROOT}", file=sys.stderr)
        return 1

    if not dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = LIB / f"root.sqlite.pre-repair-{ts}.bak"
        shutil.copy2(ROOT, backup)
        print(f"Kopia root.sqlite: {backup}")

    result = repair_serato_library_paths(dry_run=dry_run)
    print(result)
    if not result.get("ok"):
        return 2
    if dry_run:
        print("\n(dry-run — bez zapisu)")
    else:
        print("\nGotowe. Uruchom Serato ponownie (Rescan / Analyze jeśli trzeba).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
