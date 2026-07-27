#!/usr/bin/env python3
"""
Monitor miejsca na dysku podczas pracy Engine DJ (Create stems).

Uruchamiaj równolegle z watcherem migracji stemów na Patriot:

  # Terminal 1
  python3 scripts/monitor_engine_disk.py

  # Terminal 2
  python3 scripts/auto_stems_to_patriot.py watch

Zapisuje próbkę co N sekund (JSONL) i wypisuje delty wolnego miejsca,
cache AI temp, folder Stems/, m.db oraz liczbę lokalnych snapshotów TM.

  python3 scripts/monitor_engine_disk.py --interval 15
  python3 scripts/monitor_engine_disk.py --auto-clean-gb 2   # czyść TYLKO gdy Engine zamknięty
  python3 scripts/monitor_engine_disk.py --once              # jedna próbka i wyjście
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine_disk_cleanup import (  # noqa: E402
    _disk_free_gb,
    _dir_size,
    clean_engine_hidden_cache,
    scan_engine_disk_usage,
)
from engine_libdjinterop import (  # noqa: E402
    default_engine_desktop_library,
    is_engine_desktop_running,
)
from engine_stems import DEFAULT_PATRIOT_ENGINE  # noqa: E402

DEFAULT_LOG = (
    Path.home()
    / "Documents"
    / "njr-konwerter"
    / "editor"
    / "logs"
    / "engine_disk_monitor.jsonl"
)


def _fmt_gb(n: int | float) -> float:
    return round(float(n) / (1024**3), 3)


def _tm_snapshot_dates() -> list[str]:
    if sys.platform != "darwin":
        return []
    dates: list[str] = []
    for volume in ("/System/Volumes/Data", "/"):
        proc = subprocess.run(
            ["tmutil", "listlocalsnapshotdates", volume],
            capture_output=True,
            text=True,
        )
        for line in (proc.stdout or "").splitlines():
            date = line.strip()
            if date and not date.startswith("Snapshot"):
                dates.append(date)
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for d in dates:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _engine_rss_mb() -> float | None:
    if sys.platform != "darwin":
        return None
    proc = subprocess.run(
        ["pgrep", "-x", "Engine DJ"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    pids = [p for p in (proc.stdout or "").split() if p.isdigit()]
    if not pids:
        return None
    total = 0
    for pid in pids:
        r = subprocess.run(
            ["ps", "-o", "rss=", "-p", pid],
            capture_output=True,
            text=True,
        )
        try:
            total += int((r.stdout or "0").strip() or "0")
        except ValueError:
            pass
    return round(total / 1024, 1)  # ps rss is KB


def _stems_stats(stems_dir: Path) -> tuple[int, int]:
    if not stems_dir.is_dir():
        return 0, 0
    files = list(stems_dir.glob("*.stems"))
    return len(files), sum(f.stat().st_size for f in files if f.is_file())


def _patriot_mounted(patriot: Path) -> bool:
    try:
        return patriot.exists() and patriot.is_dir()
    except OSError:
        return False


def sample(
    *,
    mac_engine: Path,
    patriot_engine: Path,
    baseline_free_gb: float | None,
) -> dict:
    scan = scan_engine_disk_usage(mac_engine)
    free = _disk_free_gb(mac_engine)
    stems_dir = mac_engine / "Stems"
    stems_n, stems_b = _stems_stats(stems_dir)
    mdb = mac_engine / "Database2" / "m.db"
    mdb_b = mdb.stat().st_size if mdb.is_file() else 0
    prime = (
        Path.home()
        / "Library/Application Support/AIR Music Technology/EnginePrime"
    )
    snaps = _tm_snapshot_dates()
    cache_gb = float(scan.get("cache_gb") or 0)
    used_vs_start = None
    if baseline_free_gb is not None and free is not None:
        used_vs_start = round(baseline_free_gb - free, 3)

    return {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "engine_running": is_engine_desktop_running(),
        "engine_rss_mb": _engine_rss_mb(),
        "mac_free_gb": free,
        "free_delta_from_start_gb": used_vs_start,
        "cache_gb": cache_gb,
        "cache_items": len(scan.get("cache_items") or []),
        "mac_stems_count": stems_n,
        "mac_stems_gb": _fmt_gb(stems_b),
        "m_db_gb": _fmt_gb(mdb_b),
        "engine_prime_gb": _fmt_gb(_dir_size(prime)),
        "tm_local_snapshots": snaps,
        "tm_snapshot_count": len(snaps),
        "patriot_mounted": _patriot_mounted(patriot_engine),
        "temp_dir": os.environ.get("TMPDIR") or None,
        "explained_engine_gb": round(
            cache_gb + _fmt_gb(stems_b) + _fmt_gb(mdb_b), 3
        ),
    }


def _line(s: dict, *, alert: str | None = None) -> str:
    eng = "ON " if s["engine_running"] else "off"
    rss = f" rss={s['engine_rss_mb']}MB" if s.get("engine_rss_mb") is not None else ""
    delta = s.get("free_delta_from_start_gb")
    delta_s = f" Δstart={delta:+.2f}G" if delta is not None else ""
    pats = "Patriot=OK" if s["patriot_mounted"] else "Patriot=BRAK"
    base = (
        f"{s['ts']}  Engine={eng}{rss}  free={s['mac_free_gb']}G{delta_s}  "
        f"cache={s['cache_gb']}G  stems={s['mac_stems_count']}({s['mac_stems_gb']}G)  "
        f"m.db={s['m_db_gb']}G  TM_snap={s['tm_snapshot_count']}  {pats}"
    )
    if alert:
        return f"{base}  !! {alert}"
    return base


def _maybe_alert(s: dict, prev: dict | None, *, warn_free_gb: float) -> str | None:
    alerts: list[str] = []
    free = s.get("mac_free_gb")
    if free is not None and free < warn_free_gb:
        alerts.append(f"mało wolnego (<{warn_free_gb}G)")
    if (s.get("cache_gb") or 0) >= 0.5:
        alerts.append(f"rośnie cache AI={s['cache_gb']}G")
    if prev:
        pf, cf = prev.get("mac_free_gb"), free
        if pf is not None and cf is not None and (pf - cf) >= 0.4:
            alerts.append(f"spadek free −{pf - cf:.2f}G od ostatniej próbki")
        pc, cc = prev.get("cache_gb") or 0, s.get("cache_gb") or 0
        if cc - pc >= 0.3:
            alerts.append(f"cache +{cc - pc:.2f}G")
        pt, ct = prev.get("tm_snapshot_count") or 0, s.get("tm_snapshot_count") or 0
        if ct > pt:
            alerts.append(f"nowy snapshot TM ({ct})")
    return "; ".join(alerts) if alerts else None


def run_monitor(
    *,
    mac_engine: Path,
    patriot_engine: Path,
    interval: float,
    log_path: Path,
    warn_free_gb: float,
    auto_clean_gb: float | None,
    once: bool,
) -> int:
    mac_engine = mac_engine.resolve()
    patriot_engine = patriot_engine.resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"Monitor Engine DJ → log: {log_path}\n"
        f"Mac library: {mac_engine}\n"
        f"Interval: {interval}s  warn_free<{warn_free_gb}G  "
        f"auto_clean_gb={auto_clean_gb}\n"
        f"Ctrl+C = stop. Równolegle: auto_stems_to_patriot.py watch\n",
        flush=True,
    )

    baseline: float | None = None
    prev: dict | None = None
    samples = 0

    try:
        while True:
            s = sample(
                mac_engine=mac_engine,
                patriot_engine=patriot_engine,
                baseline_free_gb=baseline,
            )
            if baseline is None and s.get("mac_free_gb") is not None:
                baseline = float(s["mac_free_gb"])
                s["free_delta_from_start_gb"] = 0.0

            cleaned = None
            # NIGDY nie czyść cache AI gdy Engine DJ działa — kasowanie *.mlmodelc
            # w trakcie Create stems kończy się "Stems Processor Error: initialisation
            # error" / "Aborted" (log Engine 2026-07-15 20:10).
            if (
                auto_clean_gb is not None
                and (s.get("cache_gb") or 0) >= auto_clean_gb
            ):
                if s.get("engine_running"):
                    s["auto_clean"] = {
                        "triggered": False,
                        "skipped": "engine_running",
                        "cache_gb": s.get("cache_gb"),
                    }
                else:
                    cleaned = clean_engine_hidden_cache(
                        mac_engine,
                        quit_engine=False,
                        clear_mac_stems=False,
                        remove_library_backup=True,
                        vacuum_mdb=False,
                        empty_trash=False,
                    )
                    s["auto_clean"] = {
                        "triggered": True,
                        "removed_gb": cleaned.get("removed_gb"),
                        "ok": cleaned.get("ok"),
                        "actions": len(cleaned.get("actions") or []),
                    }
                    s2 = sample(
                        mac_engine=mac_engine,
                        patriot_engine=patriot_engine,
                        baseline_free_gb=baseline,
                    )
                    s["mac_free_gb_after_clean"] = s2.get("mac_free_gb")
                    s["cache_gb_after_clean"] = s2.get("cache_gb")

            alert = _maybe_alert(s, prev, warn_free_gb=warn_free_gb)
            if s.get("auto_clean", {}).get("skipped") == "engine_running":
                alert = (
                    (alert + "; " if alert else "")
                    + f"cache={s.get('cache_gb')}G — clean PO zamknięciu Engine (nie teraz)"
                )
            if cleaned and cleaned.get("ok"):
                alert = (alert + "; " if alert else "") + "auto-clean cache OK"

            print(_line(s, alert=alert), flush=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")

            prev = s
            samples += 1
            if once:
                break
            time.sleep(max(2.0, interval))
    except KeyboardInterrupt:
        print("\nMonitor zatrzymany.", flush=True)

    # short summary at end
    if log_path.is_file():
        rows = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        # only this session: last `samples` lines
        session = rows[-samples:] if samples else rows
        if session:
            frees = [
                r["mac_free_gb"]
                for r in session
                if r.get("mac_free_gb") is not None
            ]
            caches = [r.get("cache_gb") or 0 for r in session]
            print(
                "\n=== Podsumowanie sesji ===\n"
                f"próbek: {len(session)}\n"
                f"free min/max: {min(frees):.2f} / {max(frees):.2f} G\n"
                f"cache max: {max(caches):.3f} G\n"
                f"największy spadek vs start: "
                f"{max((r.get('free_delta_from_start_gb') or 0) for r in session):.2f} G\n"
                f"log: {log_path}",
                flush=True,
            )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Monitor dysku Engine DJ (cache / stems / free / TM snapshots)"
    )
    parser.add_argument("--mac", type=Path, default=None)
    parser.add_argument("--patriot", type=Path, default=DEFAULT_PATRIOT_ENGINE)
    parser.add_argument(
        "--interval",
        type=float,
        default=15.0,
        help="Co ile sekund próbkować (domyślnie 15)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG,
        help=f"Plik JSONL (domyślnie {DEFAULT_LOG})",
    )
    parser.add_argument(
        "--warn-free-gb",
        type=float,
        default=8.0,
        help="Alert gdy wolne < N GB (domyślnie 8)",
    )
    parser.add_argument(
        "--auto-clean-gb",
        type=float,
        default=None,
        help="Gdy cache AI ≥ N GB, wyczyść temp (bez zamykania Engine)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Jedna próbka i wyjście",
    )
    args = parser.parse_args()
    mac = args.mac or default_engine_desktop_library()
    return run_monitor(
        mac_engine=mac,
        patriot_engine=args.patriot,
        interval=args.interval,
        log_path=args.log,
        warn_free_gb=args.warn_free_gb,
        auto_clean_gb=args.auto_clean_gb,
        once=args.once,
    )


if __name__ == "__main__":
    raise SystemExit(main())
