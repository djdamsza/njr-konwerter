#!/usr/bin/env python3
"""
Automatyczny pipeline stemów: Mac (Engine DJ) → Patriot.

Przykłady:
  # Status i sugerowana wielkość partii
  python3 scripts/auto_stems_to_patriot.py status

  # Jedna partia — pełna automatyzacja (wymaga Dostępności dla Terminala)
  python3 scripts/auto_stems_to_patriot.py run --max-batches 1

  # Nocna pętla aż skończą się stemy na Patriot
  python3 scripts/auto_stems_to_patriot.py run

  # Bez AppleScript — sam przygotuje playlistę, Ty klikasz Create stems
  python3 scripts/auto_stems_to_patriot.py run --manual-render --max-batches 1

  # Tylko render bieżącej partii (playlista już przygotowana)
  python3 scripts/auto_stems_to_patriot.py render --manual-render

  # Watcher w tle — Engine renderuje wszystko, skrypt przenosi na Patriot na bieżąco
  python3 scripts/auto_stems_to_patriot.py watch
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine_libdjinterop import default_engine_desktop_library  # noqa: E402
from engine_stems import (  # noqa: E402
    DEFAULT_PATRIOT_ENGINE,
    migrate_stems_to_patriot,
    prepare_stems_batch_playlist,
    stems_migration_status,
)
from engine_stems_render import (  # noqa: E402
    compute_auto_batch_size,
    render_stems_batch,
    run_auto_stems_pipeline,
    watch_and_migrate_stems,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automatyczne stemy Engine DJ → Patriot (NJR)"
    )
    parser.add_argument("--mac", type=Path, default=None)
    parser.add_argument("--patriot", type=Path, default=DEFAULT_PATRIOT_ENGINE)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Podsumowanie + sugerowana partia")

    p_run = sub.add_parser("run", help="Pętla: prepare → render → migrate")
    p_run.add_argument("--batch", type=int, default=None, help="Wielkość partii")
    p_run.add_argument(
        "--max-batches",
        type=int,
        default=0,
        help="Limit partii (0 = bez limitu)",
    )
    p_run.add_argument(
        "--manual-render",
        action="store_true",
        help="Nie klika Create stems — tylko czeka na pliki .stems",
    )
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument(
        "--no-delete-mac",
        action="store_true",
        help="Zostaw .stems na Macu po migracji",
    )
    p_run.add_argument(
        "--render-timeout",
        type=float,
        default=7200,
        help="Sekundy na render jednej partii",
    )

    p_render = sub.add_parser("render", help="Render bieżącej partii NJR Stems Batch")
    p_render.add_argument(
        "--manual-render",
        action="store_true",
        help="Bez AppleScript — kliknij Create stems ręcznie",
    )
    p_render.add_argument("--render-timeout", type=float, default=7200)

    p_prepare = sub.add_parser("prepare", help="Tylko playlista partii")
    p_prepare.add_argument("--batch", type=int, default=None)

    p_migrate = sub.add_parser("migrate", help="Tylko migracja Mac → Patriot")
    p_migrate.add_argument("--batch", type=int, default=None)
    p_migrate.add_argument(
        "--no-delete-mac",
        action="store_true",
    )
    p_migrate.add_argument("--dry-run", action="store_true")

    p_watch = sub.add_parser(
        "watch",
        help="Watcher: przenoś gotowe .stems na Patriot podczas renderu Engine DJ",
    )
    p_watch.add_argument(
        "--poll",
        type=float,
        default=20.0,
        help="Co ile sekund skanować folder Stems/ (domyślnie 20)",
    )
    p_watch.add_argument(
        "--stop-after-idle",
        type=float,
        default=0,
        help="Zakończ po tylu sekundach bez nowych stemów (0 = działaj w nieskończoność)",
    )
    p_watch.add_argument(
        "--no-delete-mac",
        action="store_true",
        help="Kopiuj na Patriot, zostaw pliki na Macu",
    )

    args = parser.parse_args()
    mac = args.mac or default_engine_desktop_library()
    patriot = args.patriot

    try:
        if args.cmd == "status":
            out = stems_migration_status(mac, patriot)
            if out.get("ok"):
                free = out.get("mac_free_gb")
                out["suggested_batch_size"] = compute_auto_batch_size(free)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out.get("ok", True) else 1

        if args.cmd == "prepare":
            status = stems_migration_status(mac, patriot)
            bs = args.batch or compute_auto_batch_size(status.get("mac_free_gb"))
            out = prepare_stems_batch_playlist(mac, patriot, batch_size=max(1, bs))
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out.get("ok", True) else 1

        if args.cmd == "migrate":
            out = migrate_stems_to_patriot(
                mac,
                patriot,
                batch_size=args.batch,
                delete_mac=not args.no_delete_mac,
                dry_run=args.dry_run,
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out.get("ok", True) else 1

        if args.cmd == "render":
            out = render_stems_batch(
                mac,
                manual_ui=args.manual_render,
                timeout_sec=args.render_timeout,
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out.get("ok", True) else 1

        if args.cmd == "watch":
            out = watch_and_migrate_stems(
                mac,
                patriot,
                poll_sec=args.poll,
                delete_mac=not args.no_delete_mac,
                stop_after_idle_sec=args.stop_after_idle,
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out.get("ok", True) else 1

        out = run_auto_stems_pipeline(
            mac,
            patriot,
            batch_size=args.batch,
            max_batches=args.max_batches,
            manual_render=args.manual_render,
            delete_mac=not args.no_delete_mac,
            dry_run=args.dry_run,
            render_timeout_sec=args.render_timeout,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok", True) else 1
    except RuntimeError as ex:
        print(json.dumps({"ok": False, "error": str(ex)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
