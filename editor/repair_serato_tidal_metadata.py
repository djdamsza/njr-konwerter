#!/usr/bin/env python3
"""Naprawa placeholderów „Tidal 12345” w tidal.sqlite (tytuły z VDJ / Metadata XML).

Użycie (Serato ZAMKNIĘTE):
  python3 repair_serato_tidal_metadata.py
  python3 repair_serato_tidal_metadata.py --dry-run
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

EDITOR = Path(__file__).resolve().parent
if str(EDITOR) not in sys.path:
    sys.path.insert(0, str(EDITOR))

from serato_library_sqlite import repair_tidal_sqlite_metadata

LIB = Path.home() / "Library/Application Support/Serato/Library"
TIDAL = LIB / "tidal.sqlite"


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    if not TIDAL.is_file():
        print(f"Brak {TIDAL}", file=sys.stderr)
        return 1

    if not dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = LIB / f"tidal.sqlite.pre-tidal-meta-{ts}.bak"
        shutil.copy2(TIDAL, backup)
        print(f"Kopia tidal.sqlite: {backup}")

    result = repair_tidal_sqlite_metadata(dry_run=dry_run)
    print(result)
    if not result.get("ok"):
        return 2
    if dry_run:
        print("\n(dry-run — bez zapisu)")
    else:
        print("\nGotowe. Uruchom Serato ponownie.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
