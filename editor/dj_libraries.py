"""
Gdzie leży aktualna baza każdego programu DJ i jak zrobić z niej kopię.

Import czyta to miejsce. Eksport zapisuje z powrotem w to samo miejsce.
Przed jednym i drugim powstaje kopia, którą można przywrócić.
"""
from __future__ import annotations

import json
import platform
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional


SYSTEMS = (
    ("serato", "Serato"),
    ("vdj", "VirtualDJ"),
    ("engine", "Engine DJ"),
    ("rekordbox", "Rekordbox"),
    ("traktor", "Traktor"),
)


def _home(home: Optional[Path]) -> Path:
    return Path(home) if home is not None else Path.home()


def backup_root(home: Optional[Path] = None) -> Path:
    base = _home(home)
    if platform.system() == "Windows":
        return base / "AppData" / "Roaming" / "NJR Konwerter" / "backups"
    return base / "Library" / "Application Support" / "NJR Konwerter" / "backups"


def _existing_files(paths: list[Path]) -> list[str]:
    return [str(p) for p in paths if p.is_file()]


def locate(system: str, home: Optional[Path] = None) -> dict:
    system = (system or "").strip().lower()
    base = _home(home)
    if system == "vdj":
        return _locate_vdj(base)
    if system == "serato":
        return _locate_serato(base)
    if system == "engine":
        return _locate_engine(base)
    if system == "rekordbox":
        return _locate_rekordbox(base)
    if system == "traktor":
        return _locate_traktor(base)
    raise ValueError(f"Nieznany system: {system}")


def locate_all(home: Optional[Path] = None) -> list[dict]:
    rows = []
    root = backup_root(home)
    for key, _label in SYSTEMS:
        row = locate(key, home)
        row["hasBackup"] = _latest_backup_dir(key, root) is not None
        rows.append(row)
    return rows


def _locate_vdj(base: Path) -> dict:
    if platform.system() == "Windows":
        folder = base / "Documents" / "VirtualDJ"
    else:
        folder = base / "Library" / "Application Support" / "VirtualDJ"
    db = folder / "database.xml"
    return _row(
        "vdj",
        "VirtualDJ",
        found=db.is_file(),
        path=db if db.is_file() else folder,
        kind="vdj",
        backup_files=_existing_files([db]),
        note="" if db.is_file() else f"Brak {db}",
        importable=db.is_file(),
    )


def _locate_serato(base: Path) -> dict:
    if platform.system() == "Windows":
        library = base / "AppData" / "Local" / "Serato" / "Library"
    else:
        library = base / "Library" / "Application Support" / "Serato" / "Library"
    music = base / "Music" / "_Serato_"
    master = library / "master.sqlite"
    v2 = music / "database V2"
    files = [
        master,
        library / "root.sqlite",
        library / "tidal.sqlite",
        v2,
    ]
    if master.is_file():
        path, kind = library, "serato-sqlite"
        note = "Bieżąca biblioteka Serato (master + root + tidal)."
    elif v2.is_file():
        path, kind = music, "serato-v2"
        note = "Starsza biblioteka Serato (database V2)."
    else:
        path, kind = library, "serato-sqlite"
        note = f"Brak {master} i {v2}"
    return _row(
        "serato",
        "Serato",
        found=master.is_file() or v2.is_file(),
        path=path,
        kind=kind,
        backup_files=_existing_files(files),
        note=note,
        importable=master.is_file() or v2.is_file(),
    )


def _locate_engine(base: Path) -> dict:
    folder = base / "Music" / "Engine Library"
    mdb = folder / "Database2" / "m.db"
    return _row(
        "engine",
        "Engine DJ",
        found=mdb.is_file(),
        path=mdb if mdb.is_file() else folder,
        kind="engine",
        backup_files=_existing_files([mdb]),
        note="" if mdb.is_file() else f"Brak {mdb}. Uruchom Engine DJ raz, żeby powstała biblioteka.",
        importable=mdb.is_file(),
    )


def _locate_rekordbox(base: Path) -> dict:
    if platform.system() == "Windows":
        folder = base / "AppData" / "Roaming" / "Pioneer" / "rekordbox"
    else:
        folder = base / "Library" / "Pioneer" / "rekordbox"
    master = folder / "master.db"
    xml_files = sorted(folder.glob("*.xml"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []
    xml = xml_files[0] if xml_files else None
    note = ""
    if master.is_file() and xml is None:
        note = (
            "Rekordbox trzyma kolekcję w master.db. NJR czyta i zapisuje oficjalny XML, "
            "bez zapisu do master.db. W rekordboxie: File → Export Collection in xml format "
            f"i zapisz plik w {folder}, potem pobierz bazę ponownie."
        )
    elif xml is not None:
        note = "Wczytany zostanie najnowszy plik XML z folderu rekordbox."
    else:
        note = f"Brak folderu rekordbox: {folder}"
    return _row(
        "rekordbox",
        "Rekordbox",
        found=master.is_file() or xml is not None,
        path=xml if xml is not None else folder,
        kind="rekordbox-xml",
        backup_files=_existing_files([master] + xml_files[:3]),
        note=note,
        importable=xml is not None,
        export_dir=folder,
    )


def _locate_traktor(base: Path) -> dict:
    root = base / "Documents" / "Native Instruments"
    nml_files: list[Path] = []
    if root.is_dir():
        nml_files = sorted(root.glob("Traktor*/collection.nml"), key=lambda p: p.stat().st_mtime, reverse=True)
    nml = nml_files[0] if nml_files else None
    return _row(
        "traktor",
        "Traktor",
        found=nml is not None,
        path=nml if nml is not None else root,
        kind="traktor",
        backup_files=_existing_files([nml] if nml else []),
        note="" if nml is not None else f"Brak collection.nml w {root}",
        importable=nml is not None,
    )


def _row(
    system: str,
    label: str,
    *,
    found: bool,
    path: Path,
    kind: str,
    backup_files: list[str],
    note: str,
    importable: bool,
    export_dir: Optional[Path] = None,
) -> dict:
    return {
        "system": system,
        "label": label,
        "found": found,
        "importable": importable,
        "path": str(path),
        "kind": kind,
        "backupFiles": backup_files,
        "note": note,
        "exportDir": str(export_dir) if export_dir is not None else "",
    }


def running_message(system: str) -> str:
    """Pusty tekst, gdy program jest zamknięty."""
    from dj_apps_guard import is_serato_running, is_vdj_running
    from engine_libdjinterop import is_engine_desktop_running

    system = (system or "").strip().lower()
    if system == "vdj":
        running, msg = is_vdj_running()
        return msg if running else ""
    if system == "serato":
        running, msg = is_serato_running()
        return msg if running else ""
    if system == "engine" and is_engine_desktop_running():
        return "Engine DJ jest uruchomiony — zamknij go przed zapisem."
    if system == "rekordbox" and _process_running("rekordbox"):
        return "Rekordbox jest uruchomiony — zamknij go przed zapisem."
    if system == "traktor" and _process_running("Traktor"):
        return "Traktor jest uruchomiony — zamknij go przed zapisem."
    return ""


def _process_running(name: str) -> bool:
    import subprocess
    if platform.system() != "Darwin":
        return False
    try:
        r = subprocess.run(["pgrep", "-f", name], capture_output=True, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def create_backup(system: str, home: Optional[Path] = None) -> dict:
    info = locate(system, home)
    sources = [Path(p) for p in info["backupFiles"]]
    if not sources:
        raise ValueError(info["note"] or f"Nie znaleziono bazy {info['label']}.")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_root(home) / system / stamp
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in sources:
        target_name = f"{len(copied):02d}_{src.name}"
        shutil.copy2(src, dest / target_name)
        copied.append({"src": str(src), "file": target_name})
    manifest = {
        "system": system,
        "label": info["label"],
        "created": stamp,
        "files": copied,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "dir": str(dest),
        "stamp": stamp,
        "files": len(copied),
        "label": info["label"],
    }


def _latest_backup_dir(system: str, root: Path) -> Optional[Path]:
    folder = root / system
    if not folder.is_dir():
        return None
    dirs = [p for p in folder.iterdir() if p.is_dir() and (p / "manifest.json").is_file()]
    if not dirs:
        return None
    return sorted(dirs)[-1]


def restore_backup(system: str, home: Optional[Path] = None) -> dict:
    blocked = running_message(system)
    if blocked:
        raise ValueError(blocked)
    latest = _latest_backup_dir(system, backup_root(home))
    if latest is None:
        raise ValueError("Nie ma kopii bezpieczeństwa dla tego programu.")
    manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    restored = []
    for item in manifest.get("files") or []:
        src = latest / item["file"]
        target = Path(item["src"])
        if not src.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        restored.append(str(target))
    if not restored:
        raise ValueError("Kopia jest pusta.")
    return {
        "ok": True,
        "dir": str(latest),
        "restored": restored,
        "stamp": manifest.get("created") or latest.name,
        "label": manifest.get("label") or system,
    }
