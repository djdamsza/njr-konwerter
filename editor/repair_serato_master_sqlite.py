#!/usr/bin/env python3
"""Naprawa master.sqlite po uszkodzeniu FK (container_asset → location_container).

Serato odmawia otwarcia biblioteki z błędem:
  Failed foreign_key_check

Użycie (Serato ZAMKNIĘTE):
  python3 repair_serato_master_sqlite.py
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

EDITOR = Path(__file__).resolve().parent
if str(EDITOR) not in sys.path:
    sys.path.insert(0, str(EDITOR))

from serato_library_sqlite import repair_master_sqlite_foreign_keys

LIB = Path.home() / "Library/Application Support/Serato/Library"
MASTER = LIB / "master.sqlite"


def main() -> int:
    if not MASTER.is_file():
        print(f"Brak {MASTER}", file=sys.stderr)
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = LIB / f"master.sqlite.pre-repair-{ts}.bak"
    shutil.copy2(MASTER, backup)
    print(f"Kopia zapasowa: {backup}")

    result = repair_master_sqlite_foreign_keys()
    print(f"Usunięto sierocie container_asset: {result.get('removed_orphan_container_asset', 0)}")
    if result.get("ok"):
        print("PRAGMA foreign_key_check: OK")
        print("\nGotowe. Otwórz Serato ponownie.")
        return 0
    print("UWAGA:", result, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
