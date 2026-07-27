"""
Synchronizacja okładek Engine DJ z tagów osadzonych w plikach audio.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def extract_embedded_cover(file_path: Path) -> bytes | None:
    """Zwraca bajty okładki (JPEG/PNG) z tagów pliku lub None."""
    if not file_path.is_file():
        return None
    ext = file_path.suffix.lower()
    try:
        if ext in (".mp3", ".mp2", ".mp1"):
            from mutagen.id3 import ID3

            try:
                id3 = ID3(str(file_path))
            except Exception:
                return None
            for key in id3.keys():
                if key.startswith("APIC"):
                    data = id3[key].data
                    return bytes(data) if data else None
            return None

        from mutagen import File

        audio = File(str(file_path))
        if audio is None:
            return None
        tags = getattr(audio, "tags", None)
        if tags:
            for key in tags.keys():
                if "covr" in key.lower():
                    val = tags[key]
                    if isinstance(val, (list, tuple)) and val:
                        return bytes(val[0])
                    if val:
                        return bytes(val)
        pictures = getattr(audio, "pictures", None)
        if pictures:
            data = pictures[0].data
            return bytes(data) if data else None
    except Exception:
        return None
    return None


def _cover_hashes(image_bytes: bytes) -> tuple[bytes, str]:
    digest = hashlib.sha1(image_bytes).digest()
    return digest, digest.hex()


def sync_engine_album_art(
    engine_dir: Path,
    paths: set[str] | None = None,
    *,
    clear_broken: bool = True,
) -> dict:
    """
    Importuje okładki z plików do AlbumArt i ustawia Track.albumArtId.
    paths — opcjonalnie tylko te ścieżki względne (po merge: utwory z VDJ).
    """
    engine_dir = engine_dir.resolve()
    mdb = engine_dir / "Database2" / "m.db"
    if not mdb.is_file():
        return {"skipped": True, "reason": "no_m_db"}

    path_filter = None
    if paths:
        path_filter = {p.replace("\\", "/") for p in paths if p}

    conn = sqlite3.connect(str(mdb))
    try:
        conn.execute("PRAGMA foreign_keys=ON")

        dangling_cleared = 0
        if clear_broken:
            bad_ids = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT id FROM AlbumArt
                    WHERE albumArt IS NULL OR length(albumArt) = 0
                    """
                )
            }
            if bad_ids:
                placeholders = ",".join("?" for _ in bad_ids)
                conn.execute(
                    f"""
                    UPDATE Track SET albumArtId = NULL, albumArtSourceHash = NULL
                    WHERE albumArtId IN ({placeholders})
                    """,
                    tuple(bad_ids),
                )
                conn.execute(
                    f"DELETE FROM AlbumArt WHERE id IN ({placeholders})",
                    tuple(bad_ids),
                )
            # libdjinterop czasem zostawia albumArtId wskazujące na nieistniejący wiersz
            dangling_cleared = conn.execute(
                """
                UPDATE Track SET albumArtId = NULL, albumArtSourceHash = NULL
                WHERE albumArtId IS NOT NULL
                  AND albumArtId NOT IN (SELECT id FROM AlbumArt)
                """
            ).rowcount

        if path_filter:
            placeholders = ",".join("?" for _ in path_filter)
            track_rows = conn.execute(
                f"SELECT id, path FROM Track WHERE path IN ({placeholders})",
                tuple(sorted(path_filter)),
            ).fetchall()
        else:
            track_rows = conn.execute("SELECT id, path FROM Track").fetchall()

        hash_to_art_id: dict[bytes, int] = {}
        for row in conn.execute("SELECT id, hash FROM AlbumArt WHERE hash IS NOT NULL"):
            if row[1]:
                hash_to_art_id[row[1]] = row[0]

        linked = 0
        unique_new = 0
        missing = 0
        skipped_exists = 0
        preserved_existing = 0

        for track_id, rel_path in track_rows:
            full = (engine_dir / rel_path).resolve()
            cover = extract_embedded_cover(full)
            if not cover:
                # Nie kasuj istniejącej okładki gdy plik chwilowo nieczytelny
                # albo nie ma APIC — inaczej merge VDJ wymazuje Artwork.
                missing += 1
                prev = conn.execute(
                    "SELECT albumArtId FROM Track WHERE id = ?",
                    (track_id,),
                ).fetchone()
                if prev and prev[0] is not None:
                    preserved_existing += 1
                continue

            bin_hash, hex_hash = _cover_hashes(cover)
            art_id = hash_to_art_id.get(bin_hash)
            if art_id is None:
                cur = conn.execute(
                    """
                    INSERT INTO AlbumArt (hash, albumArt) VALUES (?, ?)
                    """,
                    (bin_hash, cover),
                )
                art_id = cur.lastrowid
                hash_to_art_id[bin_hash] = art_id
                unique_new += 1
            else:
                skipped_exists += 1

            cur = conn.execute(
                "SELECT albumArtId, albumArtSourceHash FROM Track WHERE id = ?",
                (track_id,),
            )
            prev = cur.fetchone()
            if prev and prev[0] == art_id and prev[1] == hex_hash:
                continue

            conn.execute(
                """
                UPDATE Track SET albumArtId = ?, albumArtSourceHash = ?
                WHERE id = ?
                """,
                (art_id, hex_hash, track_id),
            )
            linked += 1

        conn.commit()
        album_art_total = conn.execute("SELECT COUNT(*) FROM AlbumArt").fetchone()[0]
    finally:
        conn.close()

    return {
        "album_art_tracks_linked": linked,
        "album_art_unique_added": unique_new,
        "album_art_reused": skipped_exists,
        "album_art_no_embedded": missing,
        "album_art_preserved_existing": preserved_existing,
        "album_art_dangling_cleared": dangling_cleared if clear_broken else 0,
        "album_art_total": album_art_total,
        "album_art_paths_scoped": bool(path_filter),
    }
