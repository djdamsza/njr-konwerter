"""
Przepięcie ścieżek Serato z fizycznych lokalizacji MacBooka na pliki
pobrane z Dysku Google (ten komputer = backup, pliki zostają na GDrive).

Serato trzyma ścieżki względne do roota dysku (Users/…, Mój dysk/…).
Na Windows litera dysku Google (np. G:) różni się od ścieżek Maca
(/Users/…, Volumes/osx/…, Inne komputery/…).
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from library_paths import google_drive_roots
from serato_parser import (
    _rewrite_paths_in_container,
    canonical_serato_relative_path,
    to_serato_relative_path,
)

AUDIO_SUFFIXES = {".mp3", ".m4a", ".mp4", ".wav", ".flac", ".ogg", ".aac", ".aiff", ".aif", ".alac"}

_OTHER_COMPUTERS_RE = re.compile(r"(?i)^(?:[A-Za-z]:/)?Inne komputery/[^/]+/")
_CLOUDSTORAGE_RE = re.compile(
    r"(?i)^Users/[^/]+/Library/CloudStorage/GoogleDrive-[^/]+/(?:My Drive/|Mój dysk/)?"
)
_VOLUMES_RE = re.compile(r"(?i)^Volumes/[^/]+/")
_DRIVE_LETTER_RE = re.compile(r"(?i)^[A-Za-z]:/")
_USERS_HOME_RE = re.compile(r"(?i)^Users/[^/]+/")
_GOOGLE_FOLDER_RE = re.compile(
    r"(?i)^(?:Google Drive|GoogleDrive|My Drive|Mój dysk)/"
)


def strip_serato_machine_prefix(path: str) -> str:
    """Ścieżka bez komputera / woluminu / litery dysku — do dopasowania na GDrive."""
    p = to_serato_relative_path(path)
    if not p:
        return p
    for _ in range(8):
        nxt = _OTHER_COMPUTERS_RE.sub("", p, count=1)
        nxt = _CLOUDSTORAGE_RE.sub("", nxt, count=1)
        nxt = _VOLUMES_RE.sub("", nxt, count=1)
        nxt = _DRIVE_LETTER_RE.sub("", nxt, count=1)
        if nxt == p:
            break
        p = nxt
    return p.lstrip("/")


def _search_keys(path: str) -> list[str]:
    """Klucze od najdłuższego (pełna reszta) do nazwy pliku."""
    stripped = strip_serato_machine_prefix(path)
    # Users/macuser/Desktop/muzyka dj/a.mp3 → też bez Users/macuser/
    rest = _USERS_HOME_RE.sub("", stripped, count=1)
    keys: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        k = (raw or "").replace("\\", "/").strip("/").lower()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)

    add(stripped)
    add(rest)
    add(_GOOGLE_FOLDER_RE.sub("", rest, count=1))
    add(_GOOGLE_FOLDER_RE.sub("", stripped, count=1))
    parts = [x for x in rest.split("/") if x]
    for i in range(len(parts)):
        add("/".join(parts[i:]))
    return keys


def absolute_to_serato_portable(abs_path: Path | str) -> str:
    """Absolutna ścieżka Windows/Mac → portable_id Serato (bez litery dysku)."""
    s = str(abs_path).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = s[2:]
    return canonical_serato_relative_path(s)


def serato_portable_to_absolute_candidates(path: str) -> list[Path]:
    """Kandydaci na plik z wpisu Serato (Mac /Users, Windows C: i inne litery)."""
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return []
    out: list[Path] = []
    seen: set[str] = set()

    def add(cand: Path) -> None:
        key = str(cand).replace("\\", "/").lower()
        if key not in seen:
            seen.add(key)
            out.append(cand)

    if p.startswith("/"):
        add(Path(p))
        add(Path(p[1:]))
    if len(p) >= 2 and p[1] == ":":
        add(Path(p))
        add(Path(p[0] + ":/" + p[3:].lstrip("/")))
    rel = to_serato_relative_path(p)
    add(Path("/" + rel))
    home = Path.home()
    drive = getattr(home, "drive", "") or ""
    if drive:
        add(Path(f"{drive}/{rel}"))
    add(home / rel)
    # Users/thisuser/... → ~/...
    m = re.match(r"(?i)^Users/([^/]+)/(.*)$", rel)
    if m and m.group(1).lower() == home.name.lower():
        add(home / m.group(2))
    try:
        from library_paths import google_drive_roots, _windows_volumes
        if os.name == "nt":
            for letter, _label in _windows_volumes():
                add(Path(f"{letter}:/{rel}"))
        for root in google_drive_roots():
            for cand in _google_drive_join_candidates(root, rel):
                add(cand)
    except Exception:
        pass
    return out


def _google_drive_join_candidates(root: Path, rel: str) -> list[Path]:
    """root + rel bez podwójnego „Mój dysk/Mój dysk/…”."""
    rel_n = (rel or "").replace("\\", "/").strip("/")
    if not rel_n:
        return [root]
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        key = str(p).replace("\\", "/").lower()
        if key not in seen:
            seen.add(key)
            out.append(p)

    root_name = root.name.replace("\\", "/").lower()
    parts = [p for p in rel_n.split("/") if p]
    if parts and parts[0].lower() == root_name:
        rest = "/".join(parts[1:])
        add(root / rest if rest else root)
    else:
        add(root / rel_n)
    add(root / Path(rel_n).name)
    stripped = _GOOGLE_FOLDER_RE.sub("", rel_n, count=1).strip("/")
    if stripped and stripped != rel_n:
        add(root / stripped)
    return out


def serato_path_exists_on_disk(path: str) -> bool:
    """Czy wpis Serato wskazuje istniejący plik (także litera dysku na Windows)."""
    from vdj_streaming import is_serato_tidal_path

    p = (path or "").strip().replace("\\", "/")
    if not p:
        return False
    if is_serato_tidal_path(p):
        return True
    if "://" in p[:64] or p.startswith("clouddrive:"):
        return False
    for cand in serato_portable_to_absolute_candidates(p):
        try:
            if cand.is_file():
                return True
        except OSError:
            continue
    return False


def resolve_serato_portable_file(path: str) -> Optional[Path]:
    for cand in serato_portable_to_absolute_candidates(path):
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


class GoogleDriveAudioIndex:
    """Indeks plików audio na Dysku Google: suffix ścieżki → portable_id Serato."""

    def __init__(self, roots: list[Path]):
        self.roots = roots
        self.by_suffix: dict[str, list[str]] = {}
        self.files = 0
        for root in roots:
            self._index_root(root)

    def _index_root(self, root: Path) -> None:
        try:
            if not root.is_dir():
                return
        except OSError:
            return
        try:
            walker = root.rglob("*")
        except OSError:
            return
        for f in walker:
            try:
                if not f.is_file() or f.suffix.lower() not in AUDIO_SUFFIXES:
                    continue
                if f.name.startswith("._"):
                    continue
            except OSError:
                continue
            portable = absolute_to_serato_portable(f)
            self.files += 1
            rel_from_root = str(f.relative_to(root)).replace("\\", "/")
            for key in _search_keys(rel_from_root) + _search_keys(portable):
                bucket = self.by_suffix.setdefault(key, [])
                if portable not in bucket:
                    bucket.append(portable)

    def lookup(self, serato_path: str) -> Optional[str]:
        for key in _search_keys(serato_path):
            hits = self.by_suffix.get(key) or []
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                # Preferuj ten sam basename + najdłuższy wspólny ogon
                base = Path(serato_path.replace("\\", "/")).name.lower()
                named = [h for h in hits if Path(h).name.lower() == base]
                if len(named) == 1:
                    return named[0]
                if named:
                    return named[0]
                return hits[0]
        return None


def build_google_drive_audio_index(
    roots: Optional[list[Path]] = None,
) -> GoogleDriveAudioIndex:
    use = list(roots) if roots else google_drive_roots()
    return GoogleDriveAudioIndex(use)


def map_serato_path_to_google_drive(
    path: str,
    index: Optional[GoogleDriveAudioIndex] = None,
) -> Optional[str]:
    """Nowa ścieżka Serato na GDrive albo None gdy brak dopasowania."""
    idx = index or build_google_drive_audio_index()
    return idx.lookup(path)


def remap_serato_library_to_google_drive(
    serato_dir: Optional[Path] = None,
    *,
    google_drive: Optional[Path | str] = None,
    dry_run: bool = False,
    include_sqlite: bool = True,
    sqlite_dir: Optional[Path] = None,
) -> dict:
    """
    Przepina database V2 + Subcrates (+ root.sqlite) na pliki z Dysku Google.
    Nie kopiuje muzyki. Wymaga zamkniętego Serato. Kopia .bak.
    """
    from dj_apps_guard import is_serato_running, serato_db_likely_locked
    from library_paths import default_serato_dir, default_serato_sqlite_dir
    from vdj_streaming import is_serato_tidal_path

    running, msg = is_serato_running()
    if running:
        return {"ok": False, "error": msg}
    base = Path(serato_dir) if serato_dir else default_serato_dir()
    locked, lock_msg = serato_db_likely_locked(base)
    if locked:
        return {"ok": False, "error": lock_msg}

    if google_drive:
        roots = [Path(google_drive).expanduser()]
    else:
        roots = google_drive_roots()
    roots = [r for r in roots if r.is_dir()]
    if not roots:
        return {
            "ok": False,
            "error": (
                "Nie znaleziono Dysku Google. Podłącz lustrzane pliki (Google Drive for desktop) "
                "albo ustaw NJR_GOOGLE_DRIVE / wskaż folder w UI."
            ),
        }

    index = GoogleDriveAudioIndex(roots)
    db_file = base / "database V2"
    if not db_file.is_file():
        db_file = base / "Database V2"
    stats: dict = {
        "ok": True,
        "dry_run": dry_run,
        "serato_dir": str(base),
        "google_drive_roots": [str(r) for r in roots],
        "indexed_files": index.files,
        "db_rewrites": 0,
        "crate_files": 0,
        "crate_rewrites": 0,
        "unchanged": 0,
        "unmapped": 0,
        "redirects_sample": [],
        "backups": [],
        "sqlite": {"skipped": True},
    }
    if not db_file.is_file():
        stats["ok"] = False
        stats["error"] = f"Brak database V2 w {base}"
        return stats

    redirects: dict[str, str] = {}
    lookup_cache: dict[str, Optional[str]] = {}

    def transform(old: str) -> str:
        if is_serato_tidal_path(old) or "://" in (old or "")[:64]:
            return old
        if old in lookup_cache:
            mapped = lookup_cache[old]
        else:
            mapped = index.lookup(old)
            lookup_cache[old] = mapped
        if not mapped:
            stats["unmapped"] += 1
            return old
        canon_old = canonical_serato_relative_path(old)
        if mapped == canon_old or mapped == old.replace("\\", "/"):
            stats["unchanged"] += 1
            return canon_old
        redirects[old] = mapped
        redirects[canon_old] = mapped
        return mapped

    raw = db_file.read_bytes()
    new_blob, n_db = _rewrite_paths_in_container(raw, transform)
    stats["db_rewrites"] = n_db
    stats["redirects_sample"] = [
        {"from": a, "to": b} for a, b in list(redirects.items())[:8]
    ]

    crate_updates: list[tuple[Path, bytes]] = []
    crate_seen: set[str] = set()
    for folder in (base / "Subcrates", base / "Crates", base):
        if not folder.is_dir():
            continue
        for cf in folder.glob("*.crate"):
            try:
                key = str(cf.resolve())
            except OSError:
                key = str(cf)
            if key in crate_seen:
                continue
            crate_seen.add(key)
            try:
                craw = cf.read_bytes()
                cnew, crew = _rewrite_paths_in_container(craw, transform)
                if crew and cnew != craw:
                    crate_updates.append((cf, cnew))
                    stats["crate_files"] += 1
                    stats["crate_rewrites"] += crew
            except OSError:
                continue

    sqlite_lib = Path(sqlite_dir) if sqlite_dir else default_serato_sqlite_dir()
    if include_sqlite and dry_run:
        stats["sqlite"] = _remap_root_sqlite_to_google_drive(
            sqlite_lib,
            index,
            dry_run=True,
        )

    if dry_run:
        return stats

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = Path(str(db_file) + f".pre-gdrive-{stamp}.bak")
    bak.write_bytes(raw)
    stats["backups"].append(str(bak))
    db_file.write_bytes(new_blob)
    for cf, cnew in crate_updates:
        cbak = Path(str(cf) + f".pre-gdrive-{stamp}.bak")
        try:
            cbak.write_bytes(cf.read_bytes())
            cf.write_bytes(cnew)
            stats["backups"].append(str(cbak))
        except OSError:
            continue

    if include_sqlite:
        stats["sqlite"] = _remap_root_sqlite_to_google_drive(
            sqlite_lib,
            index,
            dry_run=False,
        )
    return stats


def _remap_root_sqlite_to_google_drive(
    library_dir: Path,
    index: GoogleDriveAudioIndex,
    *,
    dry_run: bool = False,
) -> dict:
    import sqlite3
    import time

    db_path = library_dir / "root.sqlite"
    if not db_path.is_file():
        return {"ok": True, "skipped": True, "reason": f"Brak {db_path}"}
    try:
        con = sqlite3.connect(str(db_path), timeout=60)
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e)}
    updated = 0
    missing = 0
    try:
        if not dry_run:
            con.execute("BEGIN IMMEDIATE")
        rows = con.execute(
            "SELECT id, portable_id, file_name FROM asset "
            "WHERE portable_id IS NOT NULL AND TRIM(portable_id) != ''"
        ).fetchall()
        for aid, pid, fname in rows:
            mapped = index.lookup(pid) or (index.lookup(fname) if fname else None)
            if not mapped or mapped == pid:
                if not serato_path_exists_on_disk(pid):
                    missing += 1
                continue
            abs_file = resolve_serato_portable_file(mapped)
            size = None
            if abs_file:
                try:
                    size = abs_file.stat().st_size
                except OSError:
                    pass
            if not dry_run:
                con.execute(
                    "UPDATE asset SET revision=revision+1, portable_id=?, is_missing=?, "
                    "file_size=COALESCE(?, file_size) WHERE id=?",
                    (mapped, 0 if abs_file else 1, size, aid),
                )
            updated += 1
        if not dry_run:
            try:
                con.execute(
                    "UPDATE master SET revision=revision+1, last_sync_time=?",
                    (int(time.time()),),
                )
            except sqlite3.Error:
                pass
            con.commit()
        else:
            con.rollback()
    except sqlite3.Error as e:
        if not dry_run:
            con.rollback()
        return {"ok": False, "error": str(e), "updated": updated}
    finally:
        con.close()
    return {"ok": True, "updated": updated, "still_missing": missing, "path": str(db_path)}
