"""
Fizyczne czyszczenie ukrytego cache Engine DJ na Macu.

Engine DJ przy „Create stems” kopiuje modele AI (~400 MB × N) do
``/var/folders/.../T/`` i **nie usuwa ich po zakończeniu** — znany bug:
https://community.enginedj.com/t/engine-desktop-not-cleaning-temp-files-after-stem-processing-on-mac/60940
(użytkownicy raportują setki GB temp przy większych kolekcjach)

NJR czyści ten cache automatycznie w watcherze i po każdej partii stemów.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from engine_libdjinterop import default_engine_desktop_library, is_engine_desktop_running

ENGINE_PRIME = Path.home() / "Library/Application Support/AIR Music Technology/EnginePrime"
OLD_PROCESSOR_DIRS = (
    "bin.v1.0.0.backup",
    "bin.old.20260714_220401",
    "bin.before-1.2.0.20260714_230152",
)
ML_ORPHAN_MIN_BYTES = 50_000_000
UUID_MODEL_RE = re.compile(
    r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}",
    re.I,
)


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        if path.is_file():
            return path.stat().st_size
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return 0


def _fmt_gb(n: int) -> float:
    return round(n / (1024**3), 3)


def _disk_free_gb(path: Path | None = None) -> float | None:
    try:
        return round(shutil.disk_usage(path or Path.home()).free / (1024**3), 2)
    except OSError:
        return None


def _all_temp_roots() -> list[Path]:
    roots: list[Path] = []
    tmp = os.environ.get("TMPDIR") or tempfile.gettempdir()
    if tmp:
        roots.append(Path(tmp))
    # Tylko katalog temp bieżącego użytkownika (nie całe /var/folders — Permission denied)
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        try:
            if r.is_dir():
                key = str(r.resolve())
                if key not in seen:
                    seen.add(key)
                    out.append(r)
        except OSError:
            pass
    return out


def _mlmodel_paths_in_temp(temp: Path) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    try:
        entries = list(temp.iterdir())
    except OSError:
        return paths
    for p in entries:
        name = p.name
        if name.endswith(".mlmodelc"):
            base = name[: -len(".mlmodelc")]
            seen.add(base)
            paths.append(p)
            sib = temp / base
            if sib.exists():
                paths.append(sib)
        elif (temp / f"{name}.mlmodelc").exists():
            if name not in seen:
                paths.append(p)
    for p in entries:
        if not p.is_file() or p.stat().st_size < ML_ORPHAN_MIN_BYTES:
            continue
        if p.name.endswith(".mlmodelc") or p.name.startswith("com."):
            continue
        if UUID_MODEL_RE.match(p.name) or "-000001" in p.name:
            if p not in paths:
                paths.append(p)
    return paths


def scan_engine_disk_usage(engine_dir: Path | None = None) -> dict:
    engine_dir = (engine_dir or default_engine_desktop_library()).resolve()
    dbdir = engine_dir / "Database2"
    stems_dir = engine_dir / "Stems"
    lib_backup = engine_dir.parent / "Engine Library Backup"

    items: list[dict] = []

    for temp in _all_temp_roots():
        for sub in ("EngineDJ", "EngineOS"):
            p = temp / sub
            if p.exists():
                items.append(
                    {
                        "path": str(p),
                        "kind": "engine_temp_dir",
                        "bytes": _dir_size(p),
                    }
                )
        for p in _mlmodel_paths_in_temp(temp):
            items.append(
                {
                    "path": str(p),
                    "kind": "engine_ml_model_cache",
                    "bytes": _dir_size(p),
                }
            )
        for name in ("com.inmusicbrands.EngineDJ", "com.air-music-technology.EnginePrime"):
            p = temp / name
            if p.exists():
                items.append(
                    {
                        "path": str(p),
                        "kind": "engine_app_cache",
                        "bytes": _dir_size(p),
                    }
                )

    if dbdir.is_dir():
        for pattern in ("m.db.pre-*", "m.db.njr-backup", "m.db-journal"):
            for f in dbdir.glob(pattern):
                if f.is_file():
                    items.append(
                        {
                            "path": str(f),
                            "kind": "m_db_backup",
                            "bytes": f.stat().st_size,
                        }
                    )

    for name in OLD_PROCESSOR_DIRS:
        p = ENGINE_PRIME / name
        if p.is_dir():
            items.append(
                {
                    "path": str(p),
                    "kind": "stems_processor_backup",
                    "bytes": _dir_size(p),
                }
            )

    if lib_backup.is_dir():
        items.append(
            {
                "path": str(lib_backup),
                "kind": "engine_library_backup",
                "bytes": _dir_size(lib_backup),
            }
        )

    stem_files = list(stems_dir.glob("*.stems")) if stems_dir.is_dir() else []
    stem_bytes = sum(f.stat().st_size for f in stem_files)
    mdb = dbdir / "m.db"
    total_reclaim = sum(i["bytes"] for i in items)

    return {
        "ok": True,
        "engine_dir": str(engine_dir),
        "mac_free_gb": _disk_free_gb(engine_dir),
        "engine_running": is_engine_desktop_running(),
        "cache_items": items,
        "cache_gb": _fmt_gb(total_reclaim),
        "mac_stems_count": len(stem_files),
        "mac_stems_gb": _fmt_gb(stem_bytes),
        "m_db_gb": _fmt_gb(mdb.stat().st_size if mdb.is_file() else 0),
        "temp_roots_scanned": len(_all_temp_roots()),
    }


def _remove_path(p: Path) -> int:
    if not p.exists():
        return 0
    sz = _dir_size(p)
    if p.is_file():
        p.unlink()
    else:
        shutil.rmtree(p)
    return sz


def clean_engine_hidden_cache(
    engine_dir: Path | None = None,
    *,
    quit_engine: bool = True,
    clear_mac_stems: bool = False,
    remove_library_backup: bool = True,
    vacuum_mdb: bool = False,
    empty_trash: bool = True,
) -> dict:
    """
    Fizycznie usuwa ukryty cache Engine DJ (modele AI, temp, backupy).
    ``clear_mac_stems`` — usuwa WSZYSTKIE .stems z Mac Stems/ (użyj po migracji na Patriot).
    """
    engine_dir = (engine_dir or default_engine_desktop_library()).resolve()
    before_free = _disk_free_gb(engine_dir)
    before_scan = scan_engine_disk_usage(engine_dir)
    actions: list[dict] = []
    removed = 0
    errors: list[str] = []

    if quit_engine and is_engine_desktop_running():
        subprocess.run(
            ["osascript", "-e", 'tell application "Engine DJ" to quit'],
            check=False,
        )
        import time

        for _ in range(90):
            if not is_engine_desktop_running():
                break
            time.sleep(0.5)
        if is_engine_desktop_running():
            return {
                "ok": False,
                "error": "Zamknij Engine DJ (Cmd+Q) i powtórz czyszczenie.",
                "before": before_scan,
            }
        actions.append({"action": "quit_engine"})

    seen_paths: set[str] = set()
    for item in before_scan.get("cache_items") or []:
        p = Path(item["path"])
        key = str(p)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        if item["kind"] == "engine_library_backup" and not remove_library_backup:
            continue
        try:
            sz = _remove_path(p)
            if sz > 0:
                removed += sz
                actions.append(
                    {"action": "remove", "kind": item["kind"], "path": key, "bytes": sz}
                )
        except OSError as ex:
            errors.append(f"{p}: {ex}")

    stems_dir = engine_dir / "Stems"
    if clear_mac_stems and stems_dir.is_dir():
        for f in stems_dir.glob("*.stems"):
            try:
                sz = f.stat().st_size
                f.unlink()
                removed += sz
                actions.append({"action": "remove_mac_stem", "path": str(f), "bytes": sz})
            except OSError as ex:
                errors.append(f"{f}: {ex}")

    if vacuum_mdb:
        mdb = engine_dir / "Database2" / "m.db"
        if mdb.is_file() and not is_engine_desktop_running():
            try:
                import sqlite3

                before_mdb = mdb.stat().st_size
                conn = sqlite3.connect(str(mdb))
                try:
                    conn.execute("VACUUM")
                    conn.commit()
                finally:
                    conn.close()
                after_mdb = mdb.stat().st_size
                freed = max(0, before_mdb - after_mdb)
                removed += freed
                actions.append(
                    {
                        "action": "vacuum_mdb",
                        "before_bytes": before_mdb,
                        "after_bytes": after_mdb,
                        "bytes": freed,
                    }
                )
            except OSError as ex:
                errors.append(f"VACUUM m.db: {ex}")

    if empty_trash:
        trash = Path.home() / ".Trash"
        if trash.is_dir():
            for f in trash.glob("*.stems"):
                try:
                    sz = _dir_size(f)
                    _remove_path(f)
                    removed += sz
                    actions.append({"action": "empty_trash_stem", "path": str(f), "bytes": sz})
                except OSError:
                    pass

    subprocess.run(["/usr/sbin/purge"], check=False)

    after_free = _disk_free_gb(engine_dir)
    return {
        "ok": len(errors) == 0,
        "removed_gb": _fmt_gb(removed),
        "mac_free_gb_before": before_free,
        "mac_free_gb_after": after_free,
        "mac_free_gb_delta": round((after_free or 0) - (before_free or 0), 2)
        if after_free is not None and before_free is not None
        else None,
        "actions": actions,
        "errors": errors,
        "before_cache_gb": before_scan.get("cache_gb"),
    }


# Backward-compatible API
def scan_reclaimable(engine_dir: Path | None = None) -> dict:
    scan = scan_engine_disk_usage(engine_dir)
    items = [
        {**i, "safe": True, "note": i.get("kind", "")}
        for i in scan.get("cache_items") or []
    ]
    return {
        "engine_dir": scan["engine_dir"],
        "reclaimable_items": items,
        "reclaimable_bytes": sum(i["bytes"] for i in items),
        "reclaimable_gb": scan.get("cache_gb", 0),
        "active_stem_files": scan.get("mac_stems_count", 0),
        "active_stem_bytes": int((scan.get("mac_stems_gb") or 0) * 1024**3),
        "active_m_db_bytes": int((scan.get("m_db_gb") or 0) * 1024**3),
        "note": "Ukryty cache Engine DJ (modele AI w /var/folders) + backupy.",
    }


def reclaim_engine_disk_space(
    engine_dir: Path | None = None,
    *,
    dry_run: bool = True,
) -> dict:
    if dry_run:
        scan = scan_reclaimable(engine_dir)
        return {
            "ok": True,
            "dry_run": True,
            "freed_bytes": scan["reclaimable_bytes"],
            "freed_gb": scan["reclaimable_gb"],
            "removed": [
                {**i, "action": "would_remove"} for i in scan["reclaimable_items"]
            ],
            "errors": [],
            "disk_free_gb_after": _disk_free_gb(),
            **{k: scan[k] for k in ("note", "active_stem_files", "active_stem_bytes")},
        }
    return clean_engine_hidden_cache(engine_dir, quit_engine=False)
