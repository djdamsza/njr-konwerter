"""
Wykrywanie uruchomionych aplikacji DJ (Lexicon/MIXO style) przed sync/ zapisem.
Zwraca (bool, komunikat) — True = aplikacja działa / baza prawdopodobnie zablokowana.
"""
from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path
from typing import Optional

SERATO_LIBRARY_DIR = Path.home() / "Library/Application Support/Serato/Library"
SERATO_DB_V2_NAMES = ("database V2", "DatabaseV2")


def _pgrep_running(pattern: str) -> bool:
    if platform.system() == "Darwin":
        try:
            r = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                timeout=5,
            )
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    if platform.system() == "Windows":
        try:
            r = subprocess.run(
                ["tasklist", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            needle = pattern.lower()
            return needle in (r.stdout or "").lower()
        except (OSError, subprocess.TimeoutExpired):
            return False
    return False


def is_vdj_running() -> tuple[bool, str]:
    """True gdy VirtualDJ jest uruchomiony."""
    if _pgrep_running("VirtualDJ"):
        return True, "VirtualDJ jest uruchomiony — zamknij przed synchronizacją."
    return False, ""


def is_serato_running() -> tuple[bool, str]:
    """True gdy Serato DJ Pro/Lite działa."""
    for pattern in ("Serato DJ Pro", "Serato DJ Lite", "Serato DJ"):
        if _pgrep_running(pattern):
            return True, f"{pattern} jest uruchomiony — zamknij przed synchronizacją."
    return False, ""


def is_engine_running() -> tuple[bool, str]:
    """True gdy Engine DJ Desktop działa."""
    from engine_libdjinterop import is_engine_desktop_running

    if is_engine_desktop_running():
        return True, "Engine DJ Desktop jest uruchomiony — zamknij (Cmd+Q) przed synchronizacją."
    return False, ""


def _resolve_serato_db_v2(serato_dir: Optional[Path] = None) -> Optional[Path]:
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    for name in SERATO_DB_V2_NAMES:
        p = base / name
        if p.is_file():
            return p
    nested = base / "_Serato_"
    for name in SERATO_DB_V2_NAMES:
        p = nested / name
        if p.is_file():
            return p
    return None


def serato_db_likely_locked(serato_dir: Optional[Path] = None) -> tuple[bool, str]:
    """
    Heurystyka WAL/SHM: świeżo zmodyfikowany -wal/-shm przy database V2
    sugeruje otwarty Serato (plik bazy może być zablokowany).
    """
    db = _resolve_serato_db_v2(serato_dir)
    if not db or not db.is_file():
        return False, ""

    now = time.time()
    stale_sec = 120.0
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db) + suffix)
        if not sidecar.is_file():
            continue
        try:
            age = now - sidecar.stat().st_mtime
        except OSError:
            continue
        if age < stale_sec:
            return (
                True,
                "Serato database V2 ma aktywny plik WAL/SHM — "
                "zamknij Serato DJ przed synchronizacją.",
            )
    return False, ""


def sync_guard_blockers(
    *,
    require_vdj_closed: bool = False,
    require_serato_closed: bool = False,
    require_engine_closed: bool = True,
    check_serato_db_lock: bool = False,
    serato_dir: Optional[Path] = None,
) -> tuple[bool, str, list[str]]:
    """
    Zwraca (blocked, message, checklist).
    blocked=True → nie wykonuj sync (409).
    """
    issues: list[tuple[str, str]] = []
    checklist: list[str] = []

    if require_vdj_closed:
        running, msg = is_vdj_running()
        if running:
            issues.append(("VirtualDJ", msg))
            checklist.append("Zamknij VirtualDJ")

    if require_serato_closed:
        running, msg = is_serato_running()
        if running:
            issues.append(("Serato DJ", msg))
            checklist.append("Zamknij Serato DJ")

    if check_serato_db_lock:
        locked, msg = serato_db_likely_locked(serato_dir)
        if locked:
            issues.append(("Serato database V2", msg))
            if "Zamknij Serato DJ" not in checklist:
                checklist.append("Zamknij Serato DJ")

    if require_engine_closed:
        running, msg = is_engine_running()
        if running:
            issues.append(("Engine DJ", msg))
            checklist.append("Zamknij Engine DJ (Cmd+Q)")

    if not issues:
        return False, "", checklist

    lines = [msg for _, msg in issues if msg]
    message = " ".join(lines)
    if checklist:
        message += " Checklist: " + "; ".join(checklist) + "."
    return True, message.strip(), checklist
