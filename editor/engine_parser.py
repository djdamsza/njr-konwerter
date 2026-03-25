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
    library_base: opcjonalna ścieżka bazowa (np. /path/to/Engine Library) – path w Track jest względny.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, path, filename, length, bpm, year, bpmAnalyzed FROM Track")
        rows = cur.fetchall()
        meta = {}
        cur.execute("SELECT id, type, text FROM MetaData")
        for r in cur.fetchall():
            tid, ttype, text = r["id"], r["type"], r["text"]
            if tid not in meta:
                meta[tid] = {}
            key = _META_TYPE.get(ttype)
            if key and text:
                meta[tid][key] = (text or "").strip()
        meta_int = {}
        cur.execute("SELECT id, type, value FROM MetaDataInteger")
        for r in cur.fetchall():
            tid, ttype, val = r["id"], r["type"], r["value"]
            if tid not in meta_int:
                meta_int[tid] = {}
            meta_int[tid][ttype] = val
        tracks = []
        for r in rows:
            tid = r["id"]
            path = (r["path"] or "").strip() or (r["filename"] or "").strip()
            if not path:
                continue
            if library_base and not path.startswith("/") and ":" not in path[:2]:
                path = str(Path(library_base) / path.replace("\\", "/"))
            m = meta.get(tid, {})
            mi = meta_int.get(tid, {})
            artist = m.get("artist", "")
            title = m.get("title", "")
            genre = m.get("genre", "")
            album = m.get("album", "")
            comment = m.get("comment", "")
            bpm = float(r["bpmAnalyzed"] or r["bpm"] or 0)
            if not bpm and r["bpm"]:
                bpm = float(r["bpm"])
            key_val = mi.get(1)
            key = _ENGINE_KEY_MAP.get(key_val, "") if key_val is not None else ""
            rating = _engine_rating_to_stars(mi.get(7))
            duration = float(r["length"] or 0)
            year = int(r["year"] or 0)
            tags = [t.strip() for t in (genre or "").split() if t.strip()]
            tracks.append(Track(
                path=path,
                title=title,
                artist=artist,
                album=album,
                genre=genre,
                tags=tags,
                comment=comment,
                bpm=bpm,
                key=key,
                year=year,
                duration=duration,
                rating=rating,
                source_id=str(tid),
            ))
        playlists = []
        cur.execute("SELECT id, title FROM Playlist")
        for pl_row in cur.fetchall():
            pl_id = pl_row["id"]
            cur.execute("SELECT trackId FROM PlaylistTrackList WHERE playlistId = ? ORDER BY trackNumber", (pl_id,))
            track_ids = [str(r["trackId"]) for r in cur.fetchall()]
            id_to_path = {str(t.source_id): t.path for t in tracks if t.source_id}
            paths = [id_to_path.get(str(tid), "") for tid in track_ids]
            paths = [p for p in paths if p]
            if paths:
                playlists.append(Playlist(name=pl_row["title"] or f"Playlist {pl_id}", track_ids=paths))
        return UnifiedDatabase(tracks=tracks, playlists=playlists, source="engine")
    finally:
        conn.close()
