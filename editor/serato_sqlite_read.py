"""
Odczyt biblioteki Serato DJ 4/5 z trzech baz SQLite.

Serato trzyma jedną bibliotekę w trzech plikach:

- master.sqlite — drzewo playlist (crate'ów) i wskaźniki do pozostałych baz
- root.sqlite — utwory z dysku startowego
- tidal.sqlite — utwory Tidal (streaming://tidal/ID)

Kopie automatyczne leżą w Library/Backups jako osobne ZIP-y z tym samym
znacznikiem czasu, np. master.sqlite-backup-20261016_075713+0200.zip.
Otwarcie jednego ZIP-a nic nie daje: przy wskazaniu dowolnego z trójki
szukamy pozostałych z tej samej kopii i składamy jedną bibliotekę.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional
from urllib.parse import quote

from unified_model import Playlist, Track, UnifiedDatabase, count_playlist_entries
from vdjfolder import normalize_path

_BACKUP_RE = re.compile(
    r"^(master|root|tidal)\.sqlite-backup-(.+)\.zip$",
    re.IGNORECASE,
)
_ROLES = ("master", "root", "tidal")
_ROOT_NAME = "serato library root"
# Serato zapisuje trzy ZIP-y po kolei, często o sekundę od siebie.
_BACKUP_CLUSTER_SEC = 180
_snap_dirs: list[tempfile.TemporaryDirectory] = []


def is_serato_sqlite_source(path: Path) -> bool:
    """Czy ścieżka to kopia albo żywa biblioteka SQLite Serato (nie database V2)."""
    p = Path(path)
    if p.is_file() and _BACKUP_RE.match(p.name):
        return True
    if p.is_dir() and _sqlite_roles_in_dir(p):
        return True
    return False


def load_serato_sqlite_from_path(path: Path) -> tuple[UnifiedDatabase, dict]:
    """
    Ładuje trójkę master/root/tidal.
    path: jeden ZIP kopii, folder Backups, albo folder Library z plikami .sqlite.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Plik nie istnieje: {p}")

    with TemporaryDirectory(prefix="njr-serato-sqlite-") as tmp:
        roles, stamp, opened_extra = _resolve_role_files(p, Path(tmp))
        fallback_note = ""
        try:
            db = _read_roles(roles)
        except (sqlite3.Error, OSError) as exc:
            backup_dir = _backup_dir_near(p)
            if stamp or backup_dir is None:
                raise ValueError(_open_failure_message(p, exc)) from exc
            listed = _list_backups(backup_dir)
            if not listed:
                raise ValueError(_open_failure_message(p, exc)) from exc
            newest = max(listed, key=lambda item: item[2])
            grouped = _cluster_around(newest[1])
            roles = _unzip_group(grouped, Path(tmp) / "fallback")
            try:
                db = _read_roles(roles)
            except (sqlite3.Error, OSError) as exc2:
                raise ValueError(_open_failure_message(p, exc2)) from exc2
            stamp = _stamp_of(newest[1])
            fallback_note = " Żywej bazy nie dało się otworzyć, wczytałem ostatnią kopię z Backups."
        found = [name for name in _ROLES if name in roles]
        missing = [name for name in _ROLES if name not in roles]
        parts = " + ".join(f"{name}.sqlite" for name in found)
        stamp_bit = f", kopia {stamp}" if stamp else ""
        extra = ""
        if opened_extra:
            extra = f", dyski: {opened_extra}"
        miss = ""
        if missing:
            miss = ". Brak " + ", ".join(f"{name}.sqlite" for name in missing)
            if "tidal" in missing:
                miss += " (utwory Tidal z tej kopii nie wejdą)"
            if "master" in missing:
                miss += " (zostają utwory, bez drzewa playlist z master)"
        message = (
            f"Załadowano Serato ({parts}{stamp_bit}{extra}) — "
            f"{len(db.tracks)} utworów, {count_playlist_entries(db.playlists)} list{miss}{fallback_note}"
        )
        info = {
            "message": message,
            "roles": found,
            "missing": missing,
            "stamp": stamp,
            "tracks": len(db.tracks),
            "playlists": len(db.playlists),
        }
        return db, info


def _sqlite_roles_in_dir(directory: Path) -> dict[str, list[Path]]:
    """role -> pliki (żywe .sqlite albo ZIP-y kopii)."""
    found: dict[str, list[Path]] = {}
    if not directory.is_dir():
        return found
    for child in directory.iterdir():
        if not child.is_file():
            continue
        low = child.name.lower()
        for role in _ROLES:
            if low == f"{role}.sqlite":
                found.setdefault(role, []).append(child)
        match = _BACKUP_RE.match(child.name)
        if match:
            found.setdefault(match.group(1).lower(), []).append(child)
    return found


def _resolve_role_files(path: Path, tmp: Path) -> tuple[dict[str, Path], str, int]:
    """Zwraca role -> ścieżka sqlite, znacznik kopii, liczbę obcych location.sqlite."""
    if path.is_file():
        match = _BACKUP_RE.match(path.name)
        if not match:
            raise ValueError(
                "To nie jest kopia biblioteki Serato (master/root/tidal.sqlite-backup-….zip)."
            )
        stamp = match.group(2)
        grouped = _cluster_around(path)
        if "master" not in grouped and "root" not in grouped:
            raise ValueError(
                "W tym folderze nie ma pary master.sqlite i root.sqlite z tej samej kopii."
            )
        return _unzip_group(grouped, tmp), stamp, 0

    roles_present = _sqlite_roles_in_dir(path)
    if not roles_present:
        raise ValueError(
            "Folder nie zawiera biblioteki Serato (master.sqlite / root.sqlite / tidal.sqlite "
            "ani kopii master.sqlite-backup-….zip)."
        )
    # Żywe pliki mają pierwszeństwo przed ZIP-ami w tym samym folderze.
    live = {
        role: next(p for p in paths if p.suffix.lower() == ".sqlite" and "backup" not in p.name.lower())
        for role, paths in roles_present.items()
        if any(p.suffix.lower() == ".sqlite" and "backup" not in p.name.lower() for p in paths)
    }
    if live:
        if "master" not in live and "root" not in live:
            raise ValueError("W folderze jest tidal.sqlite, ale nie ma master.sqlite ani root.sqlite.")
        return live, "", 0

    listed = _list_backups(path)
    if not listed:
        raise ValueError("Folder kopii Serato jest pusty.")
    newest = max(listed, key=lambda item: item[2])
    grouped = _cluster_around(newest[1])
    return _unzip_group(grouped, tmp), _stamp_of(newest[1]), 0


def _stamp_of(path: Path) -> str:
    match = _BACKUP_RE.match(path.name)
    return match.group(2) if match else ""


def _parse_stamp(stamp: str) -> Optional[datetime]:
    """20261016_075713+0200 → datetime. Bez strefy zostaje naiwny czas z nazwy."""
    text = stamp.strip()
    for fmt in ("%Y%m%d_%H%M%S%z", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _list_backups(directory: Path) -> list[tuple[str, Path, datetime]]:
    found: list[tuple[str, Path, datetime]] = []
    if not directory.is_dir():
        return found
    for child in directory.iterdir():
        if not child.is_file():
            continue
        match = _BACKUP_RE.match(child.name)
        if not match:
            continue
        when = _parse_stamp(match.group(2))
        if when is None:
            continue
        found.append((match.group(1).lower(), child, when))
    return found


def _cluster_around(anchor: Path) -> dict[str, Path]:
    """master/root/tidal z tego samego zapisu, nawet gdy czas w nazwie różni się o sekundę."""
    match = _BACKUP_RE.match(anchor.name)
    if not match:
        return {}
    when = _parse_stamp(match.group(2))
    grouped: dict[str, tuple[float, Path]] = {}
    if when is None:
        grouped[match.group(1).lower()] = (0.0, anchor)
        return {role: path for role, (_delta, path) in grouped.items()}
    for role, path, stamped in _list_backups(anchor.parent):
        delta = abs((stamped - when).total_seconds())
        if delta > _BACKUP_CLUSTER_SEC:
            continue
        current = grouped.get(role)
        if current is None or delta < current[0]:
            grouped[role] = (delta, path)
    grouped[match.group(1).lower()] = (0.0, anchor)
    return {role: path for role, (_delta, path) in grouped.items()}


def _unzip_group(grouped: dict[str, Path], tmp: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for role, zip_path in grouped.items():
        dest = tmp / role
        dest.mkdir(parents=True, exist_ok=True)
        out[role] = _extract_sqlite(zip_path, dest)
    return out


def _extract_sqlite(zip_path: Path, dest: Path) -> Path:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [n for n in zf.namelist() if n and not n.endswith("/")]
            if not names:
                raise ValueError(f"Pusta kopia: {zip_path.name}")
            pick = next((n for n in names if n.lower().endswith(".sqlite")), names[0])
            zf.extract(pick, dest)
    except zipfile.BadZipFile as e:
        raise ValueError(f"Nie można otworzyć {zip_path.name}: {e}") from e
    extracted = dest / pick
    if not extracted.is_file():
        raise ValueError(f"W {zip_path.name} nie ma pliku bazy.")
    return extracted


def _backup_dir_near(path: Path) -> Optional[Path]:
    folder = path if path.is_dir() else path.parent
    backup = folder / "Backups"
    return backup if backup.is_dir() else None


def _open_failure_message(path: Path, exc: BaseException) -> str:
    from mac_access import offer_library_access

    folder = path if path.is_dir() else path.parent
    raw = str(exc)
    low = raw.lower()
    if "unable to open" in low or "permission" in low or "operation not permitted" in low:
        offer_library_access(folder, "Serato")
        return (
            f"Nie mogę otworzyć bazy Serato w {folder}. Zamknij Serato (Cmd+Q). "
            "Jeśli macOS nie pyta o zgodę, włącz Pełny dostęp do dysku dla Terminala "
            "albo aplikacji, z której uruchamiasz NJR "
            "(Ustawienia systemowe → Prywatność i ochrona) i pobierz bazę ponownie. "
            f"Szczegół: {raw}"
        )
    if "not a database" in low:
        return f"Plik w {folder} nie jest zwykłą bazą SQLite. Szczegół: {raw}"
    return f"Nie mogę odczytać bazy Serato w {folder}: {raw}"


def _snapshot_sqlite(path: Path) -> Path:
    """Kopia pliku razem z -wal/-shm. Odczyt żywej bazy Serato pada, gdy plik jest w trybie WAL."""
    tmp = tempfile.TemporaryDirectory(prefix="njr-serato-snap-")
    _snap_dirs.append(tmp)
    dest = Path(tmp.name) / path.name
    shutil.copy2(path, dest)
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        if side.is_file():
            shutil.copy2(side, Path(str(dest) + suffix))
    return dest


def _cleanup_snaps() -> None:
    while _snap_dirs:
        _snap_dirs.pop().cleanup()


def _connect_ro(path: Path) -> sqlite3.Connection:
    last: Optional[BaseException] = None
    candidates: list[Path] = []
    try:
        candidates.append(_snapshot_sqlite(path))
    except OSError as exc:
        last = exc
    candidates.append(path)
    for candidate in candidates:
        try:
            con = sqlite3.connect(str(candidate))
            con.row_factory = sqlite3.Row
            try:
                con.execute("PRAGMA query_only=ON")
            except sqlite3.Error:
                pass
            con.execute("SELECT name FROM sqlite_master LIMIT 1")
            return con
        except sqlite3.Error as exc:
            last = exc
    quoted = quote(str(path), safe="/")
    for uri in (
        f"file:{quoted}?mode=ro&immutable=1",
        f"file:{quoted}?mode=ro",
    ):
        try:
            con = sqlite3.connect(uri, uri=True)
            con.row_factory = sqlite3.Row
            con.execute("SELECT name FROM sqlite_master LIMIT 1")
            return con
        except sqlite3.Error as exc:
            last = exc
    raise sqlite3.OperationalError(str(last) if last else "unable to open database file")


def _tables(con: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _cols(con: sqlite3.Connection, table: str) -> list[str]:
    if table not in _tables(con):
        return []
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _read_roles(roles: dict[str, Path]) -> UnifiedDatabase:
    if "master" not in roles and "root" not in roles:
        raise ValueError("Potrzebny jest master.sqlite albo root.sqlite.")

    connections: dict[str, sqlite3.Connection] = {}
    try:
        for role, path in roles.items():
            connections[role] = _connect_ro(path)
        return _assemble(connections, roles)
    finally:
        for con in connections.values():
            con.close()
        _cleanup_snaps()


def _assemble(
    connections: dict[str, sqlite3.Connection],
    role_paths: dict[str, Path],
) -> UnifiedDatabase:
    master = connections.get("master")
    peripherals = _open_peripherals(master, connections, role_paths)

    tracks_by_path: dict[str, Track] = {}
    for _loc_id, (con, _assets) in peripherals.items():
        for track in _assets.values():
            key = normalize_path(track.path)
            if key and key not in tracks_by_path:
                tracks_by_path[key] = track

    candidates: list[list[Playlist]] = []
    if master is not None and "container" in _tables(master):
        candidates.append(_playlists_from_master(master, peripherals, restrict_space=True))
        candidates.append(_playlists_from_master(master, peripherals, restrict_space=False))
    for role in ("root", "tidal"):
        con = connections.get(role)
        if con is None or "container" not in _tables(con):
            continue
        assets = _assets_by_id(con, role, str(role_paths.get(role, "")))
        tracks_of = lambda cid, a=assets, c=con: _tracks_in_container(c, cid, a)
        candidates.append(_playlist_tree(con, tracks_of, restrict_space=True))
        candidates.append(_playlist_tree(con, tracks_of, restrict_space=False))
    playlists = _richest_playlist_tree(candidates)

    return UnifiedDatabase(
        tracks=list(tracks_by_path.values()),
        playlists=playlists,
        source="serato",
    )


def _open_peripherals(
    master: Optional[sqlite3.Connection],
    connections: dict[str, sqlite3.Connection],
    role_paths: dict[str, Path],
) -> dict[int, tuple[sqlite3.Connection, dict[int, Track]]]:
    """location_id -> (połączenie, asset_id -> Track)."""
    by_basename: dict[str, tuple[str, sqlite3.Connection]] = {}
    for role, con in connections.items():
        if role == "master":
            continue
        by_basename[f"{role}.sqlite"] = (role, con)

    peripherals: dict[int, tuple[sqlite3.Connection, dict[int, Track]]] = {}
    used_roles: set[str] = set()

    if master is not None and "connection" in _tables(master):
        rows = master.execute("SELECT location_id, database_uri FROM connection").fetchall()
        for row in rows:
            loc_id = int(row["location_id"])
            uri = str(row["database_uri"] or "")
            base = Path(uri.replace("\\", "/")).name.lower()
            hit = by_basename.get(base)
            if hit:
                role, con = hit
                used_roles.add(role)
                peripherals[loc_id] = (con, _assets_by_id(con, role, uri))
                continue
            external = Path(uri)
            if base == "location.sqlite" and external.is_file():
                con = _connect_ro(external)
                connections.setdefault(f"ext-{loc_id}", con)
                peripherals[loc_id] = (con, _assets_by_id(con, "location", uri))

    # Bazy z kopii, których master nie wskazał (albo mastera nie ma).
    next_id = -1
    for role, con in connections.items():
        if role in ("master",) or role in used_roles or role.startswith("ext-"):
            continue
        if "asset" not in _tables(con):
            continue
        while next_id in peripherals:
            next_id -= 1
        uri = str(role_paths.get(role, ""))
        peripherals[next_id] = (con, _assets_by_id(con, role, uri))
        next_id -= 1
    return peripherals


def _assets_by_id(con: sqlite3.Connection, role: str, connection_uri: str) -> dict[int, Track]:
    if "asset" not in _tables(con):
        return {}
    cols = set(_cols(con, "asset"))
    wanted = [
        "id",
        "portable_id",
        "file_name",
        "artist",
        "name",
        "album",
        "genre",
        "key",
        "bpm",
        "length_sec",
        "length_ms",
        "rating",
        "comments",
        "year",
        "dj_play_count",
    ]
    select = [c for c in wanted if c in cols]
    if "id" not in select or "portable_id" not in select:
        return {}
    out: dict[int, Track] = {}
    for row in con.execute(f"SELECT {', '.join(select)} FROM asset"):
        track = _row_to_track(row, role, connection_uri)
        if track is not None:
            out[int(row["id"])] = track
    return out


def _row_to_track(row: sqlite3.Row, role: str, connection_uri: str) -> Optional[Track]:
    portable = str(row["portable_id"] or "").strip()
    if not portable:
        return None
    path = _full_path(portable, role, connection_uri)
    if not path:
        return None
    keys = row.keys()
    length_ms = _num(row, "length_ms") if "length_ms" in keys else None
    length_sec = _num(row, "length_sec") if "length_sec" in keys else None
    duration = 0.0
    if length_ms and length_ms > 0:
        duration = float(length_ms) / 1000.0
    elif length_sec and length_sec > 0:
        duration = float(length_sec)
    rating_raw = _num(row, "rating") if "rating" in keys else None
    rating = 0
    if rating_raw and rating_raw > 0:
        rating = int(round(rating_raw * 255)) if rating_raw <= 1 else int(round(rating_raw))
        rating = max(0, min(255, rating))
    year_raw = str(row["year"]).strip() if "year" in keys and row["year"] is not None else ""
    year = int(year_raw) if year_raw.isdigit() else 0
    genre = str(row["genre"] or "") if "genre" in keys else ""
    return Track(
        path=path,
        title=str(row["name"] or "") if "name" in keys else "",
        artist=str(row["artist"] or "") if "artist" in keys else "",
        album=str(row["album"] or "") if "album" in keys else "",
        genre=genre,
        tags=[t for t in genre.split() if t],
        comment=str(row["comments"] or "") if "comments" in keys else "",
        bpm=float(_num(row, "bpm") or 0) if "bpm" in keys else 0.0,
        key=str(row["key"] or "") if "key" in keys else "",
        year=year,
        duration=duration,
        play_count=int(_num(row, "dj_play_count") or 0) if "dj_play_count" in keys else 0,
        rating=rating,
    )


def _num(row: sqlite3.Row, col: str):
    if col not in row.keys():
        return None
    value = row[col]
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _full_path(portable: str, role: str, connection_uri: str) -> str:
    if portable.lower().startswith("streaming://"):
        return portable
    if len(portable) > 2 and portable[1] == ":":
        return portable.replace("\\", "/")
    uri = (connection_uri or "").replace("\\", "/")
    root = ""
    match = re.search(r"^(.*?)/_Serato_/Library/location\.sqlite$", uri, re.IGNORECASE)
    if match:
        root = match.group(1) or "/"
    elif uri.lower().endswith("/root.sqlite") or role == "root":
        root = "/"
    elif uri.lower().endswith("/location.sqlite"):
        root = "/"
    if root == "/":
        return "/" + portable.lstrip("/")
    if root:
        return root.rstrip("/") + "/" + portable.lstrip("/")
    if portable.startswith("/"):
        return portable
    return "/" + portable.lstrip("/")


def _space_asset_asset_id(con: sqlite3.Connection, space_asset_id: int) -> Optional[int]:
    if "space_asset" not in _tables(con):
        return None
    row = con.execute(
        "SELECT asset_id FROM space_asset WHERE id=?",
        (space_asset_id,),
    ).fetchone()
    if row is None or row["asset_id"] is None:
        return None
    return int(row["asset_id"])


def _track_from_space_asset(
    con: sqlite3.Connection,
    assets: dict[int, Track],
    space_asset_id: int,
) -> Optional[Track]:
    """space_asset.id → asset, albo wprost asset id, zależnie od bazy."""
    asset_id = _space_asset_asset_id(con, space_asset_id)
    if asset_id is not None:
        hit = assets.get(asset_id)
        if hit is not None:
            return hit
    return assets.get(space_asset_id)


def _resolve_membership_track(
    master: sqlite3.Connection,
    peripherals: dict[int, tuple[sqlite3.Connection, dict[int, Track]]],
    preferred: Optional[tuple[sqlite3.Connection, dict[int, Track]]],
    space_asset_id: int,
) -> Optional[Track]:
    """space_asset_id z master.container_asset → utwór w bazie dysku.

    Najpierw baza wskazana przez location_container.location_id.
    Potem space_asset w masterze (asset_id bywa wspólne z root/tidal).
    Na końcu pozostałe bazy, tylko gdy location nie jest znane.
    """
    if preferred is not None:
        hit = _track_from_space_asset(preferred[0], preferred[1], space_asset_id)
        if hit is not None:
            return hit
    asset_id = _space_asset_asset_id(master, space_asset_id)
    pools: list[dict[int, Track]] = []
    if preferred is not None:
        pools.append(preferred[1])
    pools.extend(assets for _loc, (_con, assets) in peripherals.items())
    if asset_id is not None:
        for assets in pools:
            hit = assets.get(asset_id)
            if hit is not None:
                return hit
    if preferred is None:
        for _loc, (con, assets) in peripherals.items():
            hit = _track_from_space_asset(con, assets, space_asset_id)
            if hit is not None:
                return hit
    return None


def _tracks_in_container(
    con: sqlite3.Connection,
    container_id: int,
    assets: dict[int, Track],
) -> list[Track]:
    """Utwory listy w root.sqlite / tidal.sqlite.

    Ten projekt zapisuje container_asset(container_id, space_asset_id),
    a space_asset.id wskazuje asset. Część baz trzyma w space_asset_id od razu asset id.
    """
    if "container_asset" not in _tables(con):
        return []
    cols = set(_cols(con, "container_asset"))
    if "container_id" not in cols:
        return []
    order = " ORDER BY ca.list_order" if "list_order" in cols else ""
    queries: list[str] = []
    if "space_asset_id" in cols and "space_asset" in _tables(con):
        queries.append(
            "SELECT sa.asset_id AS asset_id FROM container_asset ca "
            "JOIN space_asset sa ON sa.id = ca.space_asset_id "
            f"WHERE ca.container_id=?{order}"
        )
    if "asset_id" in cols:
        queries.append(
            f"SELECT ca.asset_id AS asset_id FROM container_asset ca WHERE ca.container_id=?{order}"
        )
    out: list[Track] = []
    seen: set[str] = set()

    def take(asset_id) -> None:
        if asset_id is None:
            return
        track = assets.get(int(asset_id))
        if track is None and "space_asset_id" in cols:
            track = _track_from_space_asset(con, assets, int(asset_id))
        if track is None:
            return
        key = normalize_path(track.path)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(track)

    for query in queries:
        rows = con.execute(query, (container_id,)).fetchall()
        if not rows:
            continue
        for row in rows:
            take(row["asset_id"])
        if out:
            return out
    if "space_asset_id" in cols:
        rows = con.execute(
            f"SELECT ca.space_asset_id AS asset_id FROM container_asset ca WHERE ca.container_id=?{order}",
            (container_id,),
        ).fetchall()
        for row in rows:
            take(row["asset_id"])
    return out


def _playlist_score(playlists: list[Playlist]) -> tuple[int, int, int]:
    """Więcej utworów w listach wygrywa z samym zestawem pustych nazw."""
    lists = 0
    tracks = 0
    folders = 0
    stack = list(playlists or [])
    while stack:
        pl = stack.pop()
        children = list(pl.children or [])
        if pl.is_folder or children:
            folders += 1
            stack.extend(children)
        if pl.track_ids and not pl.is_folder:
            lists += 1
            tracks += len(pl.track_ids)
    return (tracks, lists, folders)


def _richest_playlist_tree(candidates: list[list[Playlist]]) -> list[Playlist]:
    best: list[Playlist] = []
    best_score = (-1, -1, -1)
    for tree in candidates:
        score = _playlist_score(tree)
        if score > best_score:
            best_score = score
            best = tree
    return best


def _attach_unique_same_name_crate(
    master: sqlite3.Connection,
    container_id: int,
    peripherals: dict[int, tuple[sqlite3.Connection, dict[int, Track]]],
    add,
) -> None:
    """Gdy master ma nazwę crate, a external_container_id nie wskazuje utworów.

    Bierzemy utwory tylko wtedy, gdy dokładnie jedna lista o tej nazwie w root/tidal
    faktycznie je ma. Dwie listy o tej samej nazwie zostawiamy, żeby ich nie pomieszać.
    """
    if "container" not in _tables(master):
        return
    row = master.execute(
        "SELECT name FROM container WHERE id=?",
        (container_id,),
    ).fetchone()
    name = str(row["name"] or "").strip() if row is not None else ""
    if not name or name.casefold() == _ROOT_NAME:
        return
    matches: list[list[Track]] = []
    for _loc, (con, assets) in peripherals.items():
        if "container" not in _tables(con):
            continue
        cols = set(_cols(con, "container"))
        if "id" not in cols or "name" not in cols:
            continue
        ids = con.execute(
            "SELECT id FROM container WHERE name=? COLLATE NOCASE",
            (name,),
        ).fetchall()
        for cid in ids:
            tracks = _tracks_in_container(con, int(cid["id"]), assets)
            if tracks:
                matches.append(tracks)
    if len(matches) != 1:
        return
    for track in matches[0]:
        add(track)


def _playlists_from_master(
    master: sqlite3.Connection,
    peripherals: dict[int, tuple[sqlite3.Connection, dict[int, Track]]],
    *,
    restrict_space: bool = True,
) -> list[Playlist]:
    def tracks_of(container_id: int) -> list[Track]:
        found: list[Track] = []
        seen: set[str] = set()

        def add(track: Optional[Track]) -> None:
            if track is None:
                return
            key = normalize_path(track.path)
            if not key or key in seen:
                return
            seen.add(key)
            found.append(track)

        rows = []
        if "location_container" in _tables(master):
            rows = master.execute(
                "SELECT id, location_id, external_container_id FROM location_container WHERE container_id=?",
                (container_id,),
            ).fetchall()
        lc_ids: list[int] = []
        lc_location: dict[int, int] = {}
        for row in rows:
            lc_id = int(row["id"])
            lc_ids.append(lc_id)
            lc_location[lc_id] = int(row["location_id"])
            peri = peripherals.get(int(row["location_id"]))
            ext_id = row["external_container_id"]
            if peri is None or ext_id is None:
                continue
            for track in _tracks_in_container(peri[0], int(ext_id), peri[1]):
                add(track)
        # master.sqlite trzyma skład listy w container_asset, nie w root.container_id.
        # Kolumna to location_container_id (serato_library_sqlite.repair_master_sqlite_foreign_keys)
        # albo container_id wskazujący kontener mastera. external_container_id bywa puste.
        ca_cols = set(_cols(master, "container_asset"))
        if "space_asset_id" in ca_cols and lc_ids and "location_container_id" in ca_cols:
            marks = ",".join("?" * len(lc_ids))
            linked = master.execute(
                "SELECT location_container_id, space_asset_id FROM container_asset "
                f"WHERE location_container_id IN ({marks})",
                lc_ids,
            ).fetchall()
            for row in linked:
                if row["space_asset_id"] is None:
                    continue
                loc_id = lc_location.get(int(row["location_container_id"]))
                peri = peripherals.get(loc_id) if loc_id is not None else None
                add(
                    _resolve_membership_track(
                        master, peripherals, peri, int(row["space_asset_id"])
                    )
                )
        if "space_asset_id" in ca_cols and "container_id" in ca_cols:
            select_loc = (
                ", location_container_id"
                if "location_container_id" in ca_cols
                else ""
            )
            linked = master.execute(
                "SELECT space_asset_id"
                f"{select_loc} FROM container_asset WHERE container_id=?",
                (container_id,),
            ).fetchall()
            for row in linked:
                if row["space_asset_id"] is None:
                    continue
                loc_id = None
                if "location_container_id" in row.keys() and row["location_container_id"] is not None:
                    loc_id = lc_location.get(int(row["location_container_id"]))
                peri = peripherals.get(loc_id) if loc_id is not None else None
                add(
                    _resolve_membership_track(
                        master, peripherals, peri, int(row["space_asset_id"])
                    )
                )
        if not found:
            _attach_unique_same_name_crate(master, container_id, peripherals, add)
        return found

    return _playlist_tree(master, tracks_of, restrict_space=restrict_space)


def _playlist_tree(con: sqlite3.Connection, tracks_of, *, restrict_space: bool = True) -> list[Playlist]:
    cols = set(_cols(con, "container"))
    if "id" not in cols or "name" not in cols:
        return []
    params: list = []
    where = ""
    if restrict_space and "space_id" in cols and "space" in _tables(con):
        spaces = [r[0] for r in con.execute("SELECT id FROM space WHERE name='Serato Library'")]
        if spaces:
            marks = ",".join("?" * len(spaces))
            where = f"WHERE space_id IN ({marks})"
            params = spaces
    order = "list_order" if "list_order" in cols else "id"
    type_col = "type" if "type" in cols else "0"
    parent_col = "parent_id" if "parent_id" in cols else "0"
    rows = con.execute(
        f"SELECT id, {parent_col} AS parent_id, name, {type_col} AS type "
        f"FROM container {where} ORDER BY {order}, id",
        params,
    ).fetchall()
    ids = {int(r["id"]) for r in rows}
    parent_of: dict[int, int] = {}
    row_by_id: dict[int, sqlite3.Row] = {}
    for row in rows:
        cid = int(row["id"])
        row_by_id[cid] = row
        parent = int(row["parent_id"] or 0)
        if parent not in ids or parent == cid:
            parent = 0
        parent_of[cid] = parent
    # Pętla parent_id (A→B→A) albo łańcuch głębszy niż limit Pythona wywalało wczytanie.
    state: set[int] = set()
    for start in list(parent_of):
        path: list[int] = []
        cur = start
        while parent_of.get(cur, 0) and cur not in state:
            if cur in path:
                parent_of[cur] = 0
                break
            path.append(cur)
            cur = parent_of.get(cur, 0)
        state.update(path)

    by_parent: dict[int, list[sqlite3.Row]] = {}
    for cid, row in row_by_id.items():
        by_parent.setdefault(parent_of.get(cid, 0), []).append(row)

    depth = {0: 0}
    queue = [0]
    while queue:
        pid = queue.pop(0)
        for row in by_parent.get(pid, []):
            cid = int(row["id"])
            if cid in depth:
                continue
            depth[cid] = depth[pid] + 1
            queue.append(cid)
    max_depth = max(depth.values(), default=0)

    def make(cid: int, parent_id: int, child_nodes: list[Playlist]) -> list[Playlist]:
        row = row_by_id[cid]
        name = str(row["name"] or "").strip() or "lista"
        track_ids = [normalize_path(t.path) for t in tracks_of(cid)]
        if name.casefold() == _ROOT_NAME and parent_id == 0:
            hoisted = list(child_nodes)
            if track_ids:
                hoisted.append(Playlist(name=name, track_ids=track_ids, is_folder=False))
            return hoisted
        if child_nodes and track_ids:
            child_nodes = [Playlist(name=name, track_ids=track_ids, is_folder=False)] + child_nodes
            return [Playlist(name=name, track_ids=[], is_folder=True, children=child_nodes)]
        if child_nodes:
            return [Playlist(name=name, track_ids=[], is_folder=True, children=child_nodes)]
        return [Playlist(name=name, track_ids=track_ids, is_folder=False)]

    children_of: dict[int, list[Playlist]] = {}
    for level in range(max_depth, -1, -1):
        for pid, dep in list(depth.items()):
            if dep != level:
                continue
            built: list[Playlist] = []
            for row in by_parent.get(pid, []):
                cid = int(row["id"])
                built.extend(make(cid, pid, children_of.get(cid, [])))
            children_of[pid] = built
    return children_of.get(0, [])
