#!/usr/bin/env python3
"""
Partiami: playlista stemów na Mac → render w Engine DJ → migracja na Patriot → usuń z Maca.

Pełna automatyzacja (render + pętla):
  python3 scripts/auto_stems_to_patriot.py run --max-batches 1

Ręczny render w Engine (skrypt czeka na pliki .stems):
  python3 scripts/auto_stems_to_patriot.py run --manual-render --max-batches 1

Klasyczny tryb krok po kroku:
  python3 scripts/migrate_stems_to_patriot.py status
  python3 scripts/migrate_stems_to_patriot.py prepare --batch 15
  # Engine DJ: otwórz „NJR / NJR Stems Batch” → Create stems
  python3 scripts/migrate_stems_to_patriot.py migrate --batch 15 --delete-mac

Powtarzaj migrate/prepare aż patriot_tracks_needing_stems = 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine_stems import (  # noqa: E402
    DEFAULT_PATRIOT_ENGINE,
    migrate_stems_to_patriot,
    prepare_stems_batch_playlist,
    stems_migration_status,
)
from engine_libdjinterop import default_engine_desktop_library  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Engine DJ: stemy Mac → Patriot")
    parser.add_argument(
        "--mac",
        type=Path,
        default=None,
        help="Mac Engine Library (domyślnie ~/Music/Engine Library)",
    )
    parser.add_argument(
        "--patriot",
        type=Path,
        default=DEFAULT_PATRIOT_ENGINE,
        help="Patriot Engine Library",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Podsumowanie stemów i miejsca na dysku")

    p_prepare = sub.add_parser("prepare", help="Playlista partii do renderu w Engine")
    p_prepare.add_argument("--batch", type=int, default=20)

    p_migrate = sub.add_parser("migrate", help="Przenieś stemy Mac → Patriot")
    p_migrate.add_argument("--batch", type=int, default=None)
    p_migrate.add_argument(
        "--delete-mac",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Usuń pliki .stems z Maca po skopiowaniu (domyślnie: tak)",
    )
    p_migrate.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    mac = args.mac or default_engine_desktop_library()
    patriot = args.patriot

    try:
        if args.cmd == "status":
            out = stems_migration_status(mac, patriot)
        elif args.cmd == "prepare":
            out = prepare_stems_batch_playlist(
                mac, patriot, batch_size=args.batch
            )
        else:
            out = migrate_stems_to_patriot(
                mac,
                patriot,
                batch_size=args.batch,
                delete_mac=args.delete_mac,
                dry_run=args.dry_run,
            )
    except RuntimeError as ex:
        print(json.dumps({"ok": False, "error": str(ex)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
