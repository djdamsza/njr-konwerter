"""
Parser bazy Engine DJ (Denon) – m.db (SQLite).
Import do formatu _songs (VDJ-style).
Eksport: na razie brak – zapis m.db wymaga zachowania schematu.
"""
import sqlite3
from pathlib import Path
from typing import Optional

from unified_model import UnifiedDatabase, Track, Playlist

# MetaData type -> pole (Engine Prime schema)
_META_TYPE = {
    7: "composer",
    8: "publisher",
    9: "comment",
    10: "genre",
    11: "album",
    12: "artist",
    13: "title",
}

# MetaDataInteger type 1 = key (Camelot)
_ENGINE_KEY_MAP = {
    0: "8B", 1: "8A", 2: "9B", 3: "9A", 4: "10B", 5: "10A", 6: "11B", 7: "11A",
    8: "12B", 9: "12A", 10: "1B", 11: "1A", 12: "2B", 13: "2A", 14: "3B", 15: "3A",
    16: "4B", 17: "4A", 18: "5B", 19: "5A", 20: "6B", 21: "6A", 22: "7B", 23: "7A",
}


def _engine_rating_to_stars(val: Optional[int]) -> int:
    """Engine: 0,20,40,60,80,100,120 -> 0-5 stars."""
    if val is None:
        return 0
    return min(5, max(0, round(val / 25)))


def load_engine_db(db_path: Path, library_base: Optional[str] = None) -> UnifiedDatabase:
    """
    Ładuje m.db Engine DJ.
    Database2 (schemat 2.x/3.x) trzyma tytuł i wykonawcę w tabeli Track.
    Starszy Engine Prime trzyma je w MetaData.
    library_base: opcjonalny folder Engine Library — ścieżki w Track są względem niego.
    """
    db_path = Path(db_path)
    engine_dir = _engine_dir_for(db_path, library_base)
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.OperationalError as exc:
        _raise_engine_open(db_path, exc)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "Track" not in tables:
            raise ValueError(
                f"W {db_path} nie ma tabeli Track. To nie jest biblioteka Engine DJ."
            )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(Track)")}
        if "title" in cols:
            tracks = _tracks_from_columns(conn, cols, engine_dir, library_base)
        elif "MetaData" in tables:
            tracks = _tracks_from_metadata(conn, engine_dir, library_base)
        else:
            names = ", ".join(sorted(tables))
            raise ValueError(
                f"Baza Engine {db_path} nie ma kolumn tytułu ani tabeli MetaData. "
                f"Tabele: {names}"
            )
        playlists = _engine_playlists(conn, tables, tracks)
        return UnifiedDatabase(tracks=tracks, playlists=playlists, source="engine")
    finally:
        conn.close()


def _engine_dir_for(db_path: Path, library_base: Optional[str]) -> Optional[Path]:
    if library_base:
        return Path(library_base).expanduser()
    if db_path.parent.name == "Database2":
        return db_path.parent.parent
    return db_path.parent


def _raise_engine_open(db_path: Path, exc: BaseException) -> None:
    from mac_access import offer_library_access

    folder = db_path.parent.parent if db_path.parent.name == "Database2" else db_path.parent
    raw = str(exc)
    if "unable to open" in raw.lower() or "permission" in raw.lower():
        offer_library_access(folder, "Engine DJ")
        raise ValueError(
            f"Nie mogę otworzyć {db_path}. Zamknij Engine DJ. "
            "Jeśli macOS nie pyta o zgodę, włącz Pełny dostęp do dysku dla Terminala "
            f"(Ustawienia systemowe → Prywatność i ochrona) i pobierz bazę ponownie. Szczegół: {raw}"
        ) from exc
    raise ValueError(f"Nie mogę otworzyć bazy Engine {db_path}: {raw}") from exc


def _cell(row: sqlite3.Row, col: str, default=""):
    if col not in row.keys() or row[col] is None:
        return default
    return row[col]


def _abs_engine_path(raw: str, engine_dir: Optional[Path], library_base: Optional[str]) -> str:
    text = (raw or "").replace("\\", "/").strip()
    if not text:
        return ""
    if text.startswith("/") or (len(text) > 2 and text[1] == ":"):
        return text
    if engine_dir is not None:
        candidate = engine_dir / text
        try:
            if candidate.is_symlink() or candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            pass
    if library_base and not text.startswith("/"):
        return str(Path(library_base) / text)
    return text


def _tracks_from_columns(conn, cols: set, engine_dir: Optional[Path], library_base: Optional[str]) -> list:
    wanted = [
        "id", "path", "filename", "title", "artist", "album", "genre", "comment",
        "year", "length", "bpm", "bpmAnalyzed", "key", "rating",
    ]
    select = [c for c in wanted if c in cols]
    tracks = []
    for row in conn.execute(f"SELECT {', '.join(select)} FROM Track"):
        raw_path = str(_cell(row, "path") or _cell(row, "filename") or "").strip()
        path = _abs_engine_path(raw_path, engine_dir, library_base)
        if not path:
            continue
        bpm = float(_cell(row, "bpmAnalyzed", 0) or 0)
        if not bpm:
            bpm = float(_cell(row, "bpm", 0) or 0)
        key = _engine_key(_cell(row, "key", None))
        genre = str(_cell(row, "genre") or "")
        tracks.append(Track(
            path=path,
            title=str(_cell(row, "title") or ""),
            artist=str(_cell(row, "artist") or ""),
            album=str(_cell(row, "album") or ""),
            genre=genre,
            tags=[t.strip() for t in genre.split() if t.strip()],
            comment=str(_cell(row, "comment") or ""),
            bpm=bpm,
            key=key,
            year=int(_cell(row, "year", 0) or 0),
            duration=float(_cell(row, "length", 0) or 0),
            rating=_engine_rating_to_stars(_cell(row, "rating", None)),
            source_id=str(row["id"]),
        ))
    return tracks


def _engine_key(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str) and not value.lstrip("-").isdigit():
        return value
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return _ENGINE_KEY_MAP.get(number, str(value))


def _tracks_from_metadata(conn, engine_dir: Optional[Path], library_base: Optional[str]) -> list:
    rows = conn.execute(
        "SELECT id, path, filename, length, bpm, year, bpmAnalyzed FROM Track"
    ).fetchall()
    meta = {}
    for r in conn.execute("SELECT id, type, text FROM MetaData"):
        tid, ttype, text = r["id"], r["type"], r["text"]
        meta.setdefault(tid, {})
        key = _META_TYPE.get(ttype)
        if key and text:
            meta[tid][key] = (text or "").strip()
    meta_int = {}
    if "MetaDataInteger" in {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }:
        for r in conn.execute("SELECT id, type, value FROM MetaDataInteger"):
            meta_int.setdefault(r["id"], {})[r["type"]] = r["value"]
    tracks = []
    for r in rows:
        tid = r["id"]
        raw_path = (r["path"] or "").strip() or (r["filename"] or "").strip()
        path = _abs_engine_path(raw_path, engine_dir, library_base)
        if not path:
            continue
        m = meta.get(tid, {})
        mi = meta_int.get(tid, {})
        genre = m.get("genre", "")
        bpm = float(r["bpmAnalyzed"] or r["bpm"] or 0)
        if not bpm and r["bpm"]:
            bpm = float(r["bpm"])
        key_val = mi.get(1)
        tracks.append(Track(
            path=path,
            title=m.get("title", ""),
            artist=m.get("artist", ""),
            album=m.get("album", ""),
            genre=genre,
            tags=[t.strip() for t in genre.split() if t.strip()],
            comment=m.get("comment", ""),
            bpm=bpm,
            key=_ENGINE_KEY_MAP.get(key_val, "") if key_val is not None else "",
            year=int(r["year"] or 0),
            duration=float(r["length"] or 0),
            rating=_engine_rating_to_stars(mi.get(7)),
            source_id=str(tid),
        ))
    return tracks


def _engine_playlists(conn, tables: set, tracks: list) -> list:
    id_to_path = {str(t.source_id): t.path for t in tracks if t.source_id}
    playlists = []
    if "Playlist" in tables and "PlaylistEntity" in tables:
        pl_cols = {r[1] for r in conn.execute("PRAGMA table_info(Playlist)")}
        pe_cols = {r[1] for r in conn.execute("PRAGMA table_info(PlaylistEntity)")}
        title_col = "title" if "title" in pl_cols else None
        parent_col = "parentListId" if "parentListId" in pl_cols else None
        rows = conn.execute(f"SELECT {', '.join(c for c in ['id', title_col, parent_col] if c)} FROM Playlist").fetchall()
        by_id = {int(r["id"]): r for r in rows}

        def label(pid: int) -> str:
            parts = []
            seen = set()
            while pid and pid not in seen:
                seen.add(pid)
                row = by_id.get(pid)
                if row is None:
                    break
                name = str(row["title"] or "").strip() if title_col else ""
                if name:
                    parts.append(name)
                pid = int(row["parentListId"] or 0) if parent_col else 0
            return " / ".join(reversed(parts))

        order_sql = "id"
        if "nextEntityId" in pe_cols:
            order_sql = "id, trackId, nextEntityId"
        else:
            order_sql = "id, trackId"
        grouped: dict[int, list] = {}
        for row in conn.execute(f"SELECT listId, {order_sql} FROM PlaylistEntity"):
            grouped.setdefault(int(row["listId"]), []).append(row)
        for pl_id, row in by_id.items():
            members = grouped.get(pl_id) or []
            track_ids = _ordered_entity_ids(members)
            paths = [id_to_path.get(str(tid), "") for tid in track_ids]
            paths = [p for p in paths if p]
            name = label(pl_id)
            if paths and name:
                playlists.append(Playlist(name=name, track_ids=paths))
        return playlists
    if "Playlist" in tables and "PlaylistTrackList" in tables:
        for pl_row in conn.execute("SELECT id, title FROM Playlist"):
            ids = [
                str(r["trackId"])
                for r in conn.execute(
                    "SELECT trackId FROM PlaylistTrackList WHERE playlistId = ? ORDER BY trackNumber",
                    (pl_row["id"],),
                )
            ]
            paths = [id_to_path.get(tid, "") for tid in ids]
            paths = [p for p in paths if p]
            if paths:
                playlists.append(Playlist(name=pl_row["title"] or f"Playlist {pl_row['id']}", track_ids=paths))
    return playlists


def _ordered_entity_ids(rows: list) -> list:
    if not rows:
        return []
    if "nextEntityId" not in rows[0].keys():
        return [int(r["trackId"]) for r in rows if r["trackId"]]
    by_id = {int(r["id"]): r for r in rows}
    pointed = {int(r["nextEntityId"]) for r in rows if r["nextEntityId"]}
    heads = [r for r in rows if int(r["id"]) not in pointed]
    if not heads:
        return [int(r["trackId"]) for r in rows if r["trackId"]]
    ordered = []
    seen = set()
    for head in heads:
        cur = int(head["id"])
        while cur and cur in by_id and cur not in seen:
            seen.add(cur)
            tid = by_id[cur]["trackId"]
            if tid:
                ordered.append(int(tid))
            nxt = by_id[cur]["nextEntityId"]
            cur = int(nxt) if nxt else 0
    return ordered
