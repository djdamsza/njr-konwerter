#!/usr/bin/env python3
"""Przepięcie ścieżek Serato na pliki z Dysku Google (bez kopiowania muzyki).

Użycie (Serato ZAMKNIĘTE):
  python3 remap_serato_google_drive.py
  python3 remap_serato_google_drive.py --dry-run
  python3 remap_serato_google_drive.py --google-drive "G:\\Mój dysk"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EDITOR = Path(__file__).resolve().parent
if str(EDITOR) not in sys.path:
    sys.path.insert(0, str(EDITOR))

from serato_gdrive import remap_serato_library_to_google_drive


def main() -> int:
    p = argparse.ArgumentParser(
        description="Przepina database V2 / crates / root.sqlite na Dysk Google."
    )
    p.add_argument("--dry-run", action="store_true", help="Tylko raport, bez zapisu")
    p.add_argument("--google-drive", default="", help="Folder lustrzanych plików GDrive")
    p.add_argument("--serato-dir", default="", help="Folder _Serato_ (domyślnie ~/Music/_Serato_)")
    p.add_argument("--no-sqlite", action="store_true", help="Pomiń Serato 4 root.sqlite")
    args = p.parse_args()

    result = remap_serato_library_to_google_drive(
        Path(args.serato_dir).expanduser() if args.serato_dir else None,
        google_drive=args.google_drive or None,
        dry_run=args.dry_run,
        include_sqlite=not args.no_sqlite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        return 2
    if args.dry_run:
        print("\n(dry-run — bez zapisu)", file=sys.stderr)
    else:
        print(
            "\nGotowe. Pliki zostają na Dysku Google. Uruchom Serato ponownie.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
