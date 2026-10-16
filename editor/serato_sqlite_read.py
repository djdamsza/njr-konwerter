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
import sqlite3
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional
from urllib.parse import quote

from unified_model import Playlist, Track, UnifiedDatabase
from vdjfolder import normalize_path

_BACKUP_RE = re.compile(
    r"^(master|root|tidal)\.sqlite-backup-(.+)\.zip$",
    re.IGNORECASE,
)
_ROLES = ("master", "root", "tidal")
_ROOT_NAME = "serato library root"


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
        db = _read_roles(roles)
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
            f"{len(db.tracks)} utworów, {len(db.playlists)} list{miss}"
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
        grouped = _backup_groups(path.parent).get(stamp, {})
        if "master" not in grouped and "root" not in grouped:
            raise ValueError(
                "W tym folderze nie ma pary master.sqlite i root.sqlite z tego samego czasu."
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

    groups = _backup_groups(path)
    if not groups:
        raise ValueError("Folder kopii Serato jest pusty.")
    stamp = sorted(groups)[-1]
    return _unzip_group(groups[stamp], tmp), stamp, 0


def _backup_groups(directory: Path) -> dict[str, dict[str, Path]]:
    groups: dict[str, dict[str, Path]] = {}
    if not directory.is_dir():
        return groups
    for child in directory.iterdir():
        if not child.is_file():
            continue
        match = _BACKUP_RE.match(child.name)
        if not match:
            continue
        role, stamp = match.group(1).lower(), match.group(2)
        groups.setdefault(stamp, {})[role] = child
    return groups


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


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(path)) + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


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

    playlists: list[Playlist] = []
    if master is not None and "container" in _tables(master):
        playlists = _playlists_from_master(master, peripherals)
    if not playlists:
        for role in ("root", "tidal"):
            con = connections.get(role)
            if con is None or "container" not in _tables(con):
                continue
            assets = _assets_by_id(con, role, "")
            tree = _playlist_tree(con, lambda cid, a=assets, c=con: _tracks_in_container(c, cid, a))
            playlists.extend(tree)

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


def _tracks_in_container(
    con: sqlite3.Connection,
    container_id: int,
    assets: dict[int, Track],
) -> list[Track]:
    if "container_asset" not in _tables(con):
        return []
    cols = set(_cols(con, "container_asset"))
    order = " ORDER BY ca.list_order" if "list_order" in cols else ""
    if "space_asset_id" in cols and "space_asset" in _tables(con):
        query = (
            "SELECT sa.asset_id AS asset_id FROM container_asset ca "
            "JOIN space_asset sa ON sa.id = ca.space_asset_id "
            f"WHERE ca.container_id=?{order}"
        )
    elif "asset_id" in cols:
        query = f"SELECT ca.asset_id AS asset_id FROM container_asset ca WHERE ca.container_id=?{order}"
    else:
        return []
    out: list[Track] = []
    seen: set[str] = set()
    for row in con.execute(query, (container_id,)):
        track = assets.get(int(row["asset_id"]))
        if track is None:
            continue
        key = normalize_path(track.path)
        if key in seen:
            continue
        seen.add(key)
        out.append(track)
    return out


def _playlists_from_master(
    master: sqlite3.Connection,
    peripherals: dict[int, tuple[sqlite3.Connection, dict[int, Track]]],
) -> list[Playlist]:
    def tracks_of(container_id: int) -> list[Track]:
        if "location_container" not in _tables(master):
            return []
        found: list[Track] = []
        seen: set[str] = set()
        rows = master.execute(
            "SELECT location_id, external_container_id FROM location_container WHERE container_id=?",
            (container_id,),
        ).fetchall()
        for row in rows:
            peri = peripherals.get(int(row["location_id"]))
            ext_id = row["external_container_id"]
            if peri is None or ext_id is None:
                continue
            for track in _tracks_in_container(peri[0], int(ext_id), peri[1]):
                key = normalize_path(track.path)
                if key in seen:
                    continue
                seen.add(key)
                found.append(track)
        return found

    return _playlist_tree(master, tracks_of)


def _playlist_tree(con: sqlite3.Connection, tracks_of) -> list[Playlist]:
    cols = set(_cols(con, "container"))
    if "id" not in cols or "name" not in cols:
        return []
    params: list = []
    where = ""
    if "space_id" in cols and "space" in _tables(con):
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
    by_parent: dict[int, list[sqlite3.Row]] = {}
    ids = {int(r["id"]) for r in rows}
    for row in rows:
        parent = int(row["parent_id"] or 0)
        if parent not in ids:
            parent = 0
        by_parent.setdefault(parent, []).append(row)

    def build(parent_id: int) -> list[Playlist]:
        result: list[Playlist] = []
        for row in by_parent.get(parent_id, []):
            cid = int(row["id"])
            name = str(row["name"] or "").strip() or "lista"
            children = build(cid)
            tracks = tracks_of(cid)
            track_ids = [normalize_path(t.path) for t in tracks]
            if name.casefold() == _ROOT_NAME and parent_id == 0:
                result.extend(children)
                continue
            if children and track_ids:
                children = [Playlist(name=name, track_ids=track_ids, is_folder=False)] + children
                result.append(Playlist(name=name, track_ids=[], is_folder=True, children=children))
            elif children:
                result.append(Playlist(name=name, track_ids=[], is_folder=True, children=children))
            else:
                result.append(Playlist(name=name, track_ids=track_ids, is_folder=False))
        return result

    return build(0)
