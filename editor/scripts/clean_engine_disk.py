#!/usr/bin/env python3
"""
Fizyczne czyszczenie ukrytego cache Engine DJ (modele AI, temp, backupy).

  python3 scripts/clean_engine_disk.py scan
  python3 scripts/clean_engine_disk.py clean
  python3 scripts/clean_engine_disk.py clean --clear-stems   # po migracji na Patriot
  python3 scripts/clean_engine_disk.py clean --vacuum-mdb    # optymalizacja m.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine_disk_cleanup import (  # noqa: E402
    clean_engine_hidden_cache,
    scan_engine_disk_usage,
)
from engine_libdjinterop import default_engine_desktop_library  # noqa: E402
from engine_stems import (  # noqa: E402
    DEFAULT_PATRIOT_ENGINE,
    get_library_uuid,
    infer_library_uuid_from_stems,
    list_stem_files,
    match_mac_to_patriot_tracks,
    migrate_stems_to_patriot,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Czyści ukryty cache Engine DJ na Macu (nie tylko odnośniki w aplikacji)"
    )
    parser.add_argument("--mac", type=Path, default=None)
    parser.add_argument("--patriot", type=Path, default=DEFAULT_PATRIOT_ENGINE)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="Pokaż cache Engine DJ do usunięcia")
    p_clean = sub.add_parser("clean", help="Usuń cache + opcjonalnie stemy z Maca")
    p_clean.add_argument(
        "--clear-stems",
        action="store_true",
        help="Usuń wszystkie .stems z Mac Stems/ (najpierw migruje na Patriot jeśli podłączony)",
    )
    p_clean.add_argument(
        "--keep-engine",
        action="store_true",
        help="Nie zamykaj Engine DJ",
    )
    p_clean.add_argument(
        "--vacuum-mdb",
        action="store_true",
        help="VACUUM m.db (Library Optimization — Engine musi być zamknięty)",
    )
    p_clean.add_argument(
        "--no-trash",
        action="store_true",
        help="Nie czyść .stems z Kosza",
    )

    args = parser.parse_args()
    mac = args.mac or default_engine_desktop_library()
    patriot = args.patriot

    try:
        if args.cmd == "scan":
            print(json.dumps(scan_engine_disk_usage(mac), ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "clean" and patriot.is_dir():
            migrate_stems_to_patriot(
                mac, patriot, delete_mac=True, allow_engine_running=args.keep_engine
            )
            # Usuń stemy już na Patriot
            try:
                mac_uuid = infer_library_uuid_from_stems(mac / "Stems") or get_library_uuid(mac)
                id_map = match_mac_to_patriot_tracks(mac, patriot)
                pat_stems = list_stem_files(patriot, library_uuid=mac_uuid)
                for mac_id, src in list(list_stem_files(mac, library_uuid=mac_uuid).items()):
                    if id_map.get(mac_id) in pat_stems and src.is_file():
                        src.unlink(missing_ok=True)
            except OSError:
                pass

        out = clean_engine_hidden_cache(
            mac,
            quit_engine=not args.keep_engine,
            clear_mac_stems=args.clear_stems,
            vacuum_mdb=args.vacuum_mdb,
            empty_trash=not args.no_trash,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok", True) else 1
    except Exception as ex:
        print(json.dumps({"ok": False, "error": str(ex)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
