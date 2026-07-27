"""
Zapis utworów Tidal streaming do Serato Library SQLite (tidal.sqlite).

Nowoczesne Serato nie akceptuje tidal:tracks:ID w .crate / database V2
(log: „Unable to determine track type … found in crate”). Ręczne przeciągnięcie
Tidal na lokalną listę zapisuje assety jako streaming://tidal/ID w
~/Library/Application Support/Serato/Library/tidal.sqlite (space Serato Library).

Wymaga zamkniętego Serato.
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from vdj_streaming import extract_tidal_id, is_serato_tidal_path

SERATO_LIBRARY_DIR = Path.home() / "Library/Application Support/Serato/Library"
TIDAL_SQLITE = SERATO_LIBRARY_DIR / "tidal.sqlite"

# tidal.sqlite: space_id 2 = Serato Library (lokalne crates z streamingiem)
SPACE_SERATO_LIBRARY = 2
CONTAINER_TYPE_CRATE = 1


TIDAL_PLACEHOLDER_RE = re.compile(r"^Tidal\s+\d+$", re.I)


def is_tidal_placeholder_name(name: str, tidal_id: str = "") -> bool:
    """True gdy nazwa to placeholder „Tidal 12345” zamiast tytułu utworu."""
    nm = (name or "").strip()
    if not nm:
        return True
    if TIDAL_PLACEHOLDER_RE.match(nm):
        return True
    tid = str(tidal_id or "").strip()
    return bool(tid and nm.casefold() == f"tidal {tid}".casefold())


def _read_serato_tidal_ssl_xml(meta_dir: Path, tidal_id: str) -> dict:
    """Odczyt Metadata/Tidal/{id}.xml → dict(name, artist, album, bpm, key, length_sec)."""
    import xml.etree.ElementTree as ET

    xml_path = meta_dir / f"{tidal_id}.xml"
    if not xml_path.is_file():
        return {}
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return {}
    out: dict = {}
    for tag in ("Name", "Artist", "Album", "Key"):
        el = root.find(tag)
        if el is not None and (el.text or "").strip():
            out[tag.lower()] = (el.text or "").strip()
    bpm_el = root.find("BPM")
    if bpm_el is not None and (bpm_el.text or "").strip():
        try:
            out["bpm"] = float(bpm_el.text)
        except ValueError:
            pass
    len_el = root.find("Length")
    if len_el is not None and (len_el.text or "").strip():
        try:
            out["length_sec"] = float(len_el.text)
        except ValueError:
            pass
    return out


def _library_dir(serato_library_dir: Optional[Path] = None) -> Path:
    return Path(serato_library_dir) if serato_library_dir else SERATO_LIBRARY_DIR


def serato_is_likely_running(serato_library_dir: Optional[Path] = None) -> bool:
    """Heurystyka: proces Serato DJ lub świeży WAL/SHM database V2."""
    from dj_apps_guard import is_serato_running, serato_db_likely_locked

    running, _ = is_serato_running()
    if running:
        return True
    serato_dir = Path.home() / "Music" / "_Serato_"
    locked, _ = serato_db_likely_locked(serato_dir)
    return locked


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _ensure_serato_library_tree(con: sqlite3.Connection) -> int:
    """Zwraca id kontenera MyLists w space Serato Library (tworzy VDJ/MyLists jeśli brak)."""
    now = int(time.time())
    root = con.execute(
        "SELECT id FROM container WHERE space_id=? AND type=0 AND name=? LIMIT 1",
        (SPACE_SERATO_LIBRARY, "Serato Library root"),
    ).fetchone()
    if not root:
        cur = con.execute(
            "INSERT INTO container (revision, parent_id, name, type, list_order, space_id, time_added, expanded, portable_id, color) "
            "VALUES (1, 0, ?, 0, 1, ?, ?, 0, '', NULL)",
            ("Serato Library root", SPACE_SERATO_LIBRARY, now),
        )
        root_id = cur.lastrowid
    else:
        root_id = root[0]

    def child(parent_id: int, name: str) -> int:
        row = con.execute(
            "SELECT id FROM container WHERE parent_id=? AND name=? LIMIT 1",
            (parent_id, name),
        ).fetchone()
        if row:
            return row[0]
        order = con.execute(
            "SELECT COALESCE(MAX(list_order),0)+1 FROM container WHERE parent_id=?",
            (parent_id,),
        ).fetchone()[0]
        cur = con.execute(
            "INSERT INTO container (revision, parent_id, name, type, list_order, space_id, time_added, expanded, portable_id, color) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, 1, '', NULL)",
            (parent_id, name, CONTAINER_TYPE_CRATE, order, SPACE_SERATO_LIBRARY, now),
        )
        return cur.lastrowid

    vdj_id = child(root_id, "VDJ")
    return child(vdj_id, "MyLists")


def _ensure_container_path(con: sqlite3.Connection, mylists_id: int, parts: list[str]) -> int:
    """MyLists / a / b / c → id liścia."""
    parent = mylists_id
    now = int(time.time())
    for name in parts:
        name = (name or "").strip()
        if not name:
            continue
        row = con.execute(
            "SELECT id FROM container WHERE parent_id=? AND name=? LIMIT 1",
            (parent, name),
        ).fetchone()
        if row:
            parent = row[0]
            continue
        order = con.execute(
            "SELECT COALESCE(MAX(list_order),0)+1 FROM container WHERE parent_id=?",
            (parent,),
        ).fetchone()[0]
        cur = con.execute(
            "INSERT INTO container (revision, parent_id, name, type, list_order, space_id, time_added, expanded, portable_id, color) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, 1, '', NULL)",
            (parent, name, CONTAINER_TYPE_CRATE, order, SPACE_SERATO_LIBRARY, now),
        )
        parent = cur.lastrowid
    return parent


def _crate_stem_to_parts(stem: str) -> list[str]:
    """
    VDJ%%MyLists%%wesele bez DP → ['wesele bez DP']
    MyLists%%18 07 26 wesele%%pierwszy taniec → ['18 07 26 wesele', 'pierwszy taniec']
    """
    s = (stem or "").strip()
    if s.startswith("VDJ%%"):
        s = s[len("VDJ%%") :]
    parts = [p for p in s.split("%%") if p]
    if parts and parts[0] == "MyLists":
        parts = parts[1:]
    return parts


def _upsert_tidal_asset(
    con: sqlite3.Connection,
    tid: str,
    *,
    title: str = "",
    artist: str = "",
    bpm: float = 0.0,
    key: str = "",
    length_sec: float = 0.0,
) -> int:
    portable = f"streaming://tidal/{tid}"
    now = int(time.time())
    row = con.execute(
        "SELECT id FROM asset WHERE portable_id=? COLLATE NOCASE LIMIT 1",
        (portable,),
    ).fetchone()
    title_in = (title or "").strip()
    artist_in = (artist or "").strip()
    length_ms = int(length_sec * 1000) if length_sec and length_sec > 0 else None
    if row:
        aid = row[0]
        sets = ["revision=revision+1", "time_modified=?"]
        params: list = [now]
        if title_in and not is_tidal_placeholder_name(title_in, tid):
            sets.append("name=?")
            params.append(title_in)
        if artist_in:
            sets.append("artist=?")
            params.append(artist_in)
        if bpm > 0:
            sets.append("bpm=?")
            params.append(bpm)
        if key:
            sets.append("key=?")
            params.append(key)
        if length_ms is not None:
            sets.extend(["length_ms=?", "length_sec=?"])
            params.extend([length_ms, int(length_sec) if length_sec else None])
        params.append(aid)
        con.execute(
            f"UPDATE asset SET {', '.join(sets)} WHERE id=?",
            params,
        )
        return aid

    title = title_in if title_in and not is_tidal_placeholder_name(title_in, tid) else f"Tidal {tid}"
    artist = artist_in
    cur = con.execute(
        "INSERT INTO asset (revision, portable_id, file_name, type, format, artist, name, "
        "album, year, bpm, key, length_sec, length_ms, time_added, time_modified, "
        "third_party_type, type_specific_data) "
        "VALUES (1, ?, ?, 'audio', 'streaming', ?, ?, '', '', ?, ?, ?, ?, ?, ?, 3, "
        "'{\"is_video\":false,\"status\":0,\"is_available\":true}')",
        (
            portable,
            portable,
            artist,
            title,
            bpm if bpm > 0 else None,
            key or "",
            int(length_sec) if length_sec else None,
            length_ms,
            now,
            now,
        ),
    )
    return cur.lastrowid


def _ensure_space_asset(con: sqlite3.Connection, asset_id: int) -> int:
    row = con.execute(
        "SELECT id FROM space_asset WHERE asset_id=? AND space_id=? LIMIT 1",
        (asset_id, SPACE_SERATO_LIBRARY),
    ).fetchone()
    if row:
        return row[0]
    cur = con.execute(
        "INSERT INTO space_asset (asset_id, space_id) VALUES (?, ?)",
        (asset_id, SPACE_SERATO_LIBRARY),
    )
    return cur.lastrowid


def _link_container_asset(
    con: sqlite3.Connection,
    container_id: int,
    space_asset_id: int,
    list_order: int,
) -> bool:
    """True jeśli dodano nowy link."""
    exists = con.execute(
        "SELECT id FROM container_asset WHERE container_id=? AND space_asset_id=? LIMIT 1",
        (container_id, space_asset_id),
    ).fetchone()
    if exists:
        return False
    now = int(time.time())
    con.execute(
        "INSERT INTO container_asset (revision, container_id, space_asset_id, list_order, time_added) "
        "VALUES (1, ?, ?, ?, ?)",
        (container_id, space_asset_id, list_order, now),
    )
    return True


def _ensure_serato_library_roots(con: sqlite3.Connection) -> int:
    """Zwraca id kontenera MyLists (jedyno drzewo docelowe)."""
    now = int(time.time())
    root = con.execute(
        "SELECT id FROM container WHERE space_id=? AND type=0 AND name=? LIMIT 1",
        (SPACE_SERATO_LIBRARY, "Serato Library root"),
    ).fetchone()
    if not root:
        cur = con.execute(
            "INSERT INTO container (revision, parent_id, name, type, list_order, space_id, time_added, expanded, portable_id, color) "
            "VALUES (1, 0, ?, 0, 1, ?, ?, 0, '', NULL)",
            ("Serato Library root", SPACE_SERATO_LIBRARY, now),
        )
        root_id = cur.lastrowid
    else:
        root_id = root[0]

    def child(parent_id: int, name: str) -> int:
        row = con.execute(
            "SELECT id FROM container WHERE parent_id=? AND name=? LIMIT 1",
            (parent_id, name),
        ).fetchone()
        if row:
            return row[0]
        order = con.execute(
            "SELECT COALESCE(MAX(list_order),0)+1 FROM container WHERE parent_id=?",
            (parent_id,),
        ).fetchone()[0]
        cur = con.execute(
            "INSERT INTO container (revision, parent_id, name, type, list_order, space_id, time_added, expanded, portable_id, color) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, 1, '', NULL)",
            (parent_id, name, CONTAINER_TYPE_CRATE, order, SPACE_SERATO_LIBRARY, now),
        )
        return cur.lastrowid

    return child(root_id, "MyLists")


def _crate_stem_variants(stem: str) -> list[list[str]]:
    """Ścieżki względem MyLists (bez segmentu MyLists)."""
    parts = _crate_stem_to_parts(stem)
    return [parts] if parts else []


def _find_master_container(con: sqlite3.Connection, path_names: list[str]) -> Optional[int]:
    """Znajdź kontener po ścieżce nazw od root (space Serato Library w master = zwykle 5)."""
    # Preferuj space „Serato Library”
    spaces = [
        r[0]
        for r in con.execute("SELECT id FROM space WHERE name='Serato Library'")
    ]
    roots = []
    for sid in spaces or [None]:
        q = "SELECT id FROM container WHERE parent_id=0 OR parent_id IS NULL"
        args: tuple = ()
        if sid is not None:
            q = "SELECT id FROM container WHERE (parent_id=0 OR parent_id IS NULL) AND space_id=?"
            args = (sid,)
        roots.extend(r[0] for r in con.execute(q, args))
    # też „Serato Library root”
    for r in con.execute(
        "SELECT id FROM container WHERE name='Serato Library root'"
    ):
        roots.append(r[0])
    roots = list(dict.fromkeys(roots))

    for root_id in roots:
        parent = root_id
        ok = True
        for name in path_names:
            row = con.execute(
                "SELECT id FROM container WHERE parent_id=? AND name=? LIMIT 1",
                (parent, name),
            ).fetchone()
            if not row:
                ok = False
                break
            parent = row[0]
        if ok and path_names:
            return parent
    return None


def _ensure_master_container_path(con: sqlite3.Connection, path_names: list[str]) -> Optional[int]:
    """Tworzy brakującą ścieżkę kontenerów w master (space Serato Library)."""
    if not path_names:
        return None
    now = int(time.time())
    space = con.execute("SELECT id FROM space WHERE name='Serato Library' LIMIT 1").fetchone()
    space_id = space[0] if space else 5
    root = con.execute(
        "SELECT id FROM container WHERE name='Serato Library root' AND space_id=? LIMIT 1",
        (space_id,),
    ).fetchone()
    if not root:
        root = con.execute(
            "SELECT id FROM container WHERE name='Serato Library root' LIMIT 1"
        ).fetchone()
    if not root:
        return None
    parent = root[0]
    for name in path_names:
        row = con.execute(
            "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE LIMIT 1",
            (parent, name),
        ).fetchone()
        if row:
            parent = row[0]
            continue
        order = con.execute(
            "SELECT COALESCE(MAX(list_order),0)+1 FROM container WHERE parent_id=?",
            (parent,),
        ).fetchone()[0]
        try:
            cur = con.execute(
                "INSERT INTO container (parent_id, name, type, list_order, space_id, time_added, expanded, portable_id, color) "
                "VALUES (?,?,1,?,?,?,1,'',NULL)",
                (parent, name, order, space_id, now),
            )
            parent = cur.lastrowid
        except sqlite3.IntegrityError:
            row = con.execute(
                "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE LIMIT 1",
                (parent, name),
            ).fetchone()
            if not row:
                raise
            parent = row[0]
    return parent


def _find_master_containers(con: sqlite3.Connection, path_names: list[str]) -> list[int]:
    """
    Znajdź lub utwórz kontener master dokładnie pod path_names.
    Nie wolno mapować MyLists ↔ VDJ/MyLists — każde drzewo ma osobny kontener
    i osobne location_container (root + tidal).
    """
    if not path_names:
        return []
    one = _find_master_container(con, path_names)
    if one:
        return [one]
    created = _ensure_master_container_path(con, path_names)
    return [created] if created else []


def _link_master_to_tidal_containers(
    master_db: Path,
    links: list[tuple[list[str], int]],
) -> dict:
    """
    links: [(['MyLists','wesele bez DP'], tidal_container_id), …]
    Dopina location_container (location_id=2 = tidal.sqlite) w master.sqlite.
    """
    if not master_db.is_file() or not links:
        return {"ok": True, "linked": 0, "skipped": 0}
    now = int(time.time())
    linked = 0
    skipped = 0
    try:
        con = sqlite3.connect(str(master_db), timeout=10)
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e), "linked": 0}

    loc_row = con.execute("SELECT id FROM location ORDER BY id").fetchall()
    tidal_location_id = 2
    if len(loc_row) >= 2:
        tidal_location_id = loc_row[1][0]
    elif loc_row:
        tidal_location_id = loc_row[0][0]

    try:
        con.execute("BEGIN IMMEDIATE")
        for path_names, tidal_cid in links:
            mids = _find_master_containers(con, path_names)
            if not mids:
                skipped += 1
                continue
            mid = mids[0]
            # Czy ten tidal_cid jest już przypięty do innego master?
            taken = con.execute(
                "SELECT container_id FROM location_container "
                "WHERE location_id=? AND external_container_id=?",
                (tidal_location_id, tidal_cid),
            ).fetchone()
            if taken and taken[0] != mid:
                # tidal cid zajęty — zaktualizuj istniejący link master→tidal jeśli jest
                existing = con.execute(
                    "SELECT id FROM location_container WHERE container_id=? AND location_id=?",
                    (mid, tidal_location_id),
                ).fetchone()
                if existing:
                    # nie ruszaj external jeśli zajęty — zostaw
                    skipped += 1
                    continue
                skipped += 1
                continue
            existing = con.execute(
                "SELECT id, external_container_id FROM location_container "
                "WHERE container_id=? AND location_id=?",
                (mid, tidal_location_id),
            ).fetchone()
            if existing:
                if existing[1] != tidal_cid and not taken:
                    con.execute(
                        "UPDATE location_container SET external_container_id=? WHERE id=?",
                        (tidal_cid, existing[0]),
                    )
                    linked += 1
                else:
                    linked += 1  # już OK
            else:
                con.execute(
                    "INSERT INTO location_container (container_id, location_id, external_container_id) "
                    "VALUES (?,?,?)",
                    (mid, tidal_location_id, tidal_cid),
                )
                linked += 1
        con.execute(
            "UPDATE location SET revision=revision+1, last_sync_time=? WHERE id=?",
            (now, tidal_location_id),
        )
        con.commit()
    except sqlite3.Error as e:
        con.rollback()
        con.close()
        return {"ok": False, "error": str(e), "linked": linked, "skipped": skipped}
    con.close()
    return {"ok": True, "linked": linked, "skipped": skipped, "location_id": tidal_location_id}


def _portable_id_from_local_path(path: str) -> str:
    """Ścieżka lokalna → portable_id Serato (Users/… bez wiodącego /)."""
    s = (path or "").strip().replace("\\", "/")
    if s.startswith("file://"):
        s = s[7:]
    if len(s) >= 3 and s[1] == ":":
        s = s[2:].lstrip("/")
    while s.startswith("/"):
        s = s[1:]
    return s


def update_local_asset_rating(
    file_path: str,
    stars: int,
    *,
    comment: Optional[str] = None,
    library_dir: Optional[Path] = None,
) -> dict:
    """
    Ustawia asset.rating w root.sqlite (0.0–1.0 = stars/5) i czyści comments z hacka Rating:.
    Serato pokazuje ★ z tagów pliku + tego pola — trzeba oba.
    """
    from tag_writer import strip_rating_hack_from_comment

    stars = int(stars or 0)
    if stars < 0:
        stars = 0
    if stars > 5:
        stars = 5
    pid = _portable_id_from_local_path(file_path)
    if not pid:
        return {"ok": False, "reason": "bad_path"}
    lib = _library_dir(library_dir)
    db_path = lib / "root.sqlite"
    if not db_path.is_file():
        return {"ok": False, "reason": "no_root_sqlite"}
    rating_f = (stars / 5.0) if stars > 0 else None
    clean_cmt = strip_rating_hack_from_comment(comment) if comment is not None else None
    try:
        con = sqlite3.connect(str(db_path), timeout=10)
    except sqlite3.Error as e:
        return {"ok": False, "reason": str(e)}
    try:
        row = con.execute(
            "SELECT id, comments FROM asset WHERE portable_id=? COLLATE NOCASE "
            "OR file_name=? LIMIT 1",
            (pid, Path(file_path).name),
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "asset_not_found"}
        aid, old_cmt = row[0], row[1]
        if clean_cmt is None:
            clean_cmt = strip_rating_hack_from_comment(old_cmt or "")
        if rating_f is not None:
            con.execute(
                "UPDATE asset SET revision=revision+1, rating=?, comments=? WHERE id=?",
                (rating_f, clean_cmt, aid),
            )
        else:
            con.execute(
                "UPDATE asset SET revision=revision+1, comments=? WHERE id=?",
                (clean_cmt, aid),
            )
        con.commit()
        return {"ok": True, "asset_id": aid, "rating": rating_f}
    except sqlite3.Error as e:
        return {"ok": False, "reason": str(e)}
    finally:
        con.close()


def _root_space_id(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT id FROM space WHERE name='Serato Library' COLLATE NOCASE LIMIT 1"
    ).fetchone()
    return row[0] if row else 3


def _ensure_child_container(
    con: sqlite3.Connection,
    parent_id: int,
    name: str,
    *,
    space_id: int,
    container_type: int = CONTAINER_TYPE_CRATE,
) -> int:
    """Znajdź lub utwórz dziecko; odporne na UNIQUE(parent_id, name, type)."""
    name = (name or "").strip()
    row = con.execute(
        "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE LIMIT 1",
        (parent_id, name),
    ).fetchone()
    if row:
        return row[0]
    now = int(time.time())
    order = con.execute(
        "SELECT COALESCE(MAX(list_order),0)+1 FROM container WHERE parent_id=?",
        (parent_id,),
    ).fetchone()[0]
    try:
        cur = con.execute(
            "INSERT INTO container (revision, parent_id, name, type, list_order, space_id, time_added, expanded, portable_id, color) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, 1, '', NULL)",
            (parent_id, name, container_type, order, space_id, now),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        row = con.execute(
            "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE LIMIT 1",
            (parent_id, name),
        ).fetchone()
        if row:
            return row[0]
        raise


def _ensure_root_library_roots(con: sqlite3.Connection) -> int:
    """MyLists w root.sqlite (space_id zwykle 3)."""
    space_id = _root_space_id(con)
    now = int(time.time())
    root = con.execute(
        "SELECT id FROM container WHERE space_id=? AND type=0 AND name=? LIMIT 1",
        (space_id, "Serato Library root"),
    ).fetchone()
    if not root:
        cur = con.execute(
            "INSERT INTO container (revision, parent_id, name, type, list_order, space_id, time_added, expanded, portable_id, color) "
            "VALUES (1, 0, ?, 0, 1, ?, ?, 0, '', NULL)",
            ("Serato Library root", space_id, now),
        )
        root_id = cur.lastrowid
    else:
        root_id = root[0]
    return _ensure_child_container(con, root_id, "MyLists", space_id=space_id)


def _ensure_root_container_path(
    con: sqlite3.Connection, parent_id: int, parts: list[str]
) -> int:
    space_id = _root_space_id(con)
    parent = parent_id
    for name in parts:
        name = (name or "").strip()
        if not name:
            continue
        parent = _ensure_child_container(con, parent, name, space_id=space_id)
    return parent


def _ensure_root_container_path_chain(
    con: sqlite3.Connection,
    parent_id: int,
    path_prefix: list[str],
    parts: list[str],
) -> list[tuple[list[str], int]]:
    """
    Tworzy ścieżkę parts pod parent_id.
    Zwraca [(pełna_ścieżka_nazw, container_id), …] dla każdego poziomu (w tym liść),
    żeby master dostał location_id=1 także dla folderów nadrzędnych.
    """
    space_id = _root_space_id(con)
    parent = parent_id
    chain: list[tuple[list[str], int]] = []
    acc = list(path_prefix)
    for name in parts:
        name = (name or "").strip()
        if not name:
            continue
        parent = _ensure_child_container(con, parent, name, space_id=space_id)
        acc = acc + [name]
        chain.append((list(acc), parent))
    return chain


def _find_or_create_local_asset(con: sqlite3.Connection, portable_id: str) -> int:
    """Znajdź asset lokalny po portable_id; jeśli brak — minimalny wpis (Serato uzupełni metadane)."""
    row = con.execute(
        "SELECT id FROM asset WHERE portable_id=? COLLATE NOCASE LIMIT 1",
        (portable_id,),
    ).fetchone()
    if row:
        return row[0]
    now = int(time.time())
    name = Path(portable_id).name
    stem = Path(name).stem
    fmt = Path(name).suffix.lstrip(".").lower() or "m4a"
    abs_path = Path("/") / portable_id
    size = abs_path.stat().st_size if abs_path.is_file() else None
    cur = con.execute(
        "INSERT INTO asset (revision, portable_id, file_name, file_size, type, format, "
        "artist, name, album, time_added, time_modified, third_party_type, is_missing) "
        "VALUES (1, ?, ?, ?, 'audio', ?, '', ?, '', ?, ?, 0, 0)",
        (portable_id, name, size, fmt, stem, now, now),
    )
    return cur.lastrowid


def _ensure_root_space_asset(con: sqlite3.Connection, asset_id: int) -> int:
    space_id = _root_space_id(con)
    row = con.execute(
        "SELECT id FROM space_asset WHERE asset_id=? AND space_id=? LIMIT 1",
        (asset_id, space_id),
    ).fetchone()
    if row:
        return row[0]
    cur = con.execute(
        "INSERT INTO space_asset (asset_id, space_id) VALUES (?, ?)",
        (asset_id, space_id),
    )
    return cur.lastrowid


def _link_master_to_root_containers(
    master_db: Path,
    links: list[tuple[list[str], int]],
) -> dict:
    """location_id=1 (root.sqlite) — analogicznie do Tidal."""
    if not master_db.is_file() or not links:
        return {"ok": True, "linked": 0, "skipped": 0}
    now = int(time.time())
    linked = 0
    skipped = 0
    try:
        con = sqlite3.connect(str(master_db), timeout=10)
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e), "linked": 0}

    root_location_id = 1
    try:
        con.execute("BEGIN IMMEDIATE")
        for path_names, root_cid in links:
            mids = _find_master_containers(con, path_names)
            if not mids:
                skipped += 1
                continue
            mid = mids[0]
            taken = con.execute(
                "SELECT container_id FROM location_container "
                "WHERE location_id=? AND external_container_id=?",
                (root_location_id, root_cid),
            ).fetchone()
            if taken and taken[0] != mid:
                skipped += 1
                continue
            existing = con.execute(
                "SELECT id, external_container_id FROM location_container "
                "WHERE container_id=? AND location_id=?",
                (mid, root_location_id),
            ).fetchone()
            if existing:
                if existing[1] != root_cid and not taken:
                    con.execute(
                        "UPDATE location_container SET external_container_id=? WHERE id=?",
                        (root_cid, existing[0]),
                    )
                    linked += 1
                else:
                    linked += 1
            else:
                con.execute(
                    "INSERT INTO location_container (container_id, location_id, external_container_id) "
                    "VALUES (?,?,?)",
                    (mid, root_location_id, root_cid),
                )
                linked += 1
        con.execute(
            "UPDATE location SET revision=revision+1, last_sync_time=? WHERE id=?",
            (now, root_location_id),
        )
        con.commit()
    except sqlite3.Error as e:
        con.rollback()
        con.close()
        return {"ok": False, "error": str(e), "linked": linked, "skipped": skipped}
    con.close()
    return {"ok": True, "linked": linked, "skipped": skipped, "location_id": root_location_id}


def install_local_tracks_into_root_library(
    prepared_entries: list[tuple[str, list[str]]],
    *,
    library_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> dict:
    """
    Lokalne NJR / pliki → root.sqlite pod MyLists/…
    + master.sqlite location_id=1.
    """
    lib = _library_dir(library_dir)
    db_path = lib / "root.sqlite"
    master_db = lib / "master.sqlite"
    if not db_path.is_file():
        return {"ok": False, "error": f"Brak {db_path}"}

    planned: list[tuple[str, list[str]]] = []
    total = 0
    for stem, paths in prepared_entries or []:
        parts = _crate_stem_to_parts(stem)
        if not parts:
            continue
        portables: list[str] = []
        seen: set[str] = set()
        for p in paths or []:
            if is_serato_tidal_path(p) or extract_tidal_id(p):
                continue
            pid = _portable_id_from_local_path(p)
            if not pid or pid in seen:
                continue
            seen.add(pid)
            portables.append(pid)
        if portables:
            planned.append((stem, portables))
            total += len(portables)

    result = {
        "ok": True,
        "dry_run": dry_run,
        "crates": len(planned),
        "tracks_requested": total,
        "assets_created": 0,
        "links_added": 0,
        "master_links": 0,
        "db": str(db_path),
    }
    if dry_run or not planned:
        return result

    try:
        con = sqlite3.connect(str(db_path), timeout=10)
    except sqlite3.Error as e:
        return {
            "ok": False,
            "error": f"Nie można otworzyć root.sqlite ({e}). Zamknij Serato (Cmd+Q).",
        }

    master_link_jobs: list[tuple[list[str], int]] = []
    created = 0
    linked = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        mylists_top = _ensure_root_library_roots(con)
        for stem, portables in planned:
            parts = _crate_stem_to_parts(stem)
            chain = _ensure_root_container_path_chain(
                con, mylists_top, ["MyLists"], parts
            )
            for full_path, cid in chain:
                master_link_jobs.append((full_path, cid))
            if not chain:
                continue
            leaf_cid = chain[-1][1]
            next_order = con.execute(
                "SELECT COALESCE(MAX(list_order),0) FROM container_asset WHERE container_id=?",
                (leaf_cid,),
            ).fetchone()[0]
            for pid in portables:
                existed = con.execute(
                    "SELECT id FROM asset WHERE portable_id=? COLLATE NOCASE",
                    (pid,),
                ).fetchone()
                aid = _find_or_create_local_asset(con, pid)
                if not existed:
                    created += 1
                sa_id = _ensure_root_space_asset(con, aid)
                next_order += 1
                if _link_container_asset(con, leaf_cid, sa_id, next_order):
                    linked += 1
            con.execute(
                "UPDATE container SET revision=revision+1 WHERE id=?",
                (leaf_cid,),
            )

        space_id = _root_space_id(con)
        con.execute(
            "UPDATE space SET revision=revision+1 WHERE id=?",
            (space_id,),
        )
        con.execute(
            "UPDATE master SET revision=revision+1, last_sync_time=?",
            (int(time.time()),),
        )
        con.commit()
        result["assets_created"] = created
        result["links_added"] = linked
    except sqlite3.Error as e:
        con.rollback()
        return {
            "ok": False,
            "error": f"Zapis root.sqlite nieudany: {e}. Zamknij Serato i ponów.",
        }
    finally:
        con.close()

    # dedupe (ta sama ścieżka folderu z wielu list)
    deduped: list[tuple[list[str], int]] = []
    seen_jobs: set[tuple[tuple[str, ...], int]] = set()
    for path_names, cid in master_link_jobs:
        key = (tuple(path_names), cid)
        if key in seen_jobs:
            continue
        seen_jobs.add(key)
        deduped.append((path_names, cid))

    master_stats = _link_master_to_root_containers(master_db, deduped)
    result["master_links"] = master_stats.get("linked", 0)
    result["master_skipped"] = master_stats.get("skipped", 0)
    if not master_stats.get("ok"):
        result["master_error"] = master_stats.get("error")
    return result


def _find_container_by_path(
    con: sqlite3.Connection,
    parts: list[str],
    *,
    mylists_name: str = "MyLists",
) -> Optional[int]:
    """MyLists / a / b → id liścia lub None."""
    rows = con.execute(
        "SELECT id FROM container WHERE name=? COLLATE NOCASE",
        (mylists_name,),
    ).fetchall()
    for (mid,) in rows:
        cid = mid
        ok = True
        for name in parts:
            row = con.execute(
                "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE LIMIT 1",
                (cid, name),
            ).fetchone()
            if not row:
                ok = False
                break
            cid = row[0]
        if ok:
            return cid
    return None


def _purge_master_location_containers_for_containers(
    con: sqlite3.Connection,
    container_ids: list[int],
) -> int:
    """
    Usuwa location_container (+ container_asset przez location_container_id)
    dla podanych kontenerów master. Wymagane przed DELETE container — Serato FK check.
    """
    if not container_ids:
        return 0
    qmarks = ",".join("?" * len(container_ids))
    lc_ids = [
        r[0]
        for r in con.execute(
            f"SELECT id FROM location_container WHERE container_id IN ({qmarks})",
            container_ids,
        )
    ]
    removed = 0
    if lc_ids:
        q2 = ",".join("?" * len(lc_ids))
        cur = con.execute(
            f"DELETE FROM container_asset WHERE location_container_id IN ({q2})",
            lc_ids,
        )
        removed += cur.rowcount or 0
        con.execute(
            f"DELETE FROM location_container WHERE id IN ({q2})",
            lc_ids,
        )
    cur = con.execute(
        f"DELETE FROM location_container WHERE container_id IN ({qmarks})",
        container_ids,
    )
    removed += cur.rowcount or 0
    for table in ("dj_container_metadata", "container_asset_list_columns"):
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone():
            cur = con.execute(
                f"DELETE FROM {table} WHERE container_id IN ({qmarks})",
                container_ids,
            )
            removed += cur.rowcount or 0
    return removed


def _normalize_portable_id_candidate(portable_id: str) -> str:
    """Poprawia typowe złe portable_id (podwójny prefix Music/Users)."""
    pid = (portable_id or "").strip().replace("\\", "/")
    while "Users/test/Music/Users/test/" in pid:
        pid = pid.replace("Users/test/Music/Users/test/", "Users/test/", 1)
    return pid


def _fix_legacy_portable_id_prefixes(portable_id: str) -> str:
    """Stary użytkownik / macOS → bieżący home (Users/inmos → Users/test)."""
    pid = (portable_id or "").strip().replace("\\", "/")
    home = Path.home()
    user = home.name
    pid = re.sub(r"^Users/inmos/", f"Users/{user}/", pid, flags=re.I)
    return pid


def _build_local_basename_index(search_roots: list[Path]) -> dict[str, list[str]]:
    """Indeks basename → portable_id (Serato relative) dla relocate po nazwie pliku."""
    from serato_parser import to_serato_relative_path

    audio = {".mp3", ".m4a", ".aiff", ".aif", ".wav", ".flac", ".aac", ".ogg"}
    index: dict[str, list[str]] = defaultdict(list)
    for root in search_roots:
        if not root.is_dir():
            continue
        try:
            for f in root.rglob("*"):
                if not f.is_file() or f.suffix.lower() not in audio:
                    continue
                rel = to_serato_relative_path(str(f.resolve()))
                key = f.name.lower()
                if rel not in index[key]:
                    index[key].append(rel)
        except OSError:
            continue
    return index


def _resolve_root_portable_id(
    portable_id: str,
    *,
    file_name: str = "",
    basename_index: Optional[dict[str, list[str]]] = None,
) -> tuple[str, bool]:
    """Zwraca (najlepsze portable_id, czy plik istnieje na dysku)."""
    from serato_parser import map_stale_serato_path_to_desktop, serato_path_exists_on_disk

    raw = _fix_legacy_portable_id_prefixes(portable_id)
    if not raw and file_name:
        raw = (file_name or "").strip().replace("\\", "/")
    if not raw:
        return raw, False
    candidates: list[str] = []
    seen: set[str] = set()

    def add(c: str) -> None:
        c = _fix_legacy_portable_id_prefixes(c)
        c = (c or "").strip().replace("\\", "/")
        if c and c not in seen:
            seen.add(c)
            candidates.append(c)

    add(raw)
    add(_normalize_portable_id_candidate(raw))
    mapped = map_stale_serato_path_to_desktop(raw)
    if mapped:
        add(mapped)
    for c in list(candidates):
        add(_normalize_portable_id_candidate(c))

    bname = (file_name or Path(raw).name or "").lower()
    if basename_index and bname:
        for rel in basename_index.get(bname, []):
            add(rel)

    stale = (
        re.compile(r"(?i)^(?:G:/)?Inne komputery/"),
        re.compile(r"(?i)^Volumes/"),
        re.compile(r"(?i)^G:/"),
        re.compile(r"(?i)^Users/test/Music/Users/"),
        re.compile(r"(?i)^Users/test/\.Trash/"),
    )

    def score(pid: str, exists: bool) -> int:
        s = 0
        if exists:
            s += 1_000_000
        if "/Desktop/muzyka dj/" in ("/" + pid):
            s += 50_000
        if pid.startswith("Users/test/Desktop/"):
            s += 10_000
        if any(p.search(pid) for p in stale):
            s -= 100_000
        return s

    ranked: list[tuple[int, str, bool]] = []
    for pid in candidates:
        exists = serato_path_exists_on_disk(pid)
        ranked.append((score(pid, exists), pid, exists))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if ranked:
        _, best, ok = ranked[0]
        return best, ok
    return raw, serato_path_exists_on_disk(raw)


def _ensure_space_asset_for_asset(con: sqlite3.Connection, asset_id: int) -> int:
    space_id = _root_space_id(con)
    row = con.execute(
        "SELECT id FROM space_asset WHERE asset_id=? AND space_id=? LIMIT 1",
        (asset_id, space_id),
    ).fetchone()
    if row:
        return row[0]
    cur = con.execute(
        "INSERT INTO space_asset (asset_id, space_id) VALUES (?, ?)",
        (asset_id, space_id),
    )
    return cur.lastrowid


def _merge_root_asset_into(
    con: sqlite3.Connection,
    *,
    loser_id: int,
    winner_id: int,
) -> dict:
    """Przenosi odwołania crate z duplikatu asset → zwycięzca, kasuje duplikat."""
    if loser_id == winner_id:
        return {"merged": False}
    loser_sa = con.execute(
        "SELECT id FROM space_asset WHERE asset_id=? LIMIT 1",
        (loser_id,),
    ).fetchone()
    winner_sa = _ensure_space_asset_for_asset(con, winner_id)
    moved = deleted = 0
    if loser_sa:
        loser_sa_id = loser_sa[0]
        for (ca_id, container_id) in con.execute(
            "SELECT id, container_id FROM container_asset WHERE space_asset_id=?",
            (loser_sa_id,),
        ):
            dup = con.execute(
                "SELECT id FROM container_asset WHERE container_id=? AND space_asset_id=? LIMIT 1",
                (container_id, winner_sa),
            ).fetchone()
            if dup:
                con.execute("DELETE FROM container_asset WHERE id=?", (ca_id,))
                deleted += 1
            else:
                con.execute(
                    "UPDATE container_asset SET space_asset_id=?, revision=revision+1 WHERE id=?",
                    (winner_sa, ca_id),
                )
                moved += 1
        con.execute("DELETE FROM space_asset WHERE id=?", (loser_sa_id,))
    con.execute("DELETE FROM dj_asset_metadata WHERE asset_id=?", (loser_id,))
    con.execute("DELETE FROM asset WHERE id=?", (loser_id,))
    return {"merged": True, "moved": moved, "deleted_ca": deleted}


def repair_root_sqlite_path_links(
    library_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Naprawia złe powiązania plików w root.sqlite (Serato 4+):
    - usuwa duplikaty (Inne komputery / G:/ / podwójny Users/…/Music/Users/…)
    - zostawia wpis wskazujący na istniejący plik (preferuj Desktop/muzyka dj)
    - przenosi odwołania w crate na zwycięzcę
    Serato musi być zamknięty.
    """
    lib = _library_dir(library_dir)
    db_path = lib / "root.sqlite"
    if not db_path.is_file():
        return {"ok": False, "error": f"Brak {db_path}"}

    try:
        con = sqlite3.connect(str(db_path), timeout=60)
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e)}

    stats = {
        "ok": True,
        "dry_run": dry_run,
        "groups": 0,
        "updated_paths": 0,
        "removed_duplicates": 0,
        "removed_orphans": 0,
        "reconciled_sizes": 0,
        "crate_refs_moved": 0,
        "crate_refs_deduped": 0,
        "still_missing": 0,
    }

    home = Path.home()
    search_roots = [
        home / "Desktop" / "muzyka dj",
        home / "Desktop",
        home / "Music",
        home / "Downloads",
    ]
    basename_index = _build_local_basename_index(search_roots)

    rows = con.execute(
        "SELECT id, portable_id, file_name, is_missing FROM asset "
        "WHERE file_name IS NOT NULL AND TRIM(file_name) != ''"
    ).fetchall()

    by_name: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        by_name[(row[2] or "").lower()].append(row)

    try:
        if not dry_run:
            con.execute("BEGIN IMMEDIATE")

        for _base, group in by_name.items():
            if len(group) <= 1:
                aid, pid, fname, missing = group[0]
                best, exists = _resolve_root_portable_id(
                    pid, file_name=fname, basename_index=basename_index
                )
                if best != pid or (exists and missing):
                    stats["groups"] += 1
                    if not dry_run:
                        size = None
                        if exists:
                            p = Path("/" + best) if not best.startswith("/") else Path(best)
                            try:
                                size = p.stat().st_size
                            except OSError:
                                pass
                        con.execute(
                            "UPDATE asset SET revision=revision+1, portable_id=?, is_missing=?, "
                            "file_size=COALESCE(?, file_size) WHERE id=?",
                            (best, 0 if exists else 1, size, aid),
                        )
                    stats["updated_paths"] += 1
                    if not exists:
                        stats["still_missing"] += 1
                continue

            stats["groups"] += 1
            resolved: list[tuple[int, str, str, bool, int]] = []
            for aid, pid, fname, missing in group:
                best, exists = _resolve_root_portable_id(
                    pid, file_name=fname, basename_index=basename_index
                )
                bonus = 0
                if exists and missing:
                    bonus += 5000
                resolved.append((aid, pid, best, exists, bonus))

            resolved.sort(
                key=lambda x: (
                    x[3],
                    x[4],
                    0 if x[2].startswith("Users/test/Desktop/") else 1,
                    -x[0],
                ),
                reverse=True,
            )
            winner_id, winner_pid, winner_best, winner_exists, _ = resolved[0]
            losers = resolved[1:]

            # Najpierw scal duplikaty (unikaj UNIQUE na portable_id przy UPDATE).
            for loser_id, _lpid, _lbest, _lex, _ in losers:
                if not dry_run:
                    m = _merge_root_asset_into(con, loser_id=loser_id, winner_id=winner_id)
                    stats["crate_refs_moved"] += m.get("moved", 0)
                    stats["crate_refs_deduped"] += m.get("deleted_ca", 0)
                stats["removed_duplicates"] += 1

            if winner_best != winner_pid or winner_exists:
                if not dry_run:
                    clash = con.execute(
                        "SELECT id FROM asset WHERE portable_id=? COLLATE NOCASE AND id!=? LIMIT 1",
                        (winner_best, winner_id),
                    ).fetchone()
                    if clash:
                        other_id = clash[0]
                        m = _merge_root_asset_into(
                            con, loser_id=winner_id, winner_id=other_id
                        )
                        stats["crate_refs_moved"] += m.get("moved", 0)
                        stats["crate_refs_deduped"] += m.get("deleted_ca", 0)
                        stats["removed_duplicates"] += 1
                        winner_id = other_id
                        winner_pid = winner_best
                    else:
                        size = None
                        if winner_exists:
                            p = (
                                Path("/" + winner_best)
                                if not winner_best.startswith("/")
                                else Path(winner_best)
                            )
                            try:
                                size = p.stat().st_size
                            except OSError:
                                pass
                        con.execute(
                            "UPDATE asset SET revision=revision+1, portable_id=?, is_missing=?, "
                            "file_size=COALESCE(?, file_size) WHERE id=?",
                            (winner_best, 0 if winner_exists else 1, size, winner_id),
                        )
                        stats["updated_paths"] += 1

            if not winner_exists:
                stats["still_missing"] += 1

        if not dry_run:
            now = int(time.time())
            try:
                con.execute(
                    "UPDATE master SET revision=revision+1, last_sync_time=?",
                    (now,),
                )
            except sqlite3.Error:
                pass
            con.commit()
        else:
            con.rollback()
    except sqlite3.Error as e:
        if not dry_run:
            con.rollback()
        return {"ok": False, "error": str(e), **stats}
    finally:
        con.close()

    return stats


def repair_database_v2_paths(
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Usuwa martwe / zduplikowane otrk z database V2 (Serato legacy blob).
    Serato musi być zamknięty.
    """
    from datetime import datetime

    from serato_parser import purge_serato_stale_duplicates

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    db_file = base / "database V2"
    if not db_file.is_file():
        return {"ok": False, "error": f"Brak {db_file}"}
    raw = db_file.read_bytes()
    cleaned, st = purge_serato_stale_duplicates(raw)
    stats = {"ok": True, "dry_run": dry_run, **st}
    if dry_run:
        return stats
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = Path(str(db_file) + f".pre-repair-{ts}.bak")
    bak.write_bytes(raw)
    db_file.write_bytes(cleaned)
    stats["backup"] = str(bak)
    return stats


def repair_tidal_sqlite_metadata(
    library_dir: Optional[Path] = None,
    serato_dir: Optional[Path] = None,
    *,
    vdj_database: Optional[Path] = None,
    dry_run: bool = False,
) -> dict:
    """
    Naprawia wpisy Tidal w tidal.sqlite z nazwą „Tidal 12345” → tytuł/wykonawca.
    Źródła: ~/Music/_Serato_/Metadata/Tidal/{id}.xml, potem VDJ database.xml.
    Serato musi być zamknięty.
    """
    from serato_parser import _song_bpm_display
    from tidal_vdj_metadata import find_vdj_song_for_tidal_id
    from vdj_parser import load_database
    from vdj_streaming import extract_tidal_id

    lib = _library_dir(library_dir)
    db_path = lib / "tidal.sqlite"
    if not db_path.is_file():
        return {"ok": False, "error": f"Brak {db_path}"}

    meta_dir = (Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_") / "Metadata" / "Tidal"
    vdj_path = vdj_database or (Path.home() / "Library/Application Support/VirtualDJ/database.xml")
    songs: list[dict] = []
    if vdj_path.is_file():
        try:
            songs, _ = load_database(vdj_path)
        except Exception:
            songs = []

    def _read_ssl_xml(tid: str) -> dict:
        return _read_serato_tidal_ssl_xml(meta_dir, tid)

    tidal_name_re = TIDAL_PLACEHOLDER_RE
    try:
        con = sqlite3.connect(str(db_path), timeout=60)
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e)}

    stats = {
        "ok": True,
        "dry_run": dry_run,
        "candidates": 0,
        "updated": 0,
        "from_xml": 0,
        "from_vdj": 0,
        "still_placeholder": 0,
    }

    rows = con.execute(
        "SELECT id, portable_id, name, artist FROM asset WHERE portable_id LIKE 'streaming://tidal/%'"
    ).fetchall()

    try:
        if not dry_run:
            con.execute("BEGIN IMMEDIATE")
        now = int(time.time())
        for aid, portable, name, artist in rows:
            tid = extract_tidal_id(portable or "")
            if not tid:
                continue
            nm = (name or "").strip()
            ar = (artist or "").strip()
            if not tidal_name_re.match(nm) and nm and ar:
                continue
            stats["candidates"] += 1
            meta = _read_ssl_xml(tid)
            if tidal_name_re.match((meta.get("name") or "").strip()):
                meta.pop("name", None)
                meta.pop("artist", None)
            source = "xml" if meta.get("name") else ""
            if not meta.get("name"):
                song = find_vdj_song_for_tidal_id(tid, songs)
                if song:
                    meta["name"] = (song.get("Tags.Title") or song.get("Tags.Name") or "").strip()
                    meta["artist"] = (song.get("Tags.Artist") or song.get("Tags.Author") or "").strip()
                    meta["album"] = (song.get("Tags.Album") or "").strip()
                    meta["key"] = (song.get("Tags.Key") or "").strip()
                    bpm = _song_bpm_display(song)
                    if bpm > 0:
                        meta["bpm"] = bpm
                    length = float(song.get("Infos.SongLength") or 0)
                    if length > 0:
                        meta["length_sec"] = length
                    source = "vdj"
            title = (meta.get("name") or "").strip()
            artist_new = (meta.get("artist") or "").strip()
            if not title or tidal_name_re.match(title):
                stats["still_placeholder"] += 1
                continue
            if not dry_run:
                bpm = float(meta.get("bpm") or 0)
                key = (meta.get("key") or "").strip()
                length_sec = float(meta.get("length_sec") or 0)
                length_ms = int(length_sec * 1000) if length_sec > 0 else None
                album = (meta.get("album") or "").strip()
                con.execute(
                    "UPDATE asset SET revision=revision+1, name=?, artist=?, album=?, "
                    "bpm=CASE WHEN ? > 0 THEN ? ELSE bpm END, "
                    "key=CASE WHEN ? != '' THEN ? ELSE key END, "
                    "length_sec=CASE WHEN ? IS NOT NULL THEN ? ELSE length_sec END, "
                    "length_ms=CASE WHEN ? IS NOT NULL THEN ? ELSE length_ms END, "
                    "time_modified=? WHERE id=?",
                    (
                        title,
                        artist_new,
                        album,
                        bpm,
                        bpm if bpm > 0 else None,
                        key,
                        key,
                        int(length_sec) if length_sec else None,
                        int(length_sec) if length_sec else None,
                        length_ms,
                        length_ms,
                        now,
                        aid,
                    ),
                )
            stats["updated"] += 1
            if source == "xml":
                stats["from_xml"] += 1
            elif source == "vdj":
                stats["from_vdj"] += 1
        if not dry_run:
            try:
                con.execute(
                    "UPDATE master SET revision=revision+1, last_sync_time=?",
                    (now,),
                )
            except sqlite3.Error:
                pass
            con.commit()
        else:
            con.rollback()
    except sqlite3.Error as e:
        if not dry_run:
            con.rollback()
        return {"ok": False, "error": str(e), **stats}
    finally:
        con.close()
    return stats


def resolve_tidal_metadata_for_install(
    tidal_id: str,
    tidal_meta: Optional[dict[str, dict]] = None,
    songs: Optional[list[dict]] = None,
    *,
    serato_dir: Optional[Path] = None,
) -> dict:
    """
    Pełne metadane Tidal do zapisu w tidal.sqlite / Metadata XML.
    Kolejność: tidal_meta (vdjfolder) → VDJ database → istniejący SSL XML (jeśli nie placeholder).
    Nigdy nie zwraca pustego tytułu bez próby VDJ/XML.
    """
    from tidal_vdj_metadata import find_vdj_song_for_tidal_id

    tid = str(tidal_id or "").strip()
    if not tid:
        return {}
    meta_dir = (Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_") / "Metadata" / "Tidal"
    out: dict = dict((tidal_meta or {}).get(tid) or {})

    def _apply_song(song: dict) -> None:
        if not song:
            return
        title = (song.get("Tags.Title") or song.get("Tags.Name") or "").strip()
        artist = (song.get("Tags.Author") or song.get("Tags.Artist") or "").strip()
        if title and not is_tidal_placeholder_name(title, tid):
            out["Tags.Title"] = title
        if artist:
            out["Tags.Author"] = artist
        if song.get("Tags.Album"):
            out["Tags.Album"] = song.get("Tags.Album")
        if song.get("Tags.Key"):
            out["Tags.Key"] = song.get("Tags.Key")
        if song.get("Tags.Bpm"):
            out["Tags.Bpm"] = song.get("Tags.Bpm")
        if song.get("Infos.SongLength"):
            out["Infos.SongLength"] = song.get("Infos.SongLength")

    title = (out.get("Tags.Title") or out.get("Tags.Name") or "").strip()
    if is_tidal_placeholder_name(title, tid) or not title:
        song = find_vdj_song_for_tidal_id(tid, songs or [])
        _apply_song(song or {})

    title = (out.get("Tags.Title") or out.get("Tags.Name") or "").strip()
    if is_tidal_placeholder_name(title, tid) or not title:
        xml = _read_serato_tidal_ssl_xml(meta_dir, tid)
        if xml.get("name") and not is_tidal_placeholder_name(xml["name"], tid):
            out["Tags.Title"] = xml["name"]
        if xml.get("artist"):
            out["Tags.Author"] = xml["artist"]
        if xml.get("album"):
            out["Tags.Album"] = xml["album"]
        if xml.get("key"):
            out["Tags.Key"] = xml["key"]
        if xml.get("bpm"):
            out["Tags.Bpm"] = xml["bpm"]
        if xml.get("length_sec"):
            out["Infos.SongLength"] = xml["length_sec"]

    return out


def finalize_serato_sqlite_after_install(
    *,
    library_dir: Optional[Path] = None,
    serato_dir: Optional[Path] = None,
    songs: Optional[list[dict]] = None,
    dry_run: bool = False,
) -> dict:
    """
    Bezpieczna finalizacja po instalacji VDJ → Serato (Serato zamknięte):
    - metadane Tidal w tidal.sqlite
    - deduplikacja ścieżek root.sqlite (bez kasowania orphanów / bez database V2)
    - naprawa FK master.sqlite
    """
    tidal = repair_tidal_sqlite_metadata(
        library_dir=library_dir,
        serato_dir=serato_dir,
        dry_run=dry_run,
    )
    root = repair_root_sqlite_path_links(library_dir=library_dir, dry_run=dry_run)
    master = repair_master_sqlite_foreign_keys(library_dir=library_dir)
    ok = bool(tidal.get("ok")) and bool(root.get("ok")) and bool(master.get("ok"))
    return {
        "ok": ok,
        "tidal_metadata": tidal,
        "root_paths": root,
        "master_fk": master,
    }


def repair_serato_library_paths(
    *,
    library_dir: Optional[Path] = None,
    serato_dir: Optional[Path] = None,
    dry_run: bool = False,
    include_database_v2: bool = False,
) -> dict:
    """
    Naprawa powiązań plików w root.sqlite.
    database V2 domyślnie NIE jest modyfikowane — Serato synchronizuje obie bazy
    przy starcie; równoległa edycja powoduje UNIQUE constraint / import failed.
    """
    root_stats = repair_root_sqlite_path_links(library_dir, dry_run=dry_run)
    v2_stats = {"ok": True, "skipped": True}
    if include_database_v2:
        v2_stats = repair_database_v2_paths(serato_dir, dry_run=dry_run)
    ok = bool(root_stats.get("ok")) and bool(v2_stats.get("ok"))
    return {"ok": ok, "root_sqlite": root_stats, "database_v2": v2_stats}


def verify_master_sqlite_foreign_keys(
    library_dir: Optional[Path] = None,
) -> dict:
    """Sprawdza FK master.sqlite (to samo co Serato przy starcie)."""
    master_db = _library_dir(library_dir) / "master.sqlite"
    if not master_db.is_file():
        return {"ok": False, "error": f"Brak {master_db}"}
    try:
        con = sqlite3.connect(str(master_db), timeout=10)
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e)}
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()
        fk_rows = list(con.execute("PRAGMA foreign_key_check"))
        orphan_ca = con.execute(
            """
            SELECT COUNT(*) FROM container_asset ca
            LEFT JOIN location_container lc ON lc.id = ca.location_container_id
            WHERE ca.location_container_id IS NOT NULL AND lc.id IS NULL
            """
        ).fetchone()[0]
        return {
            "ok": integrity and integrity[0] == "ok" and not fk_rows and orphan_ca == 0,
            "integrity": integrity[0] if integrity else "",
            "fk_violations": len(fk_rows),
            "orphan_container_asset": orphan_ca,
            "fk_samples": fk_rows[:5],
        }
    finally:
        con.close()


def repair_master_sqlite_foreign_keys(
    library_dir: Optional[Path] = None,
    *,
    remove_marker: bool = True,
) -> dict:
    """
    Naprawia typowe uszkodzenia FK w master.sqlite (container_asset → location_container).
    Wywoływane automatycznie po instalacji VDJ → Serato.
    """
    lib = _library_dir(library_dir)
    master_db = lib / "master.sqlite"
    marker = lib / "master.sqlite.failed_integrity_check"
    if not master_db.is_file():
        return {"ok": False, "error": f"Brak {master_db}"}
    try:
        con = sqlite3.connect(str(master_db), timeout=30)
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e)}
    removed = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        orphans = con.execute(
            """
            SELECT COUNT(*) FROM container_asset ca
            LEFT JOIN location_container lc ON lc.id = ca.location_container_id
            WHERE ca.location_container_id IS NOT NULL AND lc.id IS NULL
            """
        ).fetchone()[0]
        cur = con.execute(
            """
            DELETE FROM container_asset
            WHERE location_container_id IS NOT NULL
              AND location_container_id NOT IN (SELECT id FROM location_container)
            """
        )
        removed = cur.rowcount if cur.rowcount and cur.rowcount > 0 else orphans
        # container_asset.container_id → container (po kasowaniu kontenerów)
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='container_asset'"
        ).fetchone():
            cols = [r[1] for r in con.execute("PRAGMA table_info(container_asset)")]
            if "container_id" in cols:
                con.execute(
                    "DELETE FROM container_asset WHERE container_id NOT IN (SELECT id FROM container)"
                )
        for table in ("dj_container_metadata", "container_asset_list_columns"):
            if con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone():
                con.execute(
                    f"DELETE FROM {table} WHERE container_id NOT IN (SELECT id FROM container)"
                )
        now = int(time.time())
        for (lid,) in con.execute("SELECT id FROM location"):
            con.execute(
                "UPDATE location SET revision=revision+1, last_sync_time=? WHERE id=?",
                (now, lid),
            )
        con.commit()
    except sqlite3.Error as e:
        con.rollback()
        return {"ok": False, "error": str(e), "removed": removed}
    finally:
        con.close()

    if remove_marker and marker.is_file():
        try:
            marker.unlink()
        except OSError:
            pass

    verify = verify_master_sqlite_foreign_keys(library_dir)
    verify["removed_orphan_container_asset"] = removed
    return verify


def remove_orphan_flat_crate_containers(
    stem: str,
    *,
    library_dir: Optional[Path] = None,
) -> dict:
    """
    Usuwa płaskie duplikaty crate (np. MyLists/LINKI) gdy właściwa ścieżka jest zagnieżdżona
    (MyLists/kreatywne listy/LINKI). Naprawia pusty widok w Serato 4+.
    """
    lib = _library_dir(library_dir)
    parts = _crate_stem_to_parts(stem)
    if len(parts) < 2:
        return {"ok": True, "removed": 0}
    leaf = parts[-1]
    parent_name = parts[-2]
    removed: dict[str, list[int]] = {"root.sqlite": [], "tidal.sqlite": [], "master.sqlite": []}

    for db_name in ("root.sqlite", "tidal.sqlite"):
        db_path = lib / db_name
        if not db_path.is_file():
            continue
        try:
            con = sqlite3.connect(str(db_path), timeout=10)
        except sqlite3.Error:
            continue
        try:
            con.execute("BEGIN IMMEDIATE")
            mylists_rows = con.execute(
                "SELECT id FROM container WHERE name=? COLLATE NOCASE",
                ("MyLists",),
            ).fetchall()
            for (mid,) in mylists_rows:
                flat = con.execute(
                    "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE",
                    (mid, leaf),
                ).fetchone()
                if not flat:
                    continue
                flat_id = flat[0]
                nested_parent = con.execute(
                    "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE",
                    (mid, parent_name),
                ).fetchone()
                if not nested_parent:
                    continue
                nested = con.execute(
                    "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE",
                    (nested_parent[0], leaf),
                ).fetchone()
                if not nested or nested[0] == flat_id:
                    continue
                con.execute("DELETE FROM container_asset WHERE container_id=?", (flat_id,))
                con.execute("DELETE FROM container WHERE id=?", (flat_id,))
                removed[db_name].append(flat_id)
            if removed[db_name]:
                try:
                    con.execute(
                        "UPDATE master SET revision=revision+1, last_sync_time=?",
                        (int(time.time()),),
                    )
                except sqlite3.Error:
                    pass
            con.commit()
        except sqlite3.Error:
            con.rollback()
        finally:
            con.close()

    master_db = lib / "master.sqlite"
    if master_db.is_file() and len(parts) >= 2:
        try:
            con = sqlite3.connect(str(master_db), timeout=10)
        except sqlite3.Error:
            return {"ok": True, "removed": sum(len(v) for v in removed.values()), "details": removed}
        try:
            con.execute("BEGIN IMMEDIATE")
            mylists_rows = con.execute(
                "SELECT id FROM container WHERE name=? COLLATE NOCASE",
                ("MyLists",),
            ).fetchall()
            for (mid,) in mylists_rows:
                flat = con.execute(
                    "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE",
                    (mid, leaf),
                ).fetchone()
                if not flat:
                    continue
                flat_id = flat[0]
                nested_parent = con.execute(
                    "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE",
                    (mid, parent_name),
                ).fetchone()
                if not nested_parent:
                    continue
                nested = con.execute(
                    "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE",
                    (nested_parent[0], leaf),
                ).fetchone()
                if not nested:
                    continue
                _purge_master_location_containers_for_containers(con, [flat_id])
                con.execute("DELETE FROM container WHERE id=?", (flat_id,))
                if con.execute(
                    "SELECT 1 FROM container WHERE id=?", (flat_id,)
                ).fetchone():
                    continue
                removed["master.sqlite"].append(flat_id)
            if removed["master.sqlite"]:
                now = int(time.time())
                for (lid,) in con.execute("SELECT id FROM location"):
                    con.execute(
                        "UPDATE location SET revision=revision+1, last_sync_time=? WHERE id=?",
                        (now, lid),
                    )
            con.commit()
        except sqlite3.Error:
            con.rollback()
        finally:
            con.close()

    return {
        "ok": True,
        "removed": sum(len(v) for v in removed.values()),
        "details": removed,
        "parts": parts,
    }


def sync_grow_crate_flat_alias(
    nested_stem: str,
    track_paths: list[str],
    *,
    serato_dir: Optional[Path] = None,
    library_dir: Optional[Path] = None,
    drive_root: Optional[str] = None,
    path_style: Optional[str] = None,
    path_replace: Optional[dict[str, str]] = None,
    path_substitutes: Optional[dict[str, str]] = None,
) -> dict:
    """
    Rosnące listy (LINKI): płaski crate MyLists%%LINKI w sidebarze Serato
    z tymi samymi utworami i mapowaniem sqlite co zagnieżdżony stem.
    """
    from serato_parser import save_serato_crate

    parts = _crate_stem_to_parts(nested_stem)
    if len(parts) < 2:
        return {"ok": True, "skipped": True, "reason": "not_nested"}
    leaf = parts[-1]
    flat_stem = f"MyLists%%{leaf}"
    nested_path = ["MyLists"] + parts
    flat_path = ["MyLists", leaf]
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    sub_dir.mkdir(parents=True, exist_ok=True)

    # Folder nadrzędny (np. MyLists%%kreatywne listy.crate)
    parent_stem = "%%".join(["MyLists"] + parts[:-1])
    parent_file = sub_dir / f"{parent_stem}.crate"
    if not parent_file.is_file():
        parent_file.write_bytes(save_serato_crate([], parent_stem))

    flat_file = sub_dir / f"{flat_stem}.crate"
    flat_file.write_bytes(
        save_serato_crate(
            track_paths or [],
            flat_stem,
            drive_root,
            path_style=path_style or "relative",
            path_replace=path_replace,
            path_substitutes=path_substitutes,
            existing_files_only=False,
        )
    )
    ptrk = flat_file.read_bytes().count(b"ptrk")

    master_db = _library_dir(library_dir) / "master.sqlite"
    master_linked = 0
    flat_master_id: Optional[int] = None
    if master_db.is_file():
        try:
            con = sqlite3.connect(str(master_db), timeout=10)
        except sqlite3.Error as e:
            return {
                "ok": False,
                "error": str(e),
                "flat_stem": flat_stem,
                "crate_tracks": ptrk,
            }
        try:
            con.execute("BEGIN IMMEDIATE")
            nested_mid = _find_master_container(con, nested_path)
            flat_mid = _ensure_master_container_path(con, flat_path)
            flat_master_id = flat_mid
            if nested_mid and flat_mid and nested_mid != flat_mid:
                _purge_master_location_containers_for_containers(con, [flat_mid])
                cur = con.execute(
                    "UPDATE location_container SET container_id=? WHERE container_id=?",
                    (flat_mid, nested_mid),
                )
                master_linked = cur.rowcount or 0
                _purge_master_location_containers_for_containers(con, [nested_mid])
                con.execute("DELETE FROM container WHERE id=?", (nested_mid,))
                con.execute(
                    "UPDATE container SET expanded=1 WHERE id=?",
                    (flat_mid,),
                )
                parent_mid = _find_master_container(con, ["MyLists"] + parts[:-1])
                if parent_mid:
                    con.execute(
                        "UPDATE container SET expanded=1 WHERE id=?",
                        (parent_mid,),
                    )
            elif flat_mid and not nested_mid:
                # zagnieżdżony brak w master — utwórz linki jak w install_local
                pass
            now = int(time.time())
            for (lid,) in con.execute("SELECT id FROM location"):
                con.execute(
                    "UPDATE location SET revision=revision+1, last_sync_time=? WHERE id=?",
                    (now, lid),
                )
            con.commit()
        except sqlite3.Error as e:
            con.rollback()
            return {
                "ok": False,
                "error": str(e),
                "flat_stem": flat_stem,
                "crate_tracks": ptrk,
            }
        finally:
            con.close()

    return {
        "ok": True,
        "flat_stem": flat_stem,
        "parent_stem": parent_stem,
        "crate_tracks": ptrk,
        "master_flat_id": flat_master_id,
        "master_links_synced": master_linked,
    }


def clear_container_assets_for_crate_stem(
    stem: str,
    *,
    library_dir: Optional[Path] = None,
    databases: Optional[tuple[str, ...]] = None,
) -> dict:
    """
    Usuwa wszystkie linki container_asset dla crate o danym stem
    (np. MyLists%%kreatywne listy%%LINKI) w root.sqlite / tidal.sqlite.
    Nie kasuje samych assetów — tylko przynależność do listy.
    """
    lib = _library_dir(library_dir)
    parts = _crate_stem_to_parts(stem)
    if not parts:
        return {"ok": True, "removed": 0, "dbs": {}}
    # master.sqlite ma inny schemat (location_container_id) — pomijamy
    dbs = databases or ("root.sqlite", "tidal.sqlite")
    per_db: dict[str, int] = {}
    total = 0
    for db_name in dbs:
        db_path = lib / db_name
        if not db_path.is_file():
            continue
        try:
            con = sqlite3.connect(str(db_path), timeout=10)
        except sqlite3.Error:
            per_db[db_name] = -1
            continue
        removed = 0
        try:
            con.execute("BEGIN IMMEDIATE")
            mylists = con.execute(
                "SELECT id FROM container WHERE name=? COLLATE NOCASE",
                ("MyLists",),
            ).fetchall()
            targets: list[int] = []
            for (mid,) in mylists:
                cid = mid
                ok = True
                for name in parts:
                    row = con.execute(
                        "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE LIMIT 1",
                        (cid, name),
                    ).fetchone()
                    if not row:
                        ok = False
                        break
                    cid = row[0]
                if ok:
                    targets.append(cid)
            for cid in targets:
                cur = con.execute(
                    "DELETE FROM container_asset WHERE container_id=?", (cid,)
                )
                n = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                removed += n
                if n:
                    con.execute(
                        "UPDATE container SET revision=revision+1 WHERE id=?", (cid,)
                    )
            if removed:
                try:
                    con.execute(
                        "UPDATE master SET revision=revision+1, last_sync_time=?",
                        (int(time.time()),),
                    )
                except sqlite3.Error:
                    pass
            con.commit()
        except sqlite3.Error:
            con.rollback()
            removed = -1
        finally:
            con.close()
        per_db[db_name] = removed
        if removed > 0:
            total += removed
    return {"ok": True, "removed": total, "dbs": per_db, "parts": parts}


def prune_njr_tids_from_tidal_library(
    njr_tids: set[str],
    *,
    library_dir: Optional[Path] = None,
) -> dict:
    """Usuwa z tidal.sqlite linki container_asset dla ID mających plik NJR (bez kasowania assetu)."""
    lib = _library_dir(library_dir)
    db_path = lib / "tidal.sqlite"
    tids = {str(t).strip() for t in (njr_tids or set()) if str(t).strip()}
    if not tids or not db_path.is_file():
        return {"ok": True, "removed": 0}
    try:
        con = sqlite3.connect(str(db_path), timeout=10)
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e), "removed": 0}
    removed = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        for tid in tids:
            portable = f"streaming://tidal/{tid}"
            rows = con.execute(
                """
                SELECT ca.id FROM container_asset ca
                JOIN space_asset sa ON sa.id = ca.space_asset_id
                JOIN asset a ON a.id = sa.asset_id
                WHERE a.portable_id=? COLLATE NOCASE
                """,
                (portable,),
            ).fetchall()
            for (ca_id,) in rows:
                con.execute("DELETE FROM container_asset WHERE id=?", (ca_id,))
                removed += 1
        if removed:
            con.execute(
                "UPDATE master SET revision=revision+1, last_sync_time=?",
                (int(time.time()),),
            )
        con.commit()
    except sqlite3.Error as e:
        con.rollback()
        return {"ok": False, "error": str(e), "removed": removed}
    finally:
        con.close()
    return {"ok": True, "removed": removed}


def install_tidal_streaming_into_serato_library(
    crate_streaming: list[tuple[str, list[str]]],
    *,
    tidal_meta: Optional[dict[str, dict]] = None,
    songs: Optional[list[dict]] = None,
    library_dir: Optional[Path] = None,
    serato_dir: Optional[Path] = None,
    dry_run: bool = False,
    exclude_tids: Optional[set[str]] = None,
    finalize_metadata: bool = True,
) -> dict:
    """
    crate_streaming: [(stem, [streaming://tidal/ID | netsearch://tdID | …]), …]
    Dodaje utwory do odpowiadających kontenerów w tidal.sqlite (Serato Library).
    Wypełnia MyLists/X w tidal.sqlite oraz linkuje w master.sqlite.
    exclude_tids: Tidal ID z plikiem NJR — nie dodawaj jako streaming.
    """
    lib = _library_dir(library_dir)
    db_path = lib / "tidal.sqlite"
    serato_base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    master_db = lib / "master.sqlite"
    if not db_path.is_file():
        return {"ok": False, "error": f"Brak {db_path} — otwórz Serato z zalogowanym Tidal raz."}

    meta = tidal_meta or {}
    skip = {str(t).strip() for t in (exclude_tids or set()) if str(t).strip()}
    planned: list[tuple[str, list[tuple[str, dict]]]] = []
    total_tracks = 0
    for stem, paths in crate_streaming or []:
        parts = _crate_stem_to_parts(stem)
        if not parts:
            continue
        items: list[tuple[str, dict]] = []
        seen: set[str] = set()
        for p in paths or []:
            if not (is_serato_tidal_path(p) or extract_tidal_id(p)):
                continue
            tid = extract_tidal_id(p)
            if not tid or tid in seen or tid in skip:
                continue
            seen.add(tid)
            m = resolve_tidal_metadata_for_install(
                tid,
                meta,
                songs,
                serato_dir=serato_base,
            )
            items.append((tid, m))
        if items:
            planned.append((stem, items))
            total_tracks += len(items)

    result = {
        "ok": True,
        "dry_run": dry_run,
        "crates": len(planned),
        "tracks_requested": total_tracks,
        "assets_created": 0,
        "links_added": 0,
        "master_links": 0,
        "db": str(db_path),
        "excluded_njr": len(skip),
    }
    if dry_run or not planned:
        return result

    try:
        con = sqlite3.connect(str(db_path), timeout=10)
    except sqlite3.Error as e:
        return {
            "ok": False,
            "error": f"Nie można otworzyć tidal.sqlite ({e}). Zamknij Serato (Cmd+Q) i spróbuj ponownie.",
        }

    master_link_jobs: list[tuple[list[str], int]] = []
    try:
        con.execute("BEGIN IMMEDIATE")
        mylists_top = _ensure_serato_library_roots(con)
        created = 0
        linked = 0
        for stem, items in planned:
            parts = _crate_stem_to_parts(stem)
            full_path = ["MyLists"] + parts
            cid = _ensure_container_path(con, mylists_top, parts)

            next_order = con.execute(
                "SELECT COALESCE(MAX(list_order),0) FROM container_asset WHERE container_id=?",
                (cid,),
            ).fetchone()[0]
            for tid, m in items:
                title = (m.get("Tags.Title") or m.get("Tags.Name") or "").strip()
                artist = (m.get("Tags.Author") or m.get("Tags.Artist") or "").strip()
                bpm = 0.0
                try:
                    raw = m.get("Tags.Bpm") or m.get("bpm") or 0
                    if raw:
                        val = float(raw)
                        bpm = 60.0 / val if 0.2 <= val <= 2.0 else (val if 20 <= val <= 300 else 0.0)
                except (TypeError, ValueError):
                    pass
                key = (m.get("Tags.Key") or m.get("key") or "").strip()
                length = 0.0
                try:
                    length = float(m.get("Infos.SongLength") or m.get("songlength") or 0)
                except (TypeError, ValueError):
                    pass

                existed = con.execute(
                    "SELECT id FROM asset WHERE portable_id=? COLLATE NOCASE",
                    (f"streaming://tidal/{tid}",),
                ).fetchone()
                aid = _upsert_tidal_asset(
                    con,
                    tid,
                    title=title,
                    artist=artist,
                    bpm=bpm,
                    key=key,
                    length_sec=length,
                )
                if not existed:
                    created += 1
                sa_id = _ensure_space_asset(con, aid)
                next_order += 1
                if _link_container_asset(con, cid, sa_id, next_order):
                    linked += 1

            con.execute(
                "UPDATE container SET revision=revision+1 WHERE id=?",
                (cid,),
            )
            master_link_jobs.append((full_path, cid))

        con.execute(
            "UPDATE space SET revision=revision+1 WHERE id=?",
            (SPACE_SERATO_LIBRARY,),
        )
        con.execute(
            "UPDATE master SET revision=revision+1, last_sync_time=?",
            (int(time.time()),),
        )
        con.commit()
        result["assets_created"] = created
        result["links_added"] = linked
    except sqlite3.Error as e:
        con.rollback()
        return {
            "ok": False,
            "error": f"Zapis tidal.sqlite nieudany: {e}. Zamknij Serato i ponów.",
        }
    finally:
        con.close()

    master_stats = _link_master_to_tidal_containers(master_db, master_link_jobs)
    result["master_links"] = master_stats.get("linked", 0)
    result["master_skipped"] = master_stats.get("skipped", 0)
    if not master_stats.get("ok"):
        result["master_error"] = master_stats.get("error")
    if skip:
        prune = prune_njr_tids_from_tidal_library(skip, library_dir=lib)
        result["njr_stream_pruned"] = prune.get("removed", 0)
        if not prune.get("ok"):
            result["njr_prune_error"] = prune.get("error")
    if finalize_metadata and not dry_run:
        meta_fix = repair_tidal_sqlite_metadata(
            library_dir=lib,
            serato_dir=serato_base,
            dry_run=False,
        )
        result["tidal_metadata_repair"] = meta_fix
    return result


_NON_MYLIST_SERATO_ROOT_NAMES = frozenset({
    "sideview",
    "folders",
    "filters",
})


def remove_vdj_serato_library_tree(
    *,
    library_dir: Optional[Path] = None,
    serato_dir: Optional[Path] = None,
) -> dict:
    """
    Usuwa zduplikowane drzewa filtrów VDJ (Sideview, Folders/Filters) z Serato Library
    (master/root/tidal) oraz powiązane Subcrates. Zostaje MyLists, „wszystkie pliki” i cache.
    Wymaga zamkniętego Serato.
    """
    lib = _library_dir(library_dir)
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    result: dict = {
        "ok": True,
        "master_deleted": 0,
        "root_deleted": 0,
        "tidal_deleted": 0,
        "crates_removed": 0,
    }

    def _collect_descendants(con: sqlite3.Connection, root_ids: list[int]) -> list[int]:
        """DFS: wszystkie id pod root_ids (włącznie)."""
        out: list[int] = []
        stack = list(root_ids)
        seen: set[int] = set()
        while stack:
            cid = stack.pop()
            if cid in seen:
                continue
            seen.add(cid)
            out.append(cid)
            for (child,) in con.execute(
                "SELECT id FROM container WHERE parent_id=?", (cid,)
            ):
                stack.append(child)
        return out

    def _delete_vdj_under_library_root(db_path: Path) -> int:
        if not db_path.is_file():
            return 0
        try:
            con = sqlite3.connect(str(db_path), timeout=10)
        except sqlite3.Error:
            return -1
        deleted = 0
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")
            roots = [
                r[0]
                for r in con.execute(
                    "SELECT id FROM container WHERE name='Serato Library root'"
                )
            ]
            vdj_ids: list[int] = []
            for root_id in roots:
                for (vid,) in con.execute(
                    "SELECT id FROM container WHERE parent_id=? AND name=? COLLATE NOCASE",
                    (root_id, "VDJ"),
                ):
                    vdj_ids.append(vid)
                for (cid, name) in con.execute(
                    "SELECT id, name FROM container WHERE parent_id=?", (root_id,)
                ):
                    if (name or "").strip().lower() in _NON_MYLIST_SERATO_ROOT_NAMES:
                        vdj_ids.append(cid)
            # też osierocone „VDJ” (po wcześniejszym DELETE bez CASCADE)
            for (vid,) in con.execute(
                "SELECT id FROM container WHERE name=? COLLATE NOCASE", ("VDJ",)
            ):
                if vid not in vdj_ids:
                    vdj_ids.append(vid)
            for (cid, name) in con.execute("SELECT id, name FROM container"):
                if (name or "").strip().lower() in _NON_MYLIST_SERATO_ROOT_NAMES:
                    if cid not in vdj_ids:
                        vdj_ids.append(cid)

            all_ids = _collect_descendants(con, vdj_ids)
            # location_container (master) — usuń linki do kasowanych kontenerów
            has_lc = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='location_container'"
            ).fetchone()
            if has_lc and all_ids:
                _purge_master_location_containers_for_containers(con, all_ids)
                qmarks = ",".join("?" * len(all_ids))
                con.execute(
                    f"DELETE FROM location_container WHERE external_container_id IN ({qmarks})",
                    all_ids,
                )
            # kasuj od liści (bez FK) — albo CASCADE z PRAGMA
            for cid in reversed(all_ids):
                con.execute("DELETE FROM container WHERE id=?", (cid,))
                deleted += 1

            # posprzątaj kontenery bez rodzica (oprócz root type=0)
            orphans = con.execute(
                """
                SELECT c.id FROM container c
                WHERE c.parent_id IS NOT NULL AND c.parent_id != 0
                  AND NOT EXISTS (SELECT 1 FROM container p WHERE p.id = c.parent_id)
                """
            ).fetchall()
            orphan_ids = _collect_descendants(con, [r[0] for r in orphans])
            if has_lc and orphan_ids:
                _purge_master_location_containers_for_containers(con, orphan_ids)
            for cid in reversed(orphan_ids):
                con.execute("DELETE FROM container WHERE id=?", (cid,))
                deleted += 1

            # posprzątaj metadane wskazujące na usunięte kontenery (Serato FK check)
            for tbl, col in (
                ("dj_container_metadata", "container_id"),
                ("container_asset_list_columns", "container_id"),
                ("container_asset", "container_id"),
                ("smart_crate_rules", "container_id"),
                ("expanded_container_backup", "container_id"),
                ("updated_container", "container_id"),
                ("moved_container", "container_id"),
            ):
                if not con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (tbl,),
                ).fetchone():
                    continue
                cols = [r[1] for r in con.execute(f"PRAGMA table_info({tbl})")]
                if col not in cols:
                    continue
                con.execute(
                    f"DELETE FROM {tbl} WHERE {col} NOT IN (SELECT id FROM container)"
                )
            ca_cols = [
                r[1] for r in con.execute("PRAGMA table_info(container_asset)")
            ] if con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='container_asset'"
            ).fetchone() else []
            if "location_container_id" in ca_cols:
                con.execute(
                    """
                    DELETE FROM container_asset
                    WHERE location_container_id IS NOT NULL
                      AND location_container_id NOT IN (SELECT id FROM location_container)
                    """
                )

            if deleted:
                try:
                    con.execute(
                        "UPDATE master SET revision=revision+1, last_sync_time=?",
                        (int(time.time()),),
                    )
                except sqlite3.Error:
                    pass
            con.commit()
        except sqlite3.Error as e:
            con.rollback()
            result["ok"] = False
            result["error"] = str(e)
            deleted = -1
        finally:
            con.close()
        return deleted

    result["master_deleted"] = _delete_vdj_under_library_root(lib / "master.sqlite")
    result["root_deleted"] = _delete_vdj_under_library_root(lib / "root.sqlite")
    result["tidal_deleted"] = _delete_vdj_under_library_root(lib / "tidal.sqlite")
    if any(
        v == -1
        for v in (result["master_deleted"], result["root_deleted"], result["tidal_deleted"])
    ):
        result["ok"] = False
        result.setdefault(
            "error",
            "Nie można otworzyć bazy Serato — zamknij Serato (Cmd+Q) i spróbuj ponownie.",
        )

    sub = base / "Subcrates"
    removed_crates: list[str] = []
    if sub.is_dir():
        from serato_parser import purge_vdj_filter_tree_subcrates

        purge = purge_vdj_filter_tree_subcrates(base, dry_run=False)
        removed_crates.extend(purge.get("removed") or [])
        for p in list(sub.glob("VDJ%%*.crate")):
            if p.name in removed_crates:
                continue
            try:
                p.unlink()
                removed_crates.append(p.name)
            except OSError:
                pass
        vdj_crate = sub / "VDJ.crate"
        if vdj_crate.is_file():
            try:
                vdj_crate.unlink()
                removed_crates.append("VDJ.crate")
            except OSError:
                pass
    result["crates_removed"] = len(removed_crates)
    result["crate_names"] = removed_crates[:20]
    return result
