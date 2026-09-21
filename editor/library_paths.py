"""
Ścieżki bibliotek DJ — macOS vs Windows 11.

Patriot na Windows to litera dysku (np. E:\\Engine Library), nie /Volumes/Patriot.
Nadpisanie: zmienna środowiskowa NJR_PATRIOT_ENGINE (pełna ścieżka Engine Library).
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

from engine_libdjinterop import default_engine_desktop_library

MACOS_PATRIOT_ENGINE = Path("/Volumes/Patriot/Engine Library")
WINDOWS_PATRIOT_FALLBACK = Path("E:/Engine Library")
PATRIOT_VOLUME_MARKERS = ("patriot",)


def close_engine_hint() -> str:
    if platform.system() == "Windows":
        return (
            "Zamknij Engine DJ całkowicie (ikona w zasobniku albo Menedżer zadań "
            "— nie wystarczy zamknąć okna)"
        )
    return "Zamknij Engine DJ (Cmd+Q)"


def close_all_dj_hint() -> str:
    if platform.system() == "Windows":
        return (
            "Zamknij VirtualDJ, Serato DJ i Engine DJ (Menedżer zadań — pełne wyjście)"
        )
    return "Zamknij VirtualDJ, Serato DJ i Engine DJ (Cmd+Q)"


def desktop_library_label() -> str:
    if platform.system() == "Windows":
        return "PC (Engine DJ Desktop)"
    if platform.system() == "Darwin":
        return "Mac (Engine DJ Desktop)"
    return "Engine DJ Desktop"


def is_engine_library_dir(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        return (Path(path) / "Database2" / "m.db").is_file()
    except OSError:
        return False


def _safe_resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser()


def default_vdj_base() -> Path:
    """Folder VirtualDJ (database.xml, Folders)."""
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library" / "Application Support" / "VirtualDJ"
    if platform.system() == "Windows":
        docs = home / "Documents" / "VirtualDJ"
        local = Path(
            os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")
        ) / "VirtualDJ"
        if (docs / "database.xml").is_file():
            return docs
        if (local / "database.xml").is_file():
            return local
        if docs.is_dir():
            return docs
        if local.is_dir():
            return local
        return docs
    return home / ".virtualdj"


def default_vdj_database() -> Path:
    return default_vdj_base() / "database.xml"


def default_vdj_folders() -> Path:
    return default_vdj_base() / "Folders"


def default_serato_dir() -> Path:
    return Path.home() / "Music" / "_Serato_"


def default_serato_sqlite_dir() -> Path:
    """Serato 4+ Library (root.sqlite) — macOS vs Windows."""
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library" / "Application Support" / "Serato" / "Library"
    if platform.system() == "Windows":
        roaming = (
            Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
            / "Serato"
            / "Library"
        )
        local = (
            Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
            / "Serato"
            / "Library"
        )
        if (roaming / "root.sqlite").is_file():
            return roaming
        if (local / "root.sqlite").is_file():
            return local
        return roaming
    return home / ".serato" / "Library"


_GDRIVE_DIR_NAMES = ("My Drive", "Mój dysk", "Google Drive", "GoogleDrive")
_GDRIVE_LABEL_MARKERS = ("google drive", "googledrive", "my drive", "mój dysk")


def _looks_like_google_drive(name: str) -> bool:
    lowered = (name or "").strip().lower()
    return any(marker in lowered for marker in _GDRIVE_LABEL_MARKERS)


def google_drive_roots() -> list[Path]:
    """
    Foldery Dysku Google (pobrane / lustrzane pliki), bez kopiowania na Desktop.
    Nadpisanie: NJR_GOOGLE_DRIVE (jeden katalog albo lista oddzielona ``;``).
    """
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            if not path.is_dir():
                return
        except OSError:
            return
        resolved = _safe_resolve(path)
        key = str(resolved).replace("\\", "/").lower()
        if key in seen:
            return
        seen.add(key)
        found.append(resolved)

    env = os.environ.get("NJR_GOOGLE_DRIVE", "").strip()
    if env:
        parts = [p.strip() for p in env.split(";") if p.strip()] or [env]
        for raw in parts:
            add(Path(raw).expanduser())

    home = Path.home()
    for name in _GDRIVE_DIR_NAMES:
        add(home / name)

    cloud = home / "Library" / "CloudStorage"
    if cloud.is_dir():
        try:
            entries = list(cloud.iterdir())
        except OSError:
            entries = []
        for vol in entries:
            if not _looks_like_google_drive(vol.name):
                continue
            add(vol)
            for child in _GDRIVE_DIR_NAMES:
                add(vol / child)

    if platform.system() == "Windows":
        for letter, label in _windows_volumes():
            root = Path(f"{letter}:/")
            if _looks_like_google_drive(label) or _looks_like_google_drive(letter):
                add(root)
            for child in _GDRIVE_DIR_NAMES:
                add(root / child)

    if platform.system() == "Darwin":
        volumes = Path("/Volumes")
        if volumes.is_dir():
            try:
                entries = list(volumes.iterdir())
            except OSError:
                entries = []
            for vol in entries:
                if _looks_like_google_drive(vol.name):
                    add(vol)
                    for child in _GDRIVE_DIR_NAMES:
                        add(vol / child)

    # Preferuj „My Drive” / „Mój dysk” nad korzeniem litery dysku
    found.sort(
        key=lambda p: (
            0 if _looks_like_google_drive(p.name) else 1,
            len(str(p)),
        )
    )
    return found


def default_google_drive_root() -> Path | None:
    roots = google_drive_roots()
    return roots[0] if roots else None


def _volume_looks_like_patriot(name: str) -> bool:
    lowered = (name or "").strip().lower()
    return any(marker in lowered for marker in PATRIOT_VOLUME_MARKERS)


def _windows_volumes() -> list[tuple[str, str]]:
    """Lista (litera, etykieta woluminu), np. ('E', 'Patriot')."""
    try:
        import ctypes
    except ImportError:
        return []

    kernel32 = ctypes.windll.kernel32
    bitmask = int(kernel32.GetLogicalDrives() or 0)
    out: list[tuple[str, str]] = []
    buf = ctypes.create_unicode_buffer(261)
    for i in range(26):
        if not (bitmask & (1 << i)):
            continue
        letter = chr(ord("A") + i)
        root = f"{letter}:\\"
        buf.value = ""
        try:
            kernel32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
        except OSError:
            pass
        out.append((letter, buf.value or ""))
    return out


def _macos_volume_candidates() -> list[tuple[Path, str]]:
    volumes = Path("/Volumes")
    if not volumes.is_dir():
        return []
    found: list[tuple[Path, str]] = []
    try:
        entries = list(volumes.iterdir())
    except OSError:
        return []
    for vol in entries:
        try:
            if not vol.is_dir():
                continue
        except OSError:
            continue
        found.append((vol / "Engine Library", vol.name))
    return found


def _linux_volume_candidates() -> list[tuple[Path, str]]:
    roots = [Path("/Volumes"), Path("/media"), Path("/mnt"), Path("/run/media")]
    found: list[tuple[Path, str]] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for vol in entries:
            try:
                if vol.is_dir():
                    found.append((vol / "Engine Library", vol.name))
                    # /media/user/Patriot/Engine Library
                    try:
                        nested = list(vol.iterdir())
                    except OSError:
                        nested = []
                    for child in nested:
                        if child.is_dir():
                            found.append((child / "Engine Library", child.name))
            except OSError:
                continue
    return found


def _windows_volume_candidates() -> list[tuple[Path, str]]:
    return [
        (Path(f"{letter}:/Engine Library"), label or letter)
        for letter, label in _windows_volumes()
    ]


def list_patriot_engine_candidates(*, require_database: bool = True) -> list[Path]:
    """
    Kandydaci na bibliotekę Rane/Patriot (bez biblioteki Desktop).
    Preferuje wolumin o nazwie Patriot.
    """
    desktop = _safe_resolve(default_engine_desktop_library())
    system = platform.system()
    if system == "Darwin":
        pairs = _macos_volume_candidates()
    elif system == "Windows":
        pairs = _windows_volume_candidates()
    else:
        pairs = _linux_volume_candidates()

    labeled: list[Path] = []
    others: list[Path] = []
    seen: set[str] = set()
    for candidate, volume_name in pairs:
        resolved = _safe_resolve(candidate)
        key = str(resolved).replace("\\", "/").lower()
        if key in seen:
            continue
        if resolved == desktop:
            continue
        if require_database and not is_engine_library_dir(candidate):
            continue
        seen.add(key)
        if _volume_looks_like_patriot(volume_name) or _volume_looks_like_patriot(
            candidate.as_posix()
        ):
            labeled.append(resolved)
        else:
            others.append(resolved)
    return labeled + others


def detect_patriot_engine_library() -> Path | None:
    """
    Wykryta biblioteka Engine na dysku Rane/Patriot albo None.
    Env NJR_PATRIOT_ENGINE ma pierwszeństwo (nawet gdy dysk jeszcze nie podłączony).
    """
    env = os.environ.get("NJR_PATRIOT_ENGINE", "").strip()
    if env:
        return _safe_resolve(Path(env))
    found = list_patriot_engine_candidates(require_database=True)
    if found:
        return found[0]
    labeled_empty = list_patriot_engine_candidates(require_database=False)
    for path in labeled_empty:
        if _volume_looks_like_patriot(path.as_posix()) or _volume_looks_like_patriot(
            path.parent.name
        ):
            return path
    return None


def default_patriot_engine() -> Path:
    """
    Domyślna ścieżka Patriota do API/CLI.
    Na Windows nigdy nie zwraca /Volumes/Patriot — to ślepa ścieżka Mac.
    """
    detected = detect_patriot_engine_library()
    if detected is not None:
        return detected
    if platform.system() == "Windows":
        return WINDOWS_PATRIOT_FALLBACK
    return MACOS_PATRIOT_ENGINE


def resolve_patriot_engine(patriot_engine: Path | str | None = None) -> Path:
    if patriot_engine:
        return _safe_resolve(Path(patriot_engine))
    return _safe_resolve(default_patriot_engine())


def runtime_library_paths() -> dict:
    """Snapshot ścieżek dla UI / GET /api/library-paths."""
    desktop = default_engine_desktop_library()
    patriot = default_patriot_engine()
    vdj_base = default_vdj_base()
    serato = default_serato_dir()
    gdrive_roots = [str(p) for p in google_drive_roots()]
    candidates = [str(p) for p in list_patriot_engine_candidates(require_database=True)]
    env_patriot = os.environ.get("NJR_PATRIOT_ENGINE", "").strip()
    return {
        "platform": platform.system(),
        "desktop_label": desktop_library_label(),
        "engine_desktop": str(desktop),
        "engine_desktop_exists": is_engine_library_dir(desktop),
        "patriot_engine": str(patriot),
        "patriot_mounted": is_engine_library_dir(patriot),
        "patriot_candidates": candidates,
        "patriot_from_env": bool(env_patriot),
        "vdj_base": str(vdj_base),
        "vdj_database": str(vdj_base / "database.xml"),
        "vdj_database_exists": (vdj_base / "database.xml").is_file(),
        "serato_dir": str(serato),
        "serato_exists": serato.is_dir(),
        "serato_sqlite_dir": str(default_serato_sqlite_dir()),
        "google_drive_roots": gdrive_roots,
        "google_drive": gdrive_roots[0] if gdrive_roots else "",
        "close_engine_hint": close_engine_hint(),
        "close_all_dj_hint": close_all_dj_hint(),
        "stems_notes": (
            "Stemy rób w Engine DJ Desktop (Create stems), potem migracja NJR na Patriot. "
            "Nie używaj Export Stems ani Export to Drive w Sync Manager."
        ),
    }
