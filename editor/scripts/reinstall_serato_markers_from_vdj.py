#!/usr/bin/env python3
"""
Przywraca hot cues + loopy z VirtualDJ database.xml do tagów Serato (Markers2/Markers_).

Użycie (Serato ZAMKNIĘTE):
  cd editor
  python3 scripts/reinstall_serato_markers_from_vdj.py
  python3 scripts/reinstall_serato_markers_from_vdj.py --dry-run
  python3 scripts/reinstall_serato_markers_from_vdj.py --only-loops
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dj_apps_guard import is_serato_running  # noqa: E402
from serato_markers import (  # noqa: E402
    _SUPPORTED_EXT,
    read_markers2_cues_from_file,
    write_serato_markers2_batch,
)
from vdj_adapter import vdj_songs_to_unified  # noqa: E402
from vdj_parser import load_database  # noqa: E402

_AUDIO_EXT = {e.lower() for e in _SUPPORTED_EXT}


def _default_vdj_db() -> Path:
    return Path.home() / "Library/Application Support/VirtualDJ/database.xml"


def _is_writable_audio(path: str) -> bool:
    """Serato tagi tylko w prawdziwych plikach audio — nie .vdjcache / streaming."""
    p = (path or "").strip()
    if not p:
        return False
    low = p.lower()
    if low.endswith(".vdjcache") or low.endswith(".vdjsample"):
        return False
    if any(low.startswith(x) for x in ("tidal:", "spotify:", "soundcloud:", "netsearch:")):
        return False
    return Path(p).suffix.lower() in _AUDIO_EXT


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--vdj-db",
        type=Path,
        default=_default_vdj_db(),
        help="Ścieżka do VirtualDJ database.xml",
    )
    ap.add_argument(
        "--only-loops",
        action="store_true",
        help="Tylko utwory z Type=loop w VDJ (domyślnie: cue lub loop)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Tylko raport — bez zapisu do plików",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Nadpisz nawet gdy markery wyglądają na zgodne",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Równoległe zapisy (domyślnie 4)",
    )
    ap.add_argument(
        "--allow-serato-open",
        action="store_true",
        help="Nie blokuj gdy Serato działa (ryzykowne)",
    )
    args = ap.parse_args()

    if not args.vdj_db.is_file():
        print(f"Brak bazy VDJ: {args.vdj_db}")
        return 1

    if not args.allow_serato_open:
        serato_on, msg = is_serato_running()
        if serato_on:
            print(msg or "Zamknij Serato DJ (Cmd+Q), potem uruchom ponownie.")
            return 2

    print(f"Ładowanie {args.vdj_db} …")
    songs, version = load_database(args.vdj_db)
    print(f"Utworów w VDJ: {len(songs)} (version={version})")

    # Filtr: ma cue lub loop w _children_xml
    filtered = []
    for s in songs:
        kids = s.get("_children_xml") or []
        blob = " ".join(kids)
        has_cue = 'Type="cue"' in blob or "Type='cue'" in blob
        has_loop = 'Type="loop"' in blob or "Type='loop'" in blob
        if args.only_loops and not has_loop:
            continue
        if not args.only_loops and not (has_cue or has_loop):
            continue
        path = (s.get("FilePath") or "").strip()
        if not path or not Path(path).is_file():
            continue
        if not _is_writable_audio(path):
            continue
        filtered.append(s)

    print(f"Do zapisu (istniejące pliki, cue/loop): {len(filtered)}")
    db = vdj_songs_to_unified(filtered)
    tracks = [t for t in db.tracks if t.cue_points or t.loops]
    print(
        f"Po konwersji: {len(tracks)} tracków "
        f"(z cue={sum(1 for t in tracks if t.cue_points)}, "
        f"z loop={sum(1 for t in tracks if t.loops)})"
    )

    if args.dry_run:
        from serato_markers import (  # noqa: E402
            cue_points_signature,
            loops_signature,
            parsed_cues_signature,
            parsed_loops_signature,
            read_markers_underscore_loops_from_file,
        )

        shown = 0
        for t in tracks:
            want_c = cue_points_signature(t.cue_points)
            want_l = loops_signature(t.loops)
            have_c = parsed_cues_signature(read_markers2_cues_from_file(t.path) or [])
            have_l = parsed_loops_signature(
                read_markers_underscore_loops_from_file(t.path) or []
            )
            if have_c != tuple(sorted(want_c)) or have_l != want_l:
                shown += 1
                if shown <= 40:
                    print(
                        f"  NEED cues {len(have_c)}->{len(want_c)} "
                        f"loops {len(have_l)}->{len(want_l)}  "
                        f"{Path(t.path).name}"
                    )
        print(f"Dry-run: tracks={len(tracks)}, różnice (need)={shown}")
        return 0

    written, skipped, unchanged, failed, errors = write_serato_markers2_batch(
        tracks,
        skip_unchanged=not args.force,
        workers=max(1, args.workers),
        progress_cb=lambda done, total, w, u: (
            print(f"  {done}/{total} written={w} unchanged={u}", flush=True)
            if done == total or done % 50 == 0
            else None
        ),
    )
    print(
        f"Gotowe: written={written} unchanged={unchanged} "
        f"skipped={skipped} failed={failed}"
    )
    for e in errors[:20]:
        print("  ERR", e)
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
