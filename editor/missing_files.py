"""Brakujące pliki: streaming nie wchodzi, dysk niepodpięty widać po ścieżce, resztę da się dopasować po nazwie."""
from __future__ import annotations

import os
from pathlib import Path

_SKIP_DIRS = {
    ".git", "node_modules", "Library", ".Trash", "Trash", "Caches",
    "Application Support", "Containers", ".npm", ".cache",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "$Recycle.Bin", "System Volume Information", "Recovery", "AppData",
}


def is_streaming_path(path: str) -> bool:
    from file_analyzer import is_streaming

    text = (path or "").strip()
    if not text:
        return False
    if is_streaming(text):
        return True
    lower = text.lower()
    return lower.startswith((
        "spotify:", "soundcloud:", "beatport:", "youtube:",
        "tidal:", "deezer:", "file://localhosttidal:",
    ))


def volume_name(path: str) -> str:
    """Nazwa dysku: /Volumes/Nazwa albo litera Windows, np. E:."""
    raw = (path or "").strip()
    win = raw.replace("/", "\\")
    if len(win) >= 2 and win[1] == ":" and win[0].isalpha():
        return win[0].upper() + ":"
    parts = Path(raw.replace("\\", "/")).parts
    if len(parts) >= 3 and parts[1] == "Volumes":
        return parts[2]
    return ""


def volume_unmounted(path: str) -> str:
    """Nazwa dysku, gdy wolumin nie jest podpięty. Pusto, gdy plik jest na tym komputerze."""
    name = volume_name(path)
    if not name:
        return ""
    if len(name) == 2 and name[1] == ":":
        root = Path(name + "\\")
        try:
            if root.exists():
                return ""
        except OSError:
            return name
        return name
    root = Path("/Volumes") / name
    try:
        if root.is_dir():
            return ""
    except OSError:
        return name
    return name


def in_trash(path: str) -> bool:
    text = (path or "").replace("\\", "/")
    lower = text.lower()
    return (
        "/.trash/" in lower
        or "/trash/" in lower
        or "$recycle.bin" in lower
    )


def search_roots(extra: list[str] | None = None) -> list[Path]:
    """Foldery, które wolno czytać bez skanowania całego dysku systemowego."""
    found: list[Path] = []
    seen = set()

    def add(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        if not resolved.is_dir():
            return
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        found.append(resolved)

    home = Path.home()
    add(home / "Desktop" / "muzyka dj")
    add(home / "Music")
    add(home / "Documents")
    for raw in extra or []:
        if raw and str(raw).strip():
            add(Path(str(raw).strip()))
    if os.name == "nt":
        from platform_paths import windows_drives
        system = (os.environ.get("SystemDrive") or "C:").upper()
        for drive in windows_drives():
            if drive["path"][:2].upper() == system:
                continue
            add(Path(drive["path"]))
        return found
    volumes = Path("/Volumes")
    if volumes.is_dir():
        for child in volumes.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            try:
                if os.path.samefile(child, "/"):
                    continue
            except OSError:
                continue
            add(child)
    return found


def index_audio(roots: list[Path], extensions: set[str], limit: int = 200000) -> dict[str, list[str]]:
    """Nazwa pliku bez rozszerzenia → pełne ścieżki. Pomija kosz i ukryte katalogi."""
    index: dict[str, list[str]] = {}
    count = 0
    for root in roots:
        if count >= limit:
            break
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name for name in dirnames
                if name not in _SKIP_DIRS and not name.startswith(".")
            ]
            for name in filenames:
                if count >= limit:
                    break
                path = Path(dirpath) / name
                try:
                    resolved = path.resolve(strict=True)
                except OSError:
                    continue
                if not resolved.is_file():
                    continue
                if resolved.suffix.lower() not in extensions or resolved.suffix.lower() == ".vdjcache":
                    continue
                stem = resolved.stem.lower()
                if not stem:
                    continue
                full = str(resolved)
                bucket = index.setdefault(stem, [])
                if full not in bucket:
                    bucket.append(full)
                    count += 1
    return index


def pick_new_path(old_path: str, matches: list[str]) -> str:
    if not matches:
        return ""
    old_suffix = Path(old_path).suffix.lower()
    same = [path for path in matches if Path(path).suffix.lower() == old_suffix]
    pool = same or matches
    old_norm = (old_path or "").replace("\\", "/")
    for path in pool:
        if path.replace("\\", "/") != old_norm:
            return path
    return ""
