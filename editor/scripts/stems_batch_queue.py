#!/usr/bin/env python3
"""
Partie stemów 1–10 min → playlista Engine „NJR / NJR Stems Batch”.

  python3 scripts/stems_batch_queue.py status
  python3 scripts/stems_batch_queue.py prepare --batch 250
  python3 scripts/stems_batch_queue.py go   # prepare + podpowiedź / otwarcie Engine

  # Automatyczna pętla partii (watcher + czekanie + kolejna partia + Create stems)
  python3 scripts/stems_batch_queue.py loop --batch 250

Z watcherem w drugim terminalu (opcjonalnie — loop sam uruchomi watchera):
  python3 scripts/auto_stems_to_patriot.py watch
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine_libdjinterop import default_engine_desktop_library, is_engine_desktop_running  # noqa: E402
from engine_stems import DEFAULT_PATRIOT_ENGINE  # noqa: E402
from engine_stems_queue import (  # noqa: E402
    DEFAULT_MAX_LENGTH_SEC,
    DEFAULT_MIN_LENGTH_SEC,
    list_mono_stem_candidates,
    prepare_duration_stems_batch,
    run_stems_batch_loop,
    stems_queue_status,
)
from engine_stems_render import compute_auto_batch_size, resolve_batch_size  # noqa: E402


def _ensure_watcher_running() -> None:
    r = subprocess.run(["pgrep", "-f", "auto_stems_to_patriot.py watch"], capture_output=True)
    if r.returncode != 0:
        subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/auto_stems_to_patriot.py"), "watch"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("Uruchomiono watcher w tle (auto_stems_to_patriot.py watch).", flush=True)


def _quit_engine(wait_sec: float = 30.0) -> bool:
    if not is_engine_desktop_running():
        return True
    subprocess.run(["osascript", "-e", 'tell application "Engine DJ" to quit'], check=False)
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if not is_engine_desktop_running():
            return True
        time.sleep(0.5)
    return not is_engine_desktop_running()


def _open_engine() -> None:
    subprocess.run(["open", "-a", "Engine DJ"], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Partie stemów 1–10 min (Engine DJ)")
    parser.add_argument("--mac", type=Path, default=None)
    parser.add_argument("--patriot", type=Path, default=DEFAULT_PATRIOT_ENGINE)
    parser.add_argument("--batch", type=int, default=None, help="Wielkość partii (domyślnie auto)")
    parser.add_argument("--min-sec", type=int, default=DEFAULT_MIN_LENGTH_SEC)
    parser.add_argument("--max-sec", type=int, default=DEFAULT_MAX_LENGTH_SEC)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Ile utworów w kolejce i partii")
    sub.add_parser("mono", help="Lista mono pomijanych z kolejki stemów")
    p_prepare = sub.add_parser("prepare", help="Zapisz następną partię do playlisty NJR")
    p_go = sub.add_parser("go", help="Watcher + prepare + otwórz Engine DJ")
    p_loop = sub.add_parser(
        "loop",
        help="Watcher + automatyczne partie aż skończy kolejka (Ctrl+C = stop)",
    )
    for p in (p_prepare, p_go, p_loop):
        p.add_argument(
            "--no-watcher",
            action="store_true",
            help="Nie uruchamiaj watchera w tle",
        )
    for p in (p_go, p_loop):
        p.add_argument(
            "--no-open-engine",
            action="store_true",
            help="Nie otwieraj Engine DJ automatycznie (tylko go)",
        )
    p_loop.add_argument(
        "--poll",
        type=float,
        default=45.0,
        help="Co ile sekund sprawdzać postęp partii",
    )
    p_loop.add_argument(
        "--max-batches",
        type=int,
        default=0,
        help="Limit partii (0 = bez limitu)",
    )
    p_loop.add_argument(
        "--force-batch",
        action="store_true",
        help="Ignoruj limit dysku (ryzykowne przy małym wolnym miejscu)",
    )
    p_loop.add_argument(
        "--manual-create-stems",
        action="store_true",
        help="Nie klika Create stems — tylko przygotuj playlistę i czekaj",
    )

    args = parser.parse_args()
    mac = args.mac or default_engine_desktop_library()
    patriot = args.patriot
    force_batch = getattr(args, "force_batch", False)

    def _batch_size(st: dict) -> int:
        return resolve_batch_size(
            args.batch,
            st.get("mac_free_gb"),
            force=force_batch,
        )

    try:
        if args.cmd == "status":
            from engine_stems import stems_migration_status

            st = stems_migration_status(mac, patriot)
            bs = _batch_size(st)
            out = stems_queue_status(
                mac, patriot, batch_size=bs, min_length_sec=args.min_sec, max_length_sec=args.max_sec
            )
            out["mac_free_gb"] = st.get("mac_free_gb")
            out["suggested_batch_size"] = bs
            out["requested_batch_size"] = args.batch
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "mono":
            out = {
                "ok": True,
                "mono_count": len(
                    list_mono_stem_candidates(
                        mac,
                        patriot,
                        min_length_sec=args.min_sec,
                        max_length_sec=args.max_sec,
                    )
                ),
                "tracks": list_mono_stem_candidates(
                    mac,
                    patriot,
                    min_length_sec=args.min_sec,
                    max_length_sec=args.max_sec,
                ),
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "loop":
            if not args.no_watcher:
                _ensure_watcher_running()
            from engine_stems import stems_migration_status

            st = stems_migration_status(mac, patriot)
            bs = _batch_size(st)
            if args.batch and bs < args.batch and not force_batch:
                print(
                    f"Partia ograniczona {args.batch} → {bs} "
                    f"(wolne {st.get('mac_free_gb')} GB na Macu).",
                    flush=True,
                )
            out = run_stems_batch_loop(
                mac,
                patriot,
                batch_size=bs,
                min_length_sec=args.min_sec,
                max_length_sec=args.max_sec,
                poll_sec=args.poll,
                max_batches=args.max_batches,
                auto_create_stems=not args.manual_create_stems,
                force_batch=force_batch,
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0

        if not getattr(args, "no_watcher", False) and args.cmd == "go":
            _ensure_watcher_running()

        if is_engine_desktop_running():
            print("Zamykam Engine DJ na chwilę (zapis playlisty)…", flush=True)
            if not _quit_engine():
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "Nie udało się zamknąć Engine DJ — zamknij ręcznie (Cmd+Q) i powtórz.",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1

        from engine_stems import stems_migration_status

        st = stems_migration_status(mac, patriot)
        bs = _batch_size(st)
        if args.batch and bs < args.batch and not force_batch:
            print(
                f"Partia ograniczona {args.batch} → {bs} "
                f"(wolne {st.get('mac_free_gb')} GB na Macu).",
                flush=True,
            )

        out = prepare_duration_stems_batch(
            mac,
            patriot,
            batch_size=bs,
            min_length_sec=args.min_sec,
            max_length_sec=args.max_sec,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))

        if out.get("ok") and out.get("track_count", 0) > 0 and args.cmd == "go":
            if not getattr(args, "no_open_engine", False):
                time.sleep(1)
                _open_engine()
            print(
                "\n→ Engine DJ: „NJR / NJR Stems Batch” → Cmd+A → Create stems\n",
                flush=True,
            )
        return 0 if out.get("ok", True) else 1

    except RuntimeError as ex:
        print(json.dumps({"ok": False, "error": str(ex)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
