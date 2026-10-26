"""Foldery programów i własne dane konwertera.

Na Macu zostają ścieżki w Library. Na Windowsie są to Documents, AppData i Music,
tak samo jak w wykrywaniu bibliotek.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path


def is_windows() -> bool:
    return platform.system() == "Windows"


def app_support_dir() -> Path:
    """Konto, identyfikator instalacji, dziennik, aktualizacje i kopie."""
    if is_windows():
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "NJR Konwerter"
    return Path.home() / "Library" / "Application Support" / "NJR Konwerter"


def serato_sqlite_dir() -> Path:
    """master.sqlite, root.sqlite i tidal.sqlite."""
    if is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Serato" / "Library"
    return Path.home() / "Library" / "Application Support" / "Serato" / "Library"


def vdj_root() -> Path:
    """Folder VirtualDJ z database.xml, Folders i Cache."""
    if is_windows():
        return Path.home() / "Documents" / "VirtualDJ"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "VirtualDJ"
    return Path.home() / ".virtualdj"


def engine_prime_dir() -> Path:
    if is_windows():
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "AIR Music Technology" / "EnginePrime"
    return Path.home() / "Library" / "Application Support" / "AIR Music Technology" / "EnginePrime"


def windows_drives() -> list[dict]:
    """Podłączone dyski Windows: etykieta i litera, np. Patriot (E:). Na Macu pusto."""
    if not is_windows():
        return []
    import ctypes
    import string

    kernel = ctypes.windll.kernel32
    found = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if not Path(root).exists():
            continue
        name = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint32()
        maxlen = ctypes.c_uint32()
        flags = ctypes.c_uint32()
        fsname = ctypes.create_unicode_buffer(261)
        ok = kernel.GetVolumeInformationW(
            root,
            name,
            261,
            ctypes.byref(serial),
            ctypes.byref(maxlen),
            ctypes.byref(flags),
            fsname,
            261,
        )
        label = name.value.strip() if ok else ""
        title = f"{label} ({letter}:)" if label else f"Dysk {letter}:"
        found.append({"name": title, "path": root})
    return found


def windows_volume_root(label: str) -> Path | None:
    """Litera dysku o podanej etykiecie, np. Patriot → E:\\. Na Macu zawsze pusto."""
    if not is_windows():
        return None
    import ctypes

    want = (label or "").strip().casefold()
    if not want:
        return None
    kernel = ctypes.windll.kernel32
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        name = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint32()
        maxlen = ctypes.c_uint32()
        flags = ctypes.c_uint32()
        fsname = ctypes.create_unicode_buffer(261)
        ok = kernel.GetVolumeInformationW(
            root,
            name,
            261,
            ctypes.byref(serial),
            ctypes.byref(maxlen),
            ctypes.byref(flags),
            fsname,
            261,
        )
        if ok and name.value.casefold() == want:
            return Path(root)
    return None


def plain_quit(text: str) -> str:
    """Na Macu zostawia Cmd+Q i ścieżki z tyldą. Na Windowsie mówi o zwykłym zamknięciu."""
    if not is_windows():
        return text
    text = (
        text.replace(" (Cmd+Q / Quit)", "")
        .replace(" (Cmd+Q)", "")
        .replace("Cmd+Q", "zamknij program")
        .replace("~/Music/_Serato_/", "Music\\_Serato_\\")
        .replace("~/Music/_Serato_", "Music\\_Serato_")
    )
    return text.replace(
        "find Music\\_Serato_\\SmartCrates -name 'VDJ*.scrate' -delete",
        "Usuń pliki VDJ*.scrate z Music\\_Serato_\\SmartCrates",
    )


def ensure_windows_shortcuts() -> None:
    """Skrót w menu Start i na pulpicie. Tylko złożony program, raz przy starcie."""
    import subprocess
    import sys

    if not is_windows() or not getattr(sys, "frozen", False):
        return
    exe = Path(sys.executable).resolve()
    if not exe.is_file():
        return
    name = "Imprezja Playlist Pro"
    exe_ps = str(exe).replace("'", "''")
    script = (
        "$shell = New-Object -ComObject WScript.Shell\n"
        f"$name = '{name}'\n"
        f"$exe = '{exe_ps}'\n"
        "$dirs = @(\n"
        "  (Join-Path $env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs'),\n"
        "  [Environment]::GetFolderPath('Desktop')\n"
        ")\n"
        "foreach ($dir in $dirs) {\n"
        "  if (-not $dir -or -not (Test-Path -LiteralPath $dir)) { continue }\n"
        "  $lnk = Join-Path $dir ($name + '.lnk')\n"
        "  $sc = $shell.CreateShortcut($lnk)\n"
        "  $sc.TargetPath = $exe\n"
        "  $sc.WorkingDirectory = (Split-Path -LiteralPath $exe)\n"
        "  $sc.IconLocation = ($exe + ',0')\n"
        "  $sc.Description = $name\n"
        "  $sc.Save()\n"
        "}\n"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
