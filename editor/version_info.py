"""Wersja aplikacji — czytana z pliku VERSION w korzeniu repozytorium."""
from __future__ import annotations

from pathlib import Path


def read_app_version(default: str = "1.0.0") -> str:
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "VERSION",
        here / "VERSION",
    ]
    if getattr(__import__("sys"), "frozen", False):
        meipass = getattr(__import__("sys"), "_MEIPASS", None)
        if meipass:
            candidates.insert(0, Path(meipass) / "VERSION")
    for path in candidates:
        try:
            if path.is_file():
                version = path.read_text(encoding="utf-8").strip()
                if version:
                    return version
        except OSError:
            continue
    return default
