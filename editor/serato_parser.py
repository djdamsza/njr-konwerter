"""
Parser bazy Serato DJ – DatabaseV2 i pliki .crate.
Format binarny (tag 4B + length 4B + data). Źródło: Holzhaus/serato-tags, Mixxx wiki.
Import do formatu _songs (VDJ-style).
"""
import re
import struct
from io import BytesIO
from pathlib import Path
from typing import Optional

from unified_model import UnifiedDatabase, Track, Playlist


def _decode_utf16be(data: bytes) -> str:
    """Dekoduje UTF-16 big-endian. Serato czasem ma leading byte."""
    if not data:
        return ""
    try:
        return data.decode("utf-16-be").rstrip("\x00")
    except UnicodeDecodeError:
        pass
    if len(data) > 1 and data[0] in (0, 0xFF, 0xFE):
        try:
            return data[1:].decode("utf-16-be").rstrip("\x00")
        except UnicodeDecodeError:
            pass
    return ""


def _parse_serato_records(fp: BytesIO) -> list[tuple[str, object]]:
    """Parsuje sekwencję rekordów Serato (tag 4B, length 4B BE, data)."""
    result = []
    while True:
        header = fp.read(8)
        if len(header) < 8:
            break
        name = header[:4].decode("ascii", errors="replace")
        length = struct.unpack(">I", header[4:8])[0]
        data = fp.read(length)
        if len(data) < length:
            break
        if name == "vrsn":
            value = _decode_utf16be(data)
        elif name[0] == "o" or name[0] == "r":
            value = _parse_serato_records(BytesIO(data))
        elif name[0] == "t" or name[0] == "p":
            value = _decode_utf16be(data)
        elif name[0] == "u":
            value = struct.unpack(">I", data[:4])[0] if len(data) >= 4 else 0
        elif name[0] == "s":
            value = struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 0
        elif name[0] == "b":
            value = bool(struct.unpack("?", data[:1])[0]) if data else False
        else:
            value = data
        result.append((name, value))
    return result


def _parse_serato_tcom(raw: str) -> tuple[str, int]:
    """Komentarz Serato (tcom) + ocena 0–5 gwiazdek (standalone „Rating: N” lub „… | Rating: N”)."""
    from tag_writer import strip_rating_hack_from_comment

    text = (raw or "").strip()
    comment = text
    stars = 0
    if " | Rating: " in text:
        parts = text.split(" | Rating: ", 1)
        comment = parts[0].strip()
        try:
            stars = min(5, max(0, int(parts[1].strip())))
        except (ValueError, IndexError):
            pass
    elif text.startswith("Rating: "):
        rest = text[8:].strip()
        token = rest.split()[0] if rest else ""
        if token.isdigit():
            stars = min(5, max(0, int(token)))
            tail = rest[len(token) :].strip()
            comment = tail
    comment = strip_rating_hack_from_comment(comment)
    return comment, stars


def _parse_track(otrk: list) -> Optional[Track]:
    """Wyciąga Track z rekordu otrk (lista (name, value))."""
    path = ""
    title = ""
    artist = ""
    album = ""
    genre = ""
    comment = ""
    play_count = 0
    rating = 0
    bpm = 0.0
    key = ""
    year = 0
    duration = 0.0
    bitrate = 0
    for name, value in otrk:
        if name == "pfil" or name == "ptrk":
            path = (value or "").strip()
        elif name == "tsng":
            title = (value or "").strip()
        elif name == "tart":
            artist = (value or "").strip()
        elif name == "talb":
            album = (value or "").strip()
        elif name == "tgen":
            genre = (value or "").strip()
        elif name == "tcom":
            comment, rating = _parse_serato_tcom(value or "")
        elif name == "ttyr":
            try:
                year = int(str(value).strip()) if value else 0
            except (TypeError, ValueError):
                year = 0
        elif name == "utpc":
            play_count = int(value) if value is not None else 0
        elif name == "tkey":
            key = (value or "").strip()
        elif name == "tbpm":
            try:
                bpm = float(value) if value is not None else 0.0
            except (TypeError, ValueError):
                pass
        elif name == "tlen":
            try:
                if value and isinstance(value, str) and ":" in value:
                    parts = value.strip().split(":")
                    if len(parts) >= 2:
                        duration = float(parts[0]) * 60 + float(parts[1])
                    else:
                        duration = float(value)
                else:
                    duration = float(value) if value is not None else 0.0
            except (TypeError, ValueError):
                pass
        elif name == "tbit":
            try:
                bitrate = int(value) if value is not None else 0
            except (TypeError, ValueError):
                pass
        elif name == "ttyp":
            pass  # ttyp = File Type (mp3, flac), nie genre
    if not path:
        return None
    if not title and path:
        title = Path(path).stem
    # Serato rating 0–5 → unified 0–255 (jak RB: 1→51, 2→102, 3→153, 4→204, 5→255)
    rating_255 = rating * 51 if 1 <= rating <= 5 else 0
    tags = [t.strip() for t in (genre or "").split() if t.strip()]
    return Track(
        path=path,
        title=title or "",
        artist=artist or "",
        album=album or "",
        genre=genre or "",
        tags=tags,
        comment=comment or "",
        play_count=play_count,
        rating=rating_255,
        bpm=bpm,
        key=key or "",
        year=year,
        duration=duration,
    )


def load_serato_database_v2(content: bytes, drive_root: Optional[str] = None) -> UnifiedDatabase:
    """
    Ładuje plik DatabaseV2 Serato.
    drive_root: opcjonalna ścieżka bazowa (np. /Volumes/USB lub E:) – path w Serato jest względny do rootu dysku.
    """
    records = _parse_serato_records(BytesIO(content))
    tracks = []
    for name, value in records:
        if name == "otrk" and isinstance(value, list):
            t = _parse_track(value)
            if t and t.path:
                path = t.path.replace("\\", "/")
                if drive_root and not (len(path) >= 2 and path[1] == ":") and not path.startswith("/"):
                    path = str(Path(drive_root) / path.lstrip("/"))
                t.path = path
                tracks.append(t)
    return UnifiedDatabase(tracks=tracks, playlists=[], source="serato")


def load_serato_crate(content: bytes, crate_name: str, drive_root: Optional[str] = None) -> Playlist:
    """Ładuje pojedynczy plik .crate – zwraca Playlist z ścieżkami."""
    records = _parse_serato_records(BytesIO(content))
    paths = []
    for name, value in records:
        if name == "otrk" and isinstance(value, list):
            for n, v in value:
                if (n == "ptrk" or n == "pfil") and isinstance(v, str) and v.strip():
                    p = v.strip().replace("\\", "/")
                    if drive_root and not (len(p) >= 2 and p[1] == ":") and not p.startswith("/"):
                        p = str(Path(drive_root) / p.lstrip("/"))
                    paths.append(p)
                    break
    return Playlist(name=crate_name, track_ids=paths)


def load_serato_folder(serato_path: Path, drive_root: Optional[str] = None) -> UnifiedDatabase:
    """
    Ładuje pełną bibliotekę Serato z folderu _Serato_.
    serato_path: ścieżka do folderu _Serato_ (lub folderu nadrzędnego – szukamy _Serato_/database V2).
    drive_root: root dysku (dla ścieżek względnych w DatabaseV2).
    """
    if not serato_path.is_dir():
        serato_path = serato_path / "_Serato_"
    db_file = serato_path / "database V2"
    if not db_file.exists():
        db_file = serato_path / "DatabaseV2"
    if not db_file.exists():
        return UnifiedDatabase(tracks=[], playlists=[], source="serato")

    content = db_file.read_bytes()
    root = drive_root or str(serato_path.parent)
    db = load_serato_database_v2(content, drive_root=root)

    subcrates = serato_path / "Subcrates"
    if subcrates.is_dir():
        for cf in subcrates.glob("*.crate"):
            try:
                pl = load_serato_crate(cf.read_bytes(), cf.stem, drive_root=root)
                if pl.track_ids:
                    db.playlists.append(pl)
            except Exception:
                pass
    return db


def _encode_utf16be(s: str) -> bytes:
    """Koduje tekst do UTF-16 big-endian (Serato)."""
    return (s or "").encode("utf-16-be")


def _write_serato_record(buf: BytesIO, name: str, data: bytes) -> None:
    """Zapisuje rekord Serato (tag 4B + length 4B + data)."""
    buf.write(name.encode("ascii")[:4].ljust(4, b"\x00"))
    buf.write(struct.pack(">I", len(data)))
    buf.write(data)


def _get_comment_from_song(s: dict) -> str:
    """Wyciąga tekst Comment z _children_xml (format VDJ)."""
    import xml.etree.ElementTree as ET
    for xml_str in s.get("_children_xml") or []:
        try:
            elem = ET.fromstring(xml_str)
            if elem.tag == "Comment" and elem.text:
                return (elem.text or "").strip()[:1024]
        except (ET.ParseError, ValueError):
            continue
    return ""


def to_serato_relative_path(path: str) -> str:
    """
    Kanoniczna ścieżka Serato na macOS: bez wiodącego `/`
    (`Users/…/file.mp3`, nie `/Users/…/file.mp3`).
    Serato przy odtwarzaniu dopisuje wpis relatywny — absolutny zostaje jako klon.
    """
    p = (path or "").strip().replace("\\", "/")
    if p.startswith("/"):
        p = p[1:]
    return p


def collapse_serato_broken_path_prefixes(path: str) -> str:
    """
    Usuwa zepsuty podwójny prefix po eksporcie NJR, np.:
    Users/test/Music/Users/test/Desktop/… → Users/test/Desktop/…
    """
    p = to_serato_relative_path(path)
    if not p:
        return p
    user = Path.home().name
    dup = f"Users/{user}/Music/Users/{user}/"
    while dup in p:
        p = p.replace(dup, f"Users/{user}/", 1)
    return p


def canonical_serato_relative_path(path: str) -> str:
    """Relatywna ścieżka Serato + naprawa znanego podwójnego prefixu Music/Users."""
    return collapse_serato_broken_path_prefixes(to_serato_relative_path(path))


def _rewrite_paths_in_container(data: bytes, transform) -> tuple[bytes, int]:
    """
    Prepisuje pfil/ptrk w kontenerze rekordów Serato (otrk lub top-level).
    Zachowuje pozostałe pola bajtowo. Zwraca (nowe_data, liczba_zmian).
    """
    fp = BytesIO(data)
    out = BytesIO()
    changed = 0
    while True:
        header = fp.read(8)
        if len(header) < 8:
            break
        name = header[:4].decode("ascii", errors="replace")
        length = struct.unpack(">I", header[4:8])[0]
        payload = fp.read(length)
        if len(payload) < length:
            break
        if name in ("pfil", "ptrk"):
            try:
                old = payload.decode("utf-16-be").rstrip("\x00")
            except UnicodeDecodeError:
                old = ""
            new = transform(old) if old else old
            if new != old:
                payload = _encode_utf16be(new)
                changed += 1
            _write_serato_record(out, name, payload)
        elif name in ("otrk",) or (name and name[0] in ("o", "r")):
            # zagnieżdżony kontener — recursively for otrk only to be safe
            if name == "otrk":
                new_payload, c = _rewrite_paths_in_container(payload, transform)
                changed += c
                _write_serato_record(out, name, new_payload)
            else:
                _write_serato_record(out, name, payload)
        else:
            _write_serato_record(out, name, payload)
    return out.getvalue(), changed


def normalize_serato_blob_to_relative(content: bytes) -> tuple[bytes, int]:
    """Wszystkie ścieżki w blobie (database V2 / .crate) → bez wiodącego / + fix podwójnego prefixu."""
    return _rewrite_paths_in_container(content, canonical_serato_relative_path)


def _rewrite_genres_in_otrk(
    otrk_payload: bytes,
    path_to_genre: dict[str, str],
) -> tuple[bytes, int]:
    """W otrk podmienia tgen gdy ścieżka jest w path_to_genre (klucz = identity)."""
    fp = BytesIO(otrk_payload)
    out = BytesIO()
    changed = 0
    track_path = ""
    fields: list[tuple[str, bytes]] = []
    while True:
        header = fp.read(8)
        if len(header) < 8:
            break
        name = header[:4].decode("ascii", errors="replace")
        length = struct.unpack(">I", header[4:8])[0]
        payload = fp.read(length)
        if len(payload) < length:
            break
        if name in ("pfil", "ptrk"):
            try:
                track_path = payload.decode("utf-16-be").rstrip("\x00")
            except UnicodeDecodeError:
                track_path = ""
        fields.append((name, payload))

    key = serato_path_identity_key(to_serato_relative_path(track_path)) if track_path else ""
    new_genre = path_to_genre.get(key) if key else None
    if new_genre is None:
        return otrk_payload, 0

    genre_bytes = _encode_utf16be(new_genre)
    wrote_tgen = False
    for name, payload in fields:
        if name == "tgen":
            if payload != genre_bytes:
                changed = 1
            _write_serato_record(out, name, genre_bytes)
            wrote_tgen = True
        else:
            _write_serato_record(out, name, payload)
    if not wrote_tgen and new_genre:
        _write_serato_record(out, "tgen", genre_bytes)
        changed = 1
    return out.getvalue(), changed


def _rewrite_genres_in_database(
    content: bytes,
    path_to_genre: dict[str, str],
) -> tuple[bytes, int]:
    """Podmienia tgen w database V2 wg mapy ścieżka→genre (kotwice §tag§)."""
    fp = BytesIO(content)
    out = BytesIO()
    changed = 0
    while True:
        header = fp.read(8)
        if len(header) < 8:
            break
        name = header[:4].decode("ascii", errors="replace")
        length = struct.unpack(">I", header[4:8])[0]
        payload = fp.read(length)
        if len(payload) < length:
            break
        if name == "otrk":
            new_payload, c = _rewrite_genres_in_otrk(payload, path_to_genre)
            changed += c
            _write_serato_record(out, name, new_payload)
        else:
            _write_serato_record(out, name, payload)
    return out.getvalue(), changed


def sync_serato_genres_from_vdj(
    songs: list[dict],
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Wpisuje do Serato database V2 Genre = Genre+User1+User2 VDJ + kotwice §tag§.
    Dzięki temu Smart Crates (User 2 has tag 1 itd.) widzą te same tagi co VDJ.
    Robi kopię .bak. Serato musi być zamknięty.
    """
    from datetime import datetime

    from serato_smart_crate import build_serato_genre_field

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    db_file = base / "database V2"
    if not db_file.is_file():
        db_file = base / "Database V2"
    if not db_file.is_file():
        return {"ok": False, "error": f"Brak database V2 w {base}"}

    path_to_genre: dict[str, str] = {}
    for s in songs or []:
        raw = (s.get("FilePath") or "").strip()
        if not raw:
            continue
        rel = to_serato_relative_path(
            _path_to_serato_relative(raw, None, path_style="relative") or raw
        )
        key = serato_path_identity_key(rel)
        if not key:
            continue
        genre = build_serato_genre_field(
            s.get("Tags.Genre") or "",
            s.get("Tags.User1") or "",
            s.get("Tags.User2") or "",
        )
        if genre:
            path_to_genre[key] = genre

    raw = db_file.read_bytes()
    new_blob, n = _rewrite_genres_in_database(raw, path_to_genre)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = Path(str(db_file) + f".pre-genre-sync-{stamp}.bak")
    result = {
        "ok": True,
        "updated": n,
        "mapped_songs": len(path_to_genre),
        "dry_run": dry_run,
        "backup": str(bak) if not dry_run else "",
    }
    if dry_run or n == 0:
        return result
    bak.write_bytes(raw)
    db_file.write_bytes(new_blob)
    return result


def _build_otrk_payload(s: dict, path: str, now: int) -> bytes:
    """Jeden rekord otrk (wewnętrzny blob) dla utworu VDJ."""
    from serato_smart_crate import build_serato_genre_field

    title = (s.get("Tags.Title") or s.get("Tags.Author") or "").strip() or Path(path).stem
    artist = (s.get("Tags.Author") or s.get("Tags.Artist") or "").strip()
    bpm = 0.0
    # Preferuj BPM z beatgrid (jak w vdj_adapter) — Tags.Bpm bywa 60/bpm
    for xml_str in s.get("_children_xml") or []:
        if "beatgrid" not in xml_str or "Bpm=" not in xml_str:
            continue
        try:
            import re as _re

            m = _re.search(r'Bpm="([0-9.]+)"', xml_str)
            if m:
                bg = float(m.group(1))
                if 20 <= bg <= 300:
                    bpm = bg
                    break
        except (TypeError, ValueError):
            pass
    try:
        bpm_raw = s.get("Tags.Bpm", "")
        if bpm_raw and not bpm:
            val = float(bpm_raw)
            bpm = 60.0 / val if 0.2 <= val <= 2.0 else (val if 20 <= val <= 300 else 0.0)
    except (TypeError, ValueError):
        pass
    key_str = (s.get("Tags.Key") or "").strip()
    if not bpm or not key_str:
        try:
            from vdj_adapter import _parse_scan_bpm, _parse_scan_key

            children = s.get("_children_xml") or []
            if not bpm:
                bpm = _parse_scan_bpm(children) or 0.0
            if not key_str:
                key_str = _parse_scan_key(children) or ""
        except Exception:
            pass
    duration_sec = 0.0
    try:
        duration_sec = float(s.get("Infos.SongLength") or s.get("Infos.Duration") or 0)
    except (TypeError, ValueError):
        pass
    otrk = BytesIO()
    _write_serato_record(otrk, "pfil", _encode_utf16be(path))
    if title:
        _write_serato_record(otrk, "tsng", _encode_utf16be(title))
    if artist:
        _write_serato_record(otrk, "tart", _encode_utf16be(artist))
    album = (s.get("Tags.Album") or "").strip()
    if album:
        _write_serato_record(otrk, "talb", _encode_utf16be(album))
    remix = (s.get("Tags.Remix") or "").strip()
    if remix:
        _write_serato_record(otrk, "trem", _encode_utf16be(remix))
    if bpm > 0:
        _write_serato_record(otrk, "tbpm", _encode_utf16be(f"{bpm:.2f}"))
    if key_str:
        _write_serato_record(otrk, "tkey", _encode_utf16be(key_str))
    if duration_sec > 0:
        m = int(duration_sec // 60)
        s_sec = duration_sec % 60
        _write_serato_record(otrk, "tlen", _encode_utf16be(f"{m:02d}:{s_sec:05.2f}"))
    ext = Path(path).suffix.lower().lstrip(".")
    if ext:
        _write_serato_record(otrk, "ttyp", _encode_utf16be(ext))
    tbit = s.get("Infos.Bitrate") or s.get("Tags.Bitrate") or ""
    if tbit:
        try:
            br = int(float(tbit))
            _write_serato_record(otrk, "tbit", _encode_utf16be(f"{br}.0kbps"))
        except (TypeError, ValueError):
            pass
    tsmp = s.get("Infos.SampleRate") or ""
    if tsmp:
        try:
            sr = float(tsmp)
            _write_serato_record(otrk, "tsmp", _encode_utf16be(f"{sr/1000:.1f}k" if sr >= 1000 else f"{sr}k"))
        except (TypeError, ValueError):
            pass
    genre_str = build_serato_genre_field(
        s.get("Tags.Genre") or "",
        s.get("Tags.User1") or "",
        s.get("Tags.User2") or "",
    )
    if genre_str:
        _write_serato_record(otrk, "tgen", _encode_utf16be(genre_str))
    comment = _get_comment_from_song(s)
    # Rating NIE idzie do tcom — Serato czyta ★ z tagów pliku (POPM / rate) i Library SQLite.
    if comment:
        c = comment.strip()
        if " | Rating: " in c:
            c = c.split(" | Rating: ", 1)[0].strip()
        elif c.startswith("Rating: ") and c[8:].strip().isdigit():
            c = ""
        if c:
            _write_serato_record(otrk, "tcom", _encode_utf16be(c))
    play_count = 0
    try:
        play_count = max(0, int(s.get("Infos.PlayCount") or s.get("PlayCount") or 0))
    except (TypeError, ValueError):
        pass
    _write_serato_record(otrk, "utpc", struct.pack(">I", play_count))
    _write_serato_record(otrk, "tadd", _encode_utf16be(str(now)))
    _write_serato_record(otrk, "uadd", struct.pack(">I", now))
    _write_serato_record(otrk, "utme", struct.pack(">I", now))
    _write_serato_record(otrk, "bmis", struct.pack("?", False))
    return otrk.getvalue()


def _database_path_keys(content: bytes) -> set[str]:
    """Zwraca klucze tożsamości ścieżek już obecnych w database V2."""
    records = _parse_serato_records(BytesIO(content))
    keys: set[str] = set()
    for name, value in records:
        if name != "otrk" or not isinstance(value, list):
            continue
        path = ""
        for field, val in value:
            if field in ("pfil", "ptrk") and isinstance(val, str):
                path = val
        if path:
            key = serato_path_identity_key(to_serato_relative_path(path))
            if key:
                keys.add(key)
    return keys


def _append_otrks_to_database(content: bytes, otrk_payloads: list[bytes]) -> bytes:
    if not otrk_payloads:
        return content
    fp = BytesIO(content)
    out = BytesIO()
    while True:
        header = fp.read(8)
        if len(header) < 8:
            break
        name = header[:4].decode("ascii", errors="replace")
        length = struct.unpack(">I", header[4:8])[0]
        payload = fp.read(length)
        _write_serato_record(out, name, payload)
    for payload in otrk_payloads:
        _write_serato_record(out, "otrk", payload)
    return out.getvalue()


def _manifest_entry_to_vdj_song(entry: dict) -> dict:
    """Minimalny rekord VDJ z wpisu manifestu (gdy brak dopasowania w bazie VDJ)."""
    return {
        "FilePath": (entry.get("path") or "").strip(),
        "Tags.Author": entry.get("author") or "",
        "Tags.Title": entry.get("title") or "",
    }


def merge_vdj_tracks_into_serato_database(
    songs: list[dict],
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
    path_substitutes: Optional[dict[str, str]] = None,
    path_replace: Optional[dict[str, str]] = None,
) -> dict:
    """
    Dodaje brakujące lokalne utwory z VDJ do database V2 (z tagami/kotwicami §tag§).
    Smart Crates widzą tylko utwory w bazie Serato — bez tego listy są niepełne.

    path_substitutes: mapowanie Tidal/cache VDJ → lokalny NJR (manifest) lub tidal:tracks:ID.
    Lokalne pliki z manifestu mają pierwszeństwo przed streamingiem Tidal w bazie Serato.
    """
    import time
    from datetime import datetime

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    db_file = base / "database V2"
    if not db_file.is_file():
        db_file = base / "Database V2"
    if not db_file.is_file():
        return {"ok": False, "error": f"Brak database V2 w {base}"}

    raw = db_file.read_bytes()
    existing = _database_path_keys(raw)
    now = int(time.time())
    new_payloads: list[bytes] = []
    skipped_missing = 0
    skipped_nonlocal = 0
    added_local = 0
    added_streaming = 0
    added_manifest = 0

    def _add_song_to_db(s: dict, export_path: str) -> None:
        nonlocal skipped_missing, added_local, added_streaming
        from vdj_streaming import is_serato_tidal_path

        if is_serato_tidal_path(export_path):
            # Streaming nie do database V2 — tylko Library SQLite
            return
        db_path = _path_to_serato_relative(export_path, None, path_style="relative")
        if not db_path:
            return
        key = serato_path_identity_key(db_path)
        if not serato_path_exists_on_disk(db_path):
            skipped_missing += 1
            return
        if not key or key in existing:
            return
        new_payloads.append(_build_otrk_payload(s, db_path, now))
        existing.add(key)
        added_local += 1

    for s in songs or []:
        raw_path = (s.get("FilePath") or "").strip()
        if not raw_path:
            continue
        resolved = resolve_serato_export_path(
            raw_path,
            path_replace,
            path_substitutes,
            song=s,
        )
        if resolved:
            _add_song_to_db(s, resolved)
            continue
        if is_serato_crate_local_path(raw_path):
            local = resolve_local_audio_path(raw_path, path_replace)
            if local:
                _add_song_to_db(s, local)
            else:
                skipped_missing += 1
            continue
        skipped_nonlocal += 1

    try:
        from tidal_download import manifest_tracks
        from tidal_vdj_metadata import _song_tidal_id, _vdj_song_score, find_vdj_song_for_tidal_id

        tid_index: dict[str, list[dict]] = {}
        for s in songs or []:
            tid = _song_tidal_id(s)
            if tid:
                tid_index.setdefault(str(tid), []).append(s)

        for tid, entry in (manifest_tracks() or {}).items():
            path = (entry.get("path") or "").strip()
            if not path or not Path(path).is_file():
                continue
            rel = _path_to_serato_relative(path, None, path_style="relative")
            if not rel:
                continue
            key = serato_path_identity_key(rel)
            if not key or key in existing:
                continue
            matches = tid_index.get(str(tid), [])
            if matches:
                song = max(matches, key=_vdj_song_score)
            else:
                song = find_vdj_song_for_tidal_id(
                    tid,
                    songs or [],
                    author=entry.get("author") or "",
                    title=entry.get("title") or "",
                ) or _manifest_entry_to_vdj_song(entry)
            new_payloads.append(_build_otrk_payload(song, rel, now))
            existing.add(key)
            added_manifest += 1
            added_local += 1
    except ImportError:
        pass

    result = {
        "ok": True,
        "added": len(new_payloads),
        "added_local": added_local,
        "added_streaming": added_streaming,
        "added_manifest": added_manifest,
        "skipped_missing_file": skipped_missing,
        "skipped_nonlocal": skipped_nonlocal,
        "existing_before": len(_database_path_keys(raw)),
        "dry_run": dry_run,
    }
    if dry_run or not new_payloads:
        return result

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = Path(str(db_file) + f".pre-merge-vdj-{stamp}.bak")
    bak.write_bytes(raw)
    merged = _append_otrks_to_database(raw, new_payloads)
    db_file.write_bytes(merged)
    result["backup"] = str(bak)
    result["total_after"] = len(_database_path_keys(merged))
    return result


def upsert_otrks_in_serato_database(
    items: list[tuple[dict, str]],
    serato_dir: Optional[Path] = None,
) -> dict:
    """
    Podmienia lub dodaje rekordy otrk w database V2 dla lokalnych plików.
    items: [(vdj_song, local_path), ...]
    """
    import time
    from datetime import datetime

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    db_file = base / "database V2"
    if not db_file.is_file():
        db_file = base / "Database V2"
    if not db_file.is_file():
        return {"ok": False, "error": f"Brak database V2 w {base}"}

    now = int(time.time())
    wanted: dict[str, bytes] = {}
    for song, path in items or []:
        p = (path or "").strip()
        if not p or not Path(p).is_file():
            continue
        rel = _path_to_serato_relative(p, None, path_style="relative")
        if not rel:
            continue
        key = serato_path_identity_key(rel)
        if not key:
            continue
        wanted[key] = _build_otrk_payload(song, rel, now)
    if not wanted:
        return {"ok": True, "replaced": 0, "added": 0}

    raw = db_file.read_bytes()
    fp = BytesIO(raw)
    out = BytesIO()
    replaced = 0
    seen: set[str] = set()
    while True:
        header = fp.read(8)
        if len(header) < 8:
            break
        name = header[:4].decode("ascii", errors="replace")
        length = struct.unpack(">I", header[4:8])[0]
        payload = fp.read(length)
        if name != "otrk":
            _write_serato_record(out, name, payload)
            continue
        rec_path = ""
        inner = BytesIO(payload)
        while True:
            h2 = inner.read(8)
            if len(h2) < 8:
                break
            n2 = h2[:4].decode("ascii", errors="replace")
            l2 = struct.unpack(">I", h2[4:8])[0]
            d2 = inner.read(l2)
            if n2 in ("pfil", "ptrk"):
                try:
                    rec_path = d2.decode("utf-16-be").rstrip("\x00")
                except UnicodeDecodeError:
                    rec_path = ""
                break
        key = serato_path_identity_key(to_serato_relative_path(rec_path)) if rec_path else ""
        if key and key in wanted:
            _write_serato_record(out, "otrk", wanted[key])
            seen.add(key)
            replaced += 1
        else:
            _write_serato_record(out, name, payload)

    added = 0
    for key, payload in wanted.items():
        if key in seen:
            continue
        _write_serato_record(out, "otrk", payload)
        added += 1

    if replaced or added:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = Path(str(db_file) + f".pre-upsert-meta-{stamp}.bak")
        bak.write_bytes(raw)
        db_file.write_bytes(out.getvalue())
        return {"ok": True, "replaced": replaced, "added": added, "backup": str(bak)}
    return {"ok": True, "replaced": 0, "added": 0}

def normalize_and_dedupe_serato_library(
    serato_dir: Optional[Path] = None,
    *,
    purge_stale: bool = True,
) -> dict:
    """
    1) Przepisz database V2 + .crate na ścieżki relatywne (Users/…).
    2) Usuń klony /Users vs Users.
    3) (purge_stale) Zmapuj stare ścieżki (Inne komputery/G:/Volumes/osx/Mój dysk)
       na Desktop; usuń martwe duble po nazwie pliku; wyrzuć osierocone missing.
    Robi kopię .bak database V2. Serato musi być zamknięty.
    """
    from datetime import datetime

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    db_file = base / "database V2"
    if not db_file.is_file():
        db_file = base / "Database V2"
    if not db_file.is_file():
        raise FileNotFoundError(f"Brak database V2 w {base}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stats: dict = {
        "db_path_rewrites": 0,
        "crate_files": 0,
        "crate_path_rewrites": 0,
        "removed_clones": 0,
        "remapped_stale": 0,
        "removed_stale": 0,
        "kept": 0,
        "backups": [],
    }

    raw = db_file.read_bytes()
    bak = Path(str(db_file) + f".pre-normalize-{stamp}.bak")
    bak.write_bytes(raw)
    stats["backups"].append(str(bak))

    norm, n_rew = normalize_serato_blob_to_relative(raw)
    stats["db_path_rewrites"] = n_rew
    cleaned, dstats = dedupe_serato_database_v2(norm, prefer_style="relative")
    stats["removed_clones"] = dstats.get("removed", 0)
    stats["kept"] = dstats.get("kept", 0)
    stats["original"] = dstats.get("original", 0)

    path_redirects: dict[str, str] = {}
    if purge_stale:
        cleaned2, pst = purge_serato_stale_duplicates(cleaned)
        stats["remapped_stale"] = pst.get("remapped", 0)
        stats["removed_stale"] = pst.get("removed", 0)
        stats["kept"] = pst.get("kept", stats["kept"])
        path_redirects = pst.get("redirects") or {}
        cleaned = cleaned2

    db_file.write_bytes(cleaned)

    sub = base / "Subcrates"
    if sub.is_dir():
        for cf in sub.glob("*.crate"):
            try:
                craw = cf.read_bytes()
                cnorm, crew = normalize_serato_blob_to_relative(craw)
                if path_redirects:
                    cnorm2, nred = _apply_path_redirects_to_blob(cnorm, path_redirects)
                    crew += nred
                    cnorm = cnorm2
                if crew or cnorm != craw:
                    cf.write_bytes(cnorm)
                    stats["crate_files"] += 1
                    stats["crate_path_rewrites"] += crew
            except Exception:
                continue

    return stats


def serato_path_exists_on_disk(path: str) -> bool:
    """Czy ścieżka Serato wskazuje istniejący plik lokalny."""
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return False
    from vdj_streaming import is_serato_tidal_path

    if is_serato_tidal_path(p):
        return True
    if "://" in p[:64] or p.startswith("clouddrive:"):
        return False
    if len(p) >= 2 and p[1] == ":":
        return False
    if p.startswith("/"):
        return Path(p).is_file()
    if p.startswith("Users/") or p.startswith("Volumes/"):
        return Path("/" + p).is_file()
    return False


def apply_serato_path_replace(
    path: str,
    path_replace: Optional[dict[str, str]] = None,
) -> str:
    p = (path or "").strip().replace("\\", "/")
    if not p or not path_replace:
        return p
    for old, new in path_replace.items():
        old_p = (old or "").strip().rstrip("/\\")
        new_p = (new or "").strip().rstrip("/\\")
        if not old_p:
            continue
        if p == old_p or p.startswith(old_p + "/"):
            return new_p + p[len(old_p):]
    return p


def resolve_local_audio_path(
    path: str,
    path_replace: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """
    Zwraca ścieżkę do istniejącego pliku audio (po opcjonalnej zamianie prefixu).
    Pomija streaming / brak pliku na dysku.
    """
    p = apply_serato_path_replace(path, path_replace)
    if not p or not is_serato_crate_local_path(p):
        return None
    candidates = [p]
    if p.startswith("/Users/"):
        parts = [x for x in p.split("/") if x]
        if len(parts) >= 3:
            home = Path.home()
            if parts[1] != home.name:
                alt = str(home / "/".join(parts[2:]))
                candidates.append(alt)
    seen: set[str] = set()
    for c in candidates:
        c = c.replace("\\", "/")
        if c in seen:
            continue
        seen.add(c)
        if Path(c).is_file():
            return c
    return None


def resolve_serato_export_path(
    path: str,
    path_replace: Optional[dict[str, str]] = None,
    path_substitutes: Optional[dict[str, str]] = None,
    *,
    song: Optional[dict] = None,
    song_by_path: Optional[dict[str, dict]] = None,
) -> Optional[str]:
    """
    Ścieżka do wpisu .crate / database V2: plik lokalny lub Tidal (Serato 4+).
    path_substitutes: Tidal/cache VDJ → mp3 lub streaming (path-first).
    song: opcjonalny rekord VDJ — mapowanie 1:1 po FilePath / linku, nie po meta.
    """
    from serato_offline import is_vdj_cache_path, lookup_serato_offline_substitute
    from vdj_path_mapping import resolve_path_first_export
    from vdj_streaming import (
        is_serato_tidal_path,
        is_tidal_path,
        vdj_to_serato_tidal_path,
    )
    from vdjfolder import normalize_path

    p = apply_serato_path_replace(path, path_replace)
    if not p:
        return None

    s = song
    if not s and song_by_path:
        s = song_by_path.get(normalize_path(p))

    if s:
        from vdj_path_mapping import build_tid_to_resolved_local, resolve_path_first_export

        if path_substitutes is not None:
            manifest_subs = path_substitutes
        else:
            try:
                from tidal_download import manifest_substitutes

                manifest_subs = manifest_substitutes()
            except (ImportError, OSError):
                manifest_subs = {}
        tid_locals = build_tid_to_resolved_local([s], path_replace=path_replace)
        export, _reason = resolve_path_first_export(
            s,
            manifest_subs=manifest_subs,
            tid_locals=tid_locals,
            path_replace=path_replace,
        )
        if export:
            if is_serato_tidal_path(export) or is_tidal_path(export):
                return vdj_to_serato_tidal_path(export) or export
            if is_vdj_cache_path(export):
                sub = lookup_serato_offline_substitute(export, path_substitutes)
                if sub:
                    export = sub
            return resolve_local_audio_path(export, path_replace) or export

    if is_vdj_cache_path(p):
        sub = lookup_serato_offline_substitute(p, path_substitutes)
        if sub:
            if is_serato_tidal_path(sub) or is_tidal_path(sub):
                return vdj_to_serato_tidal_path(sub) or sub
            return resolve_local_audio_path(sub, path_replace)
        return None
    sub = lookup_serato_offline_substitute(p, path_substitutes)
    if sub:
        if is_serato_tidal_path(sub):
            return sub
        if is_tidal_path(sub):
            return vdj_to_serato_tidal_path(sub)
        return resolve_local_audio_path(sub, path_replace)
    if is_serato_tidal_path(p):
        return p
    if is_tidal_path(p):
        return vdj_to_serato_tidal_path(p)
    return resolve_local_audio_path(p, path_replace)


def filter_track_paths_for_serato(
    paths: list[str],
    path_replace: Optional[dict[str, str]] = None,
    path_substitutes: Optional[dict[str, str]] = None,
    *,
    include_streaming: bool = False,
    song_by_path: Optional[dict[str, dict]] = None,
) -> list[str]:
    """
    Ścieżki do .crate / database V2.
    Domyślnie TYLKO lokalne pliki — Serato odrzuca streaming w zwykłych crates
    (log: Unable to determine track type … tidal:tracks / streaming w Dbv2).
    Streaming trafia do Library SQLite (serato_library_sqlite).
    """
    from vdjfolder import normalize_path
    from vdj_streaming import is_serato_tidal_path

    out: list[str] = []
    seen: set[str] = set()
    for raw in paths or []:
        vdj_song = (
            song_by_path.get(normalize_path((raw or "").strip()))
            if song_by_path
            else None
        )
        resolved = resolve_serato_export_path(
            raw,
            path_replace,
            path_substitutes,
            song=vdj_song,
            song_by_path=song_by_path,
        )
        if not resolved:
            continue
        if is_serato_tidal_path(resolved) and not include_streaming:
            continue
        key = serato_path_identity_key(
            resolved if is_serato_tidal_path(resolved) else to_serato_relative_path(resolved)
        )
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(resolved)
    return out


def map_stale_serato_path_to_desktop(path: str, desktop: Optional[Path] = None) -> Optional[str]:
    """
    Stare lokalizacje (Inne komputery / G: / Volumes/osx / Mój dysk)
    → Users/…/Desktop/… jeśli plik tam jest.
    """
    p = (path or "").strip().replace("\\", "/")
    if not p or serato_path_exists_on_disk(p):
        return None
    desk = desktop or (Path.home() / "Desktop")
    rest = None
    for pat in (
        r"(?i)^(?:G:/)?Inne komputery/[^/]+/(.*)$",
        r"(?i)^Volumes/osx/Inne komputery/[^/]+/(.*)$",
        r"(?i)^Volumes/[^/]+/Inne komputery/[^/]+/(.*)$",
        r"(?i)^Volumes/osx/Mój dysk/(.*)$",
        r"(?i)^Mój dysk/(.*)$",
    ):
        m = re.match(pat, p)
        if m:
            rest = m.group(1)
            break
    if not rest:
        return None
    cand = desk / rest
    if cand.is_file():
        s = str(cand).replace("\\", "/")
        return to_serato_relative_path(s)
    return None


def _otrk_basename(path: str) -> str:
    return Path((path or "").replace("\\", "/")).name.lower()


def purge_serato_stale_duplicates(content: bytes) -> tuple[bytes, dict]:
    """
    - Remapuje martwe ścieżki na Desktop gdy plik istnieje.
    - W grupie tej samej nazwy pliku zostawia jeden wpis (preferuj Users/…Desktop, plays).
    - Usuwa wpisy bez pliku na dysku (żółte trójkąty bez szansy).
    Zwraca (nowy blob, stats) + redirects: stara_ścieżka → nowa (do crates).
    """
    records = _iter_top_level_raw(content)
    entries: list[dict] = []
    for name, data in records:
        if name != "otrk":
            continue
        path, score = _otrk_path_and_score(data)
        path = (path or "").strip()
        if not path:
            continue
        collapsed = collapse_serato_broken_path_prefixes(path)
        if collapsed != path:
            data = _rewrite_paths_in_container(data, lambda _old, c=collapsed: c)[0]
            path = collapsed
            remapped = True
        else:
            remapped = False
        mapped = map_stale_serato_path_to_desktop(path)
        effective = mapped or path
        if mapped and mapped != path:
            data = _rewrite_paths_in_container(data, lambda _old, m=mapped: m)[0]
            path_for_key = mapped
            remapped = True
        else:
            path_for_key = path
        exists = serato_path_exists_on_disk(path_for_key)
        # score: istniejący >> Desktop >> plays
        bonus = 0
        if exists:
            bonus += 1_000_000
        pl = path_for_key.replace("\\", "/")
        fullish = pl if pl.startswith("/") else "/" + pl
        if "/Desktop/" in fullish:
            bonus += 50_000
        if "/Downloads/" in fullish:
            bonus -= 5_000
        entries.append({
            "data": data,
            "path": path,
            "effective": path_for_key,
            "exists": exists,
            "remapped": remapped,
            "score": score + bonus,
            "base": _otrk_basename(path_for_key),
        })

    # Grupuj po basename — jeden zwycięzca
    from collections import defaultdict
    by_base: dict[str, list] = defaultdict(list)
    for e in entries:
        by_base[e["base"] or e["effective"]].append(e)

    keep: list[dict] = []
    redirects: dict[str, str] = {}
    removed = 0
    remapped_n = 0
    for base, group in by_base.items():
        alive = sorted(
            [g for g in group if g["exists"]],
            key=lambda x: x["score"],
            reverse=True,
        )
        if not alive:
            removed += len(group)
            continue
        winner = alive[0]
        keep.append(winner)
        if winner["remapped"]:
            remapped_n += 1
        for loser in group:
            if loser is winner:
                continue
            removed += 1
            redirects[loser["path"]] = winner["effective"]
            redirects[loser["effective"]] = winner["effective"]
            redirects[to_serato_relative_path(loser["path"])] = winner["effective"]

    buf = BytesIO()
    vrsn = next((d for n, d in records if n == "vrsn"), None)
    if vrsn is not None:
        _write_serato_record(buf, "vrsn", vrsn)
    else:
        _write_serato_record(buf, "vrsn", _encode_utf16be("2.0/Serato Scratch LIVE Database"))
    for e in keep:
        _write_serato_record(buf, "otrk", e["data"])

    return buf.getvalue(), {
        "kept": len(keep),
        "removed": removed,
        "remapped": remapped_n,
        "redirects": redirects,
    }


def _apply_path_redirects_to_blob(content: bytes, redirects: dict[str, str]) -> tuple[bytes, int]:
    """Podmienia ptrk/pfil wg mapy stara→nowa."""
    if not redirects:
        return content, 0

    def transform(old: str) -> str:
        o = (old or "").strip().replace("\\", "/")
        if o in redirects:
            return redirects[o]
        rel = to_serato_relative_path(o)
        if rel in redirects:
            return redirects[rel]
        return o

    return _rewrite_paths_in_container(content, transform)


def serato_path_identity_key(path: str) -> str:
    """
    Klucz tożsamości ścieżki Serato: `/Users/x/a.mp3` i `Users/x/a.mp3` = ten sam plik.
    (Eksport z driveRoot=/ daje relatywne Users/…; istniejąca baza bywa absolutna.)
    """
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return ""
    if p.startswith("/"):
        p = p[1:]
    return p.lower()


def detect_serato_path_style(paths: list[str]) -> str:
    """
    Dominujący styl ścieżek w Database V2 / crate.
    Zwraca: 'absolute' | 'relative' | 'unknown'
    """
    abs_n = 0
    rel_n = 0
    for raw in paths or []:
        p = (raw or "").strip().replace("\\", "/")
        if not p:
            continue
        if p.startswith("/"):
            abs_n += 1
        elif p.startswith("Users/") or p.startswith("Volumes/") or (len(p) >= 2 and p[1] == ":"):
            # Users/… (mac), Volumes/… albo Windows bez litery z rootem
            rel_n += 1
        elif "/" in p or "\\" in raw:
            rel_n += 1
    if abs_n == 0 and rel_n == 0:
        return "unknown"
    if abs_n >= rel_n:
        return "absolute"
    return "relative"


def detect_serato_library_path_style(serato_dir: Optional[Path] = None) -> str:
    """Styl ścieżek w ~/Music/_Serato_/database V2 (lub podanym folderze)."""
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    db_file = base / "database V2"
    if not db_file.is_file():
        db_file = base / "Database V2"
    if not db_file.is_file():
        return "unknown"
    paths: list[str] = []
    try:
        for name, data in _iter_top_level_raw(db_file.read_bytes()):
            if name != "otrk":
                continue
            for n, v in _parse_serato_records(BytesIO(data)):
                if n in ("pfil", "ptrk") and isinstance(v, str) and v.strip():
                    paths.append(v.strip())
                    break
    except Exception:
        return "unknown"
    return detect_serato_path_style(paths)


def _iter_top_level_raw(content: bytes) -> list[tuple[str, bytes]]:
    """Top-level rekordy Serato jako (tag, surowe data) — bez zagnieżdżania."""
    fp = BytesIO(content)
    out: list[tuple[str, bytes]] = []
    while True:
        header = fp.read(8)
        if len(header) < 8:
            break
        name = header[:4].decode("ascii", errors="replace")
        length = struct.unpack(">I", header[4:8])[0]
        data = fp.read(length)
        if len(data) < length:
            break
        out.append((name, data))
    return out


def _otrk_path_and_score(otrk_data: bytes) -> tuple[str, int]:
    """Ścieżka + score (plays*10 + rating) do wyboru lepszego klona."""
    path = ""
    plays = 0
    rating = 0
    for n, v in _parse_serato_records(BytesIO(otrk_data)):
        if n in ("pfil", "ptrk") and isinstance(v, str) and v.strip() and not path:
            path = v.strip()
        elif n == "utpc":
            try:
                plays = int(v) if v is not None else 0
            except (TypeError, ValueError):
                plays = 0
        elif n == "tcom" and isinstance(v, str) and " | Rating: " in v:
            try:
                rating = min(5, max(0, int(v.split(" | Rating: ", 1)[1].strip())))
            except (ValueError, IndexError):
                pass
        elif n == "tcom" and isinstance(v, str) and v.strip().startswith("Rating: "):
            try:
                rating = min(5, max(0, int(v.strip().split("Rating: ", 1)[1].strip())))
            except (ValueError, IndexError):
                pass
    # Preferuj relatywną (kanoniczna Serato) przy remisie — absolutna generuje klony przy play
    rel_bonus = 1 if path and not path.startswith("/") else 0
    return path, plays * 10 + rating + rel_bonus


def dedupe_serato_database_v2(
    content: bytes,
    *,
    prefer_style: Optional[str] = None,
) -> tuple[bytes, dict]:
    """
    Usuwa klony tego samego pliku różniące się tylko `/Users/...` vs `Users/...`.
    Zostawia wpis z wyższym play count / rating (przy remisie: prefer_style lub absolute).
    Zwraca (nowe_bajty, stats).
    """
    records = _iter_top_level_raw(content)
    best: dict[str, tuple[int, bytes, str]] = {}
    order: list[str] = []
    skipped = 0
    for name, data in records:
        if name != "otrk":
            continue
        path, score = _otrk_path_and_score(data)
        key = serato_path_identity_key(path)
        if not key:
            skipped += 1
            continue
        if prefer_style == "absolute" and path.startswith("/"):
            score += 100000
        elif prefer_style == "relative" and path and not path.startswith("/"):
            score += 100000
        prev = best.get(key)
        if prev is None:
            best[key] = (score, data, path)
            order.append(key)
        elif score > prev[0]:
            best[key] = (score, data, path)
            skipped += 1
        else:
            skipped += 1

    buf = BytesIO()
    # zachowaj vrsn jeśli był
    vrsn = next((d for n, d in records if n == "vrsn"), None)
    if vrsn is not None:
        _write_serato_record(buf, "vrsn", vrsn)
    else:
        _write_serato_record(buf, "vrsn", _encode_utf16be("2.0/Serato Scratch LIVE Database"))
    for key in order:
        _write_serato_record(buf, "otrk", best[key][1])
    kept = len(order)
    original = sum(1 for n, _ in records if n == "otrk")
    return buf.getvalue(), {
        "original": original,
        "kept": kept,
        "removed": max(0, original - kept),
        "skipped_empty": skipped if kept == original else 0,
    }


def _path_to_serato_relative(
    path: str,
    drive_root: Optional[str] = None,
    *,
    path_style: Optional[str] = None,
) -> str:
    """
    Konwertuje ścieżkę na format Serato.
    Domyślnie (path_style != 'absolute'): względna do roota dysku, bez wiodącego `/`
    — np. Users/test/Desktop/a.mp3. Absolutne /Users/… powodują klony przy play w Serato.
    drive_root: np. C:\\, / (macOS), /Volumes/DriveName/
    """
    p = (path or "").strip()
    if not p:
        return ""
    p_norm = p.replace("\\", "/")
    style = (path_style or "relative").strip().lower()
    if style == "absolute":
        return p_norm
    if drive_root is not None and (drive_root or "").strip():
        root = (drive_root or "").strip().rstrip("/\\")
        root_norm = (root.replace("\\", "/") + "/") if root else "/"
        if root_norm == "/":
            if p_norm.startswith("/"):
                p = p_norm[1:].lstrip("/")
            else:
                p = p_norm
        elif root:
            if p_norm.lower().startswith(root_norm.lower()):
                p = p_norm[len(root_norm):].lstrip("/")
            elif len(p) > len(root) and (
                p.replace("/", "\\").lower().startswith(root.lower() + "\\")
                or p.lower().startswith(root.lower() + "/")
            ):
                p = p[len(root):].lstrip("\\/")
            else:
                p = p_norm
        else:
            p = p_norm
    else:
        p = p_norm
    # Zawsze kanoniczna forma Serato (bez leading /)
    return to_serato_relative_path(p.replace("\\", "/"))


def _song_export_score(s: dict) -> int:
    """Wyższy = lepszy kandydat przy dedupe eksportu."""
    plays = 0
    rating = 0
    try:
        plays = max(0, int(s.get("Infos.PlayCount") or s.get("PlayCount") or 0))
    except (TypeError, ValueError):
        pass
    try:
        raw = s.get("Tags.Stars") or s.get("Infos.Rating") or s.get("Tags.Rating") or 0
        if raw is not None and str(raw).strip():
            val = int(float(raw))
            rating = min(5, max(0, val // 51 if val > 5 else val))
    except (TypeError, ValueError):
        pass
    return plays * 10 + rating


def save_serato_database_v2(
    songs: list[dict],
    drive_root: Optional[str] = None,
    *,
    path_style: Optional[str] = None,
) -> bytes:
    """
    Generuje plik DatabaseV2 Serato z listy _songs (VDJ-style).
    drive_root: root dysku – ścieżki względne. Mac główny: /. Zewnętrzny: /Volumes/Nazwa/.
    path_style: domyślnie 'relative' (Users/… bez /).
    Deduplikuje po tożsamości ścieżki (/Users/x ≡ Users/x).
    Cue: serato_markers / writeCues — nie w Database V2.
    """
    import time
    style = (path_style or "relative").strip().lower()
    # Wybierz lepszy utwór przy kolizji ścieżki
    best: dict[str, tuple[int, dict, str]] = {}
    order: list[str] = []
    for s in songs or []:
        from vdj_streaming import is_tidal_path, vdj_to_serato_tidal_path

        raw_fp = (s.get("FilePath") or "").strip()
        if is_tidal_path(raw_fp):
            path = vdj_to_serato_tidal_path(raw_fp) or ""
        else:
            path = _path_to_serato_relative(
                raw_fp,
                drive_root,
                path_style=style,
            )
        if not path:
            continue
        key = serato_path_identity_key(path)
        if not key:
            continue
        score = _song_export_score(s)
        prev = best.get(key)
        if prev is None:
            best[key] = (score, s, path)
            order.append(key)
        elif score > prev[0]:
            best[key] = (score, s, path)

    buf = BytesIO()
    _write_serato_record(buf, "vrsn", _encode_utf16be("2.0/Serato Scratch LIVE Database"))
    now = int(time.time())
    for key in order:
        _, s, path = best[key]
        _write_serato_record(buf, "otrk", _build_otrk_payload(s, path, now))
    return buf.getvalue()


def save_serato_crate(
    track_paths: list[str],
    crate_name: str,
    drive_root: Optional[str] = None,
    *,
    path_style: Optional[str] = None,
    path_replace: Optional[dict[str, str]] = None,
    path_substitutes: Optional[dict[str, str]] = None,
    existing_files_only: bool = True,
) -> bytes:
    """Generuje plik .crate. Ścieżki relative; bez duplikatów (/Users ≡ Users).
    Utwory Tidal (streaming://tidal/ID) — NIE trafiają do .crate
    (Serato je odrzuca); zapis przez serato_library_sqlite.
    existing_files_only: True — tylko istniejące pliki lokalne.
    """
    style = (path_style or "relative").strip().lower()
    if existing_files_only:
        track_paths = filter_track_paths_for_serato(
            track_paths, path_replace, path_substitutes
        )
    elif path_replace:
        track_paths = [
            apply_serato_path_replace(p, path_replace) for p in (track_paths or [])
        ]
    buf = BytesIO()
    _write_serato_record(buf, "vrsn", _encode_utf16be("1.0/Serato ScratchLive Crate"))
    seen: set[str] = set()
    for path in track_paths or []:
        raw = (path or "").strip()
        if not raw:
            continue
        if existing_files_only:
            raw = resolve_serato_export_path(raw, path_replace, path_substitutes) or ""
            if not raw:
                continue
        elif path_replace:
            raw = apply_serato_path_replace(raw, path_replace)

        from vdj_streaming import is_serato_tidal_path

        if is_serato_tidal_path(raw):
            p = raw
        elif not is_serato_crate_local_path(raw):
            continue
        else:
            p = _path_to_serato_relative(
                raw,
                drive_root,
                path_style=style,
            )
        if not p:
            continue
        key = serato_path_identity_key(
            p if is_serato_tidal_path(p) else to_serato_relative_path(p)
        )
        if not key or key in seen:
            continue
        seen.add(key)
        otrk = BytesIO()
        _write_serato_record(otrk, "ptrk", _encode_utf16be(p))
        _write_serato_record(buf, "otrk", otrk.getvalue())
    return buf.getvalue()


def serato_library_exists(serato_dir: Optional[Path] = None) -> bool:
    """Czy istnieje lokalna baza Serato (database V2)."""
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    return (base / "database V2").is_file() or (base / "Database V2").is_file()


SERATO_EXPORT_INSTALL_TXT = """NJR Konwerter — eksport Serato
================================

Zalecane (istniejąca biblioteka Serato):
1. Zamknij Serato DJ (Cmd+Q / Quit).
2. Skopiuj pliki z Subcrates/ do:
   ~/Music/_Serato_/Subcrates/
   (nadpisz crates o tych samych nazwach — OK).
3. NIE kopiuj / NIE nadpisuj „database V2” — zostaw swoją bazę
   (chyba że celowo robisz nową bibliotekę).
4. Otwórz Serato. Crates pojawią się w drzewie VDJ / MyLists / …
   (hierarchia w nazwach plików: VDJ%%MyLists%%gatunki%%…).

Nowa biblioteka (pusta Serato):
- Skopiuj cały folder _Serato_/ (database V2 + Subcrates).

Filter listy VDJ są eksportowane jako zwykłe playlisty (snapshot
aktualnych utworów z bazy), nie jako Smart Crates.

WAŻNE — usuń stare Smart Crates VDJ (inaczej Serato pokaże oba):
  find ~/Music/_Serato_/SmartCrates -name 'VDJ*.scrate' -delete
albo użyj przycisku „Instaluj crates” w konwerterze (robi to automatycznie).

Ścieżki w eksporcie są w formacie Serato: Users/…/plik.mp3 (bez wiodącego /).
Utwory Tidal online: streaming://tidal/ID w Serato Library SQLite
(nie w .crate — Serato czyści tidal:tracks z zwykłych crates).
Wymaga zalogowanego TIDAL z DJ Extension.

Hot cues są w tagach plików audio (Markers2), nie w database V2.
"""


# Hierarchia Smart Crates w Serato (nie %% — to jest dla zwykłych Subcrates)
SERATO_SMART_SEP = "\u226b\u226b"  # ≫≫


def safe_serato_crate_segment(name: str) -> str:
    """Segment nazwy crate (bez %% / ≫≫ — to separatory hierarchii)."""
    s = (name or "").strip()
    s = s.replace(SERATO_SMART_SEP, " ").replace("%%", " ").replace("%", "_")
    s = "".join(c if (c.isalnum() or c in " -_.") else "_" for c in s)
    s = s.strip("._ ") or "crate"
    return s[:80]


def serato_smart_crate_stem(
    parts: tuple[str, ...],
    used: Optional[set[str]] = None,
) -> str:
    """
    Nazwa pliku Smart Crate z hierarchią Serato: VDJ≫≫MyLists≫≫gatunki≫≫TECHNO _1
    (separator ≫≫ — %% jest tylko dla zwykłych Subcrates).
    """
    used = used if used is not None else set()
    segs = [safe_serato_crate_segment(p) for p in parts if (p or "").strip()]
    if not segs:
        return "smart"
    stem = SERATO_SMART_SEP.join(segs)
    key = stem.lower()
    if key not in used:
        used.add(key)
        return stem[:200]
    n = 2
    base = stem[:180]
    while f"{base} ({n})".lower() in used:
        n += 1
    final = f"{base} ({n})"
    used.add(final.lower())
    return final


def serato_smart_crate_display_stem(
    parts: tuple[str, ...],
    used: Optional[set[str]] = None,
) -> str:
    """Alias wsteczny — hierarchiczna nazwa Smart Crate (≫≫)."""
    return serato_smart_crate_stem(parts, used)


def serato_smart_crate_leaf(stem: str) -> str:
    """Liść nazwy Smart Crate (po ostatnim ≫≫ / %% / „ - ”)."""
    s = (stem or "").strip()
    if SERATO_SMART_SEP in s:
        return s.split(SERATO_SMART_SEP)[-1].strip()
    if "%%" in s:
        return s.split("%%")[-1].strip()
    if " - " in s:
        return s.split(" - ")[-1].strip()
    return s


def iter_serato_crate_files(
    playlists: list,
    *,
    prefix: tuple[str, ...] = (),
) -> list[tuple[str, list[str]]]:
    """
    Spłaszcza drzewo Playlist → lista (stem pliku .crate, track_ids).
    Hierarchia Serato Subcrates: Parent%%Child%%Leaf.crate
    """
    out: list[tuple[str, list[str]]] = []
    seen: set[str] = set()

    def ensure_stem(stem: str, tracks: list[str]) -> None:
        if stem not in seen:
            seen.add(stem)
            out.append((stem, tracks))
            return
        if tracks:
            for i, (s, t) in enumerate(out):
                if s == stem and not t and tracks:
                    out[i] = (stem, tracks)
                    break

    def walk(nodes: list, parts: tuple[str, ...]) -> None:
        for pl in nodes or []:
            seg = safe_serato_crate_segment(getattr(pl, "name", "") or "")
            path_parts = parts + (seg,)
            stem = "%%".join(path_parts)
            children = list(getattr(pl, "children", None) or [])
            tracks = [t for t in (getattr(pl, "track_ids", None) or []) if t]

            ensure_stem(stem, tracks)
            if children:
                walk(children, path_parts)

    walk(playlists, prefix)
    return out


def is_vdj_filter_tree_serato_stem(stem: str) -> bool:
    """True dla Subcrates z drzew Sideview / Folders / Filters (nie przenosimy do Serato)."""
    s = (stem or "").strip().replace("\\", "/")
    if not s:
        return False
    if s.upper().startswith("VDJ%%"):
        s = s[len("VDJ%%") :]
    if not s or s.upper() == "VDJ":
        return False
    first = s.split("%%", 1)[0].strip().lower()
    return first in ("sideview", "folders", "filters")


def normalize_serato_mylists_stem(stem: str) -> Optional[str]:
    """
    Jedno drzewo w Serato: MyLists/…, „wszystkie pliki”, „VDJ Offline Cache”.
    VDJ%%MyLists%%X → MyLists%%X; sam „VDJ” lub drzewa filtrów → None (pomijamy).
    """
    s = (stem or "").strip()
    if not s:
        return None
    if s == "VDJ":
        return None
    if s.startswith("VDJ%%"):
        s = s[len("VDJ%%") :]
    if not s or s == "VDJ":
        return None
    if is_vdj_filter_tree_serato_stem(s):
        return None
    return s


def serato_flat_playlists_to_tree(
    playlists: list,
    *,
    skip_filter_trees: bool = True,
) -> list:
    """
    Płaskie Subcrates (MyLists%%gatunki%%HOUSE) → zagnieżdżone Playlist.
    Pomija Sideview / Folders / Filters gdy skip_filter_trees=True.
    """
    from unified_model import Playlist

    # parts → (tracks, is_explicit_leaf)
    nodes: dict[tuple[str, ...], list[str]] = {}
    folders: set[tuple[str, ...]] = set()

    for pl in playlists or []:
        raw = (getattr(pl, "name", "") or "").strip()
        stem = normalize_serato_mylists_stem(raw) if skip_filter_trees else (raw or None)
        if not stem:
            continue
        if skip_filter_trees and is_vdj_filter_tree_serato_stem(stem):
            continue
        parts = tuple(p for p in stem.split("%%") if p)
        if not parts:
            continue
        tracks = [t for t in (getattr(pl, "track_ids", None) or []) if t]
        for i in range(len(parts)):
            folders.add(parts[: i + 1])
        existing = nodes.get(parts)
        if existing is None:
            nodes[parts] = list(tracks)
        else:
            seen = set(existing)
            for t in tracks:
                if t not in seen:
                    existing.append(t)
                    seen.add(t)

    def build(parts: tuple[str, ...]) -> Playlist:
        children: list = []
        child_names = sorted(
            {
                f[len(parts)]
                for f in folders
                if len(f) == len(parts) + 1 and f[: len(parts)] == parts
            },
            key=lambda s: s.lower(),
        )
        for name in child_names:
            children.append(build(parts + (name,)))
        tracks = nodes.get(parts) or []
        return Playlist(
            name=parts[-1] if parts else "Serato",
            track_ids=list(tracks),
            is_folder=bool(children),
            children=children,
        )

    roots = sorted(
        {f[0] for f in folders if len(f) >= 1},
        key=lambda s: s.lower(),
    )
    return [build((name,)) for name in roots]


def prepare_serato_unified_for_engine(
    serato_dir: Optional[Path] = None,
    *,
    drive_root: str = "/",
    apply_njr_substitutes: bool = True,
    include_all_tracks: bool = True,
    read_file_cues: bool = True,
) -> UnifiedDatabase:
    """
    Ładuje ~/Music/_Serato_ → UnifiedDatabase gotowe do Engine:
    drzewo playlist z Subcrates + lokalne ścieżki (w tym NJR-Tidal-Serato).
    Streaming → lokalny plik z manifestu NJR gdy dostępny.
    Hot cues: odczyt Markers2 z plików audio (Serato trzyma je w tagach, nie w V2).
    """
    from unified_model import Playlist, Track, UnifiedDatabase
    from vdjfolder import normalize_path
    from engine_music_paths import is_junk_engine_path

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    if not (base / "database V2").is_file() and not (base / "DatabaseV2").is_file():
        # pozwól też na folder nadrzędny z _Serato_
        nested = base / "_Serato_"
        if (nested / "database V2").is_file() or (nested / "DatabaseV2").is_file():
            base = nested
    db = load_serato_folder(base, drive_root=drive_root)

    substitutes: dict[str, str] = {}
    if apply_njr_substitutes:
        try:
            from tidal_download import manifest_substitutes

            substitutes = manifest_substitutes() or {}
        except Exception:
            substitutes = {}

    def _resolve(path: str) -> str:
        raw = (path or "").strip()
        if not raw:
            return ""
        if substitutes:
            hit = substitutes.get(normalize_path(raw))
            if hit:
                return hit
        return raw

    tracks_out: list[Track] = []
    seen_paths: set[str] = set()
    for t in db.tracks or []:
        new_path = _resolve(t.path)
        if not new_path or new_path in seen_paths:
            continue
        if is_junk_engine_path(new_path):
            continue
        seen_paths.add(new_path)
        if new_path != t.path:
            tracks_out.append(
                Track(
                    path=new_path,
                    title=t.title,
                    artist=t.artist,
                    album=getattr(t, "album", "") or "",
                    genre=getattr(t, "genre", "") or "",
                    comment=getattr(t, "comment", "") or "",
                    bpm=getattr(t, "bpm", 0) or 0,
                    key=getattr(t, "key", "") or "",
                    duration=getattr(t, "duration", 0) or 0,
                    play_count=getattr(t, "play_count", 0) or 0,
                    rating=getattr(t, "rating", 0) or 0,
                    cue_points=list(getattr(t, "cue_points", None) or []),
                    loops=list(getattr(t, "loops", None) or []),
                    beatgrid=list(getattr(t, "beatgrid", None) or []),
                )
            )
        else:
            tracks_out.append(t)

    flat_pls = []
    for pl in db.playlists or []:
        resolved_ids = []
        seen_ids: set[str] = set()
        for p in pl.track_ids or []:
            rp = _resolve(p)
            if not rp or rp in seen_ids:
                continue
            if is_junk_engine_path(rp):
                continue
            seen_ids.add(rp)
            resolved_ids.append(rp)
            if rp not in seen_paths:
                # crate-only path — dopisz Track (meta puste)
                seen_paths.add(rp)
                tracks_out.append(Track(path=rp))
        flat_pls.append(
            Playlist(name=pl.name, track_ids=resolved_ids, is_folder=False)
        )

    cue_stats: dict = {}
    loop_stats: dict = {}
    if read_file_cues:
        try:
            from serato_markers import (
                enrich_tracks_with_serato_loops,
                enrich_tracks_with_serato_markers2,
            )

            cue_stats = enrich_tracks_with_serato_markers2(tracks_out)
            loop_stats = enrich_tracks_with_serato_loops(tracks_out)
        except Exception as e:
            cue_stats = {"ok": False, "error": str(e)}
            loop_stats = {"ok": False, "error": str(e)}

    tree = serato_flat_playlists_to_tree(flat_pls, skip_filter_trees=True)
    children = list(tree)
    if include_all_tracks:
        all_paths = [t.path for t in tracks_out if t.path]
        children = [
            Playlist(name="wszystkie pliki", track_ids=all_paths, is_folder=False)
        ] + children
    out = UnifiedDatabase(
        tracks=tracks_out,
        playlists=[
            Playlist(name="Serato", track_ids=[], is_folder=True, children=children)
        ],
        source="serato",
    )
    # metadane pomocnicze dla API (nie część UnifiedDatabase)
    setattr(out, "_serato_cue_stats", cue_stats)
    setattr(out, "_serato_loop_stats", loop_stats)
    return out


def iter_serato_smart_crate_files(
    playlists: list,
    *,
    prefix: tuple[str, ...] = (),
) -> list[tuple[str, str, tuple[str, ...]]]:
    """
    Listy z filter_text → (stem hierarchiczny ≫≫, filter_text, path_parts).
    """
    out: list[tuple[str, str, tuple[str, ...]]] = []
    used: set[str] = set()

    def walk(nodes: list, parts: tuple[str, ...]) -> None:
        for pl in nodes or []:
            seg = safe_serato_crate_segment(getattr(pl, "name", "") or "")
            path_parts = parts + (seg,)
            filt = (getattr(pl, "filter_text", "") or "").strip()
            if filt:
                stem = serato_smart_crate_stem(path_parts, used)
                out.append((stem, filt, path_parts))
            children = list(getattr(pl, "children", None) or [])
            if children:
                walk(children, path_parts)

    walk(playlists, prefix)
    return out


def is_serato_crate_exportable_path(path: str) -> bool:
    """Plik lokalny lub Tidal (Serato 4 streaming) — do wpisu .crate."""
    from vdj_streaming import is_serato_tidal_path, is_tidal_path

    if is_serato_tidal_path(path) or is_tidal_path(path):
        return True
    return is_serato_crate_local_path(path)


def is_serato_crate_local_path(path: str) -> bool:
    """Czy ścieżka nadaje się do wpisu .crate (plik lokalny)."""
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return False
    low = p.lower()
    if low.startswith("netsearch:"):
        return False
    if re.match(r"^td\d+$", p, re.IGNORECASE):
        return False
    if low.startswith("tidal:") or low.startswith("soundcloud:") or low.startswith("beatport:"):
        return False
    if low.endswith(".vdjcache") or low.endswith(".vdjsample"):
        return False
    name = p.rsplit("/", 1)[-1]
    if "." not in name:
        return False
    return True


_SMART_NAME_JUNK_RE = re.compile(
    r"(%%)|(\u241b)|(\ufe6a)|(\uff05)",  # %% / SYMBOL FOR ESCAPE / small % / fullwidth %
)


def normalize_serato_leaf_name(name: str) -> str:
    """
    Porównanie nazw liści crate/smart: BIESIADA _1_ ≡ BIESIADA _1 ≡ biesiada 1.
    """
    s = (name or "").strip().lower()
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def remove_subcrates_duplicating_smart_crates(
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Usuwa zwykłe .crate gdy istnieje Smart Crate o tej samej nazwie liścia
    (np. Energy 1.crate + Energy 1.scrate → zostaje tylko .scrate).
    Uwzględnia warianty _1_ / _1.
    """
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    smart_dir = base / "SmartCrates"
    sub_dir = base / "Subcrates"
    removed: list[str] = []
    if not smart_dir.is_dir() or not sub_dir.is_dir():
        return {"ok": True, "removed": [], "dry_run": dry_run}

    smart_names: set[str] = set()
    for p in smart_dir.glob("*.scrate"):
        leaf = serato_smart_crate_leaf(p.stem)
        smart_names.add(normalize_serato_leaf_name(leaf))
        smart_names.add(normalize_serato_leaf_name(p.stem))

    for p in list(sub_dir.glob("*.crate")):
        leaf = normalize_serato_leaf_name(p.stem.split("%%")[-1])
        full = normalize_serato_leaf_name(p.stem)
        if leaf in smart_names or full in smart_names:
            removed.append(p.name)
            if not dry_run:
                try:
                    p.unlink()
                except OSError:
                    pass
    return {"ok": True, "removed": removed, "dry_run": dry_run}


def cleanup_orphan_flat_subcrates(
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Usuwa płaskie Subcrates (bez %%) które są duplikatem:
    - Smart Crate o tej samej nazwie liścia, lub
    - zagnieżdżonego VDJ%%…%%liść.crate / MyLists%%…%%liść.crate
    Dzięki temu listy nie wiszą poza drzewem katalogów.
    """
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    smart_dir = base / "SmartCrates"
    removed: list[str] = []
    if not sub_dir.is_dir():
        return {"ok": True, "removed": [], "dry_run": dry_run}

    smart_leaves: set[str] = set()
    if smart_dir.is_dir():
        for p in smart_dir.glob("*.scrate"):
            smart_leaves.add(normalize_serato_leaf_name(serato_smart_crate_leaf(p.stem)))

    nested_leaves: set[str] = set()
    for p in sub_dir.glob("*.crate"):
        if "%%" in p.stem:
            nested_leaves.add(normalize_serato_leaf_name(p.stem.split("%%")[-1]))

    for p in list(sub_dir.glob("*.crate")):
        if "%%" in p.stem:
            continue
        leaf = normalize_serato_leaf_name(p.stem)
        if leaf in smart_leaves or leaf in nested_leaves:
            removed.append(p.name)
            if not dry_run:
                try:
                    p.unlink()
                except OSError:
                    pass
    return {"ok": True, "removed": removed, "dry_run": dry_run}


def cleanup_legacy_mylists_prefix_crates(
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Kanoniczne drzewo = MyLists%%…
    Usuwa zduplikowane VDJ%%MyLists%%… (oraz VDJ%%*) — nie rusza MyLists.
    """
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    removed: list[str] = []
    if not sub_dir.is_dir():
        return {"ok": True, "removed": [], "dry_run": dry_run}

    for p in list(sub_dir.glob("VDJ%%*.crate")):
        removed.append(p.name)
        if not dry_run:
            try:
                p.unlink()
            except OSError:
                pass
    vdj_crate = sub_dir / "VDJ.crate"
    if vdj_crate.is_file():
        removed.append("VDJ.crate")
        if not dry_run:
            try:
                vdj_crate.unlink()
            except OSError:
                pass
    return {"ok": True, "removed": removed, "dry_run": dry_run}


def remove_vdj_smart_crates(
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Usuwa Smart Crates wygenerowane z VDJ (VDJ≫≫… / VDJ%%… .scrate).
    Po przejściu na snapshot-only zwykłe Subcrates zastępują Smart Crates.
    """
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    smart_dir = base / "SmartCrates"
    removed: list[str] = []
    if not smart_dir.is_dir():
        return {"ok": True, "removed": [], "dry_run": dry_run}

    for p in list(smart_dir.glob("*.scrate")):
        stem = p.stem
        if not (
            stem.startswith("VDJ")
            or stem.startswith(f"VDJ{SERATO_SMART_SEP}")
            or "%%" in stem
            and stem.split("%%", 1)[0] == "VDJ"
        ):
            continue
        removed.append(p.name)
        if not dry_run:
            try:
                p.unlink()
            except OSError:
                pass
    return {"ok": True, "removed": removed, "dry_run": dry_run}


def remove_vdj_subcrates(
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Usuwa wszystkie Subcrates VDJ%%… przed świeżą instalacją drzewa."""
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    removed: list[str] = []
    if not sub_dir.is_dir():
        return {"ok": True, "removed": [], "dry_run": dry_run}
    for p in list(sub_dir.glob("VDJ%%*.crate")):
        removed.append(p.name)
        if not dry_run:
            try:
                p.unlink()
            except OSError:
                pass
    if not dry_run and (sub_dir / "VDJ.crate").is_file():
        removed.append("VDJ.crate")
        try:
            (sub_dir / "VDJ.crate").unlink()
        except OSError:
            pass
    return {"ok": True, "removed": removed, "dry_run": dry_run}


def build_tidal_meta_index_from_vdjfolders(vdjfolders: dict) -> dict[str, dict]:
    """Mapa Tidal ID → metadane z atrybutów <song> w plikach .vdjfolder."""
    import xml.etree.ElementTree as ET

    from vdj_streaming import extract_tidal_id

    index: dict[str, dict] = {}
    for content in (vdjfolders or {}).values():
        if not content:
            continue
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            continue
        for song_elem in root.findall(".//song"):
            p = (song_elem.get("path") or "").strip()
            tid = extract_tidal_id(p)
            if not tid:
                continue
            index[str(tid)] = {
                "FilePath": p,
                "Tags.Title": (song_elem.get("title") or "").strip(),
                "Tags.Author": (song_elem.get("artist") or "").strip(),
                "Tags.Bpm": (song_elem.get("bpm") or "").strip(),
                "Tags.Key": (song_elem.get("key") or "").strip(),
                "Infos.SongLength": (song_elem.get("songlength") or "").strip(),
            }
    return index


def build_tidal_meta_index(
    vdjfolders: Optional[dict] = None,
    songs: Optional[list[dict]] = None,
) -> dict[str, dict]:
    """
    Pełna mapa Tidal ID → metadane: .vdjfolder + pełna baza VDJ (database.xml).
    Priorytet: wpis z tytułem (nie placeholder) z songs, potem vdjfolder.
    """
    from serato_library_sqlite import is_tidal_placeholder_name
    from tidal_vdj_metadata import _song_tidal_id

    index = build_tidal_meta_index_from_vdjfolders(vdjfolders or {})
    for s in songs or []:
        tid = _song_tidal_id(s)
        if not tid:
            continue
        entry = {
            "FilePath": (s.get("FilePath") or "").strip(),
            "Tags.Title": (s.get("Tags.Title") or s.get("Tags.Name") or "").strip(),
            "Tags.Author": (s.get("Tags.Artist") or s.get("Tags.Author") or "").strip(),
            "Tags.Bpm": (s.get("Tags.Bpm") or "").strip(),
            "Tags.Key": (s.get("Tags.Key") or "").strip(),
            "Infos.SongLength": (s.get("Infos.SongLength") or "").strip(),
        }
        prev = index.get(str(tid)) or {}
        prev_title = (prev.get("Tags.Title") or "").strip()
        new_title = (entry.get("Tags.Title") or "").strip()
        if new_title and not is_tidal_placeholder_name(new_title, tid):
            index[str(tid)] = {**prev, **{k: v for k, v in entry.items() if v}}
        elif not prev_title or is_tidal_placeholder_name(prev_title, tid):
            index[str(tid)] = {**entry, **{k: v for k, v in prev.items() if v and k not in entry}}
    return index


def existing_local_serato_file(path: str) -> Optional[str]:
    """Zwraca absolutną ścieżkę istniejącego pliku lokalnego albo None (streaming / brak)."""
    from vdj_streaming import is_serato_tidal_path

    raw = (path or "").strip().replace("\\", "/")
    if not raw or is_serato_tidal_path(raw) or raw.lower().startswith("netsearch:"):
        return None
    candidates: list[Path] = []
    if raw.startswith("/"):
        candidates.append(Path(raw))
    else:
        candidates.append(Path("/") / raw)
        candidates.append(Path(raw))
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return None


def keep_existing_local_crate_paths(paths: list[str]) -> list[str]:
    """Filtruje listę do istniejących plików lokalnych (bez duplikatów /Users ≡ Users)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in paths or []:
        abs_p = existing_local_serato_file(raw)
        if not abs_p:
            continue
        key = serato_path_identity_key(abs_p)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(abs_p)
    return out


def _prepare_serato_crate_entries(
    playlists: list,
    *,
    songs: Optional[list[dict]] = None,
    path_substitutes: Optional[dict[str, str]] = None,
    path_replace: Optional[dict[str, str]] = None,
) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]], set[str]]:
    """
    Rozwija playlisty VDJ →
      - prepared: (stem, lokalne ścieżki do .crate)
      - streaming_by_crate: (stem, [streaming://tidal/ID, …]) do Library SQLite
      - njr_tids: Tidal ID które mają plik NJR (nie wolno ich trzymać w streamingu)

    Listy mieszane (lokalne + Tidal) zachowują streaming w SQLite — jak w VDJ.
    """
    from vdj_path_mapping import build_vdj_song_by_path_index
    from vdj_streaming import extract_tidal_id, is_serato_tidal_path, vdj_to_serato_tidal_path
    from vdjfolder import is_grow_serato_crate, normalize_path

    song_by_path = build_vdj_song_by_path_index(songs or []) if songs else None

    entries = iter_serato_crate_files(playlists or [])
    prepared: list[tuple[str, list[str]]] = []
    streaming_by_crate: list[tuple[str, list[str]]] = []
    njr_tids: set[str] = set()
    prepared_by_stem: dict[str, list[str]] = {}
    streaming_by_stem: dict[str, list[str]] = {}
    for stem_raw, tracks in entries:
        stem = normalize_serato_mylists_stem(stem_raw)
        if not stem:
            continue
        grow = is_grow_serato_crate(stem=stem)
        local = filter_track_paths_for_serato(
            tracks,
            path_replace,
            path_substitutes,
            include_streaming=False,
            song_by_path=song_by_path,
        )
        if grow:
            local = keep_existing_local_crate_paths(local)
        if stem in prepared_by_stem:
            seen_l = {serato_path_identity_key(p) for p in prepared_by_stem[stem]}
            for p in local:
                k = serato_path_identity_key(p)
                if k and k not in seen_l:
                    prepared_by_stem[stem].append(p)
                    seen_l.add(k)
        else:
            prepared_by_stem[stem] = list(local)

        stream: list[str] = []
        seen: set[str] = set()
        for raw in tracks or []:
            raw_s = (raw or "").strip()
            vdj_song = (
                song_by_path.get(normalize_path(raw_s)) if song_by_path else None
            )
            resolved = resolve_serato_export_path(
                raw_s,
                path_replace,
                path_substitutes,
                song=vdj_song,
                song_by_path=song_by_path,
            )
            if not resolved:
                resolved = vdj_to_serato_tidal_path(raw_s) or ""
            local_sub = None
            if path_substitutes:
                from serato_offline import lookup_serato_offline_substitute

                local_sub = lookup_serato_offline_substitute(raw_s, path_substitutes)
            if local_sub and not is_serato_tidal_path(local_sub):
                tid = extract_tidal_id(raw_s) or extract_tidal_id(local_sub) or ""
                if tid:
                    njr_tids.add(tid)
                continue
            if not resolved or not is_serato_tidal_path(resolved):
                continue
            key = serato_path_identity_key(resolved)
            if not key or key in seen:
                continue
            seen.add(key)
            stream.append(resolved)
        if stream:
            bucket = streaming_by_stem.setdefault(stem, [])
            seen_s = {serato_path_identity_key(p) for p in bucket}
            for p in stream:
                k = serato_path_identity_key(p)
                if k and k not in seen_s:
                    bucket.append(p)
                    seen_s.add(k)
    prepared = list(prepared_by_stem.items())
    streaming_by_crate = [(s, t) for s, t in streaming_by_stem.items() if t]
    return prepared, streaming_by_crate, njr_tids


def merge_tidal_streaming_paths_into_serato_database(
    tidal_paths: list[str],
    songs: list[dict],
    serato_dir: Optional[Path] = None,
    *,
    tidal_meta: Optional[dict[str, dict]] = None,
    dry_run: bool = False,
) -> dict:
    """
    Dodaje tidal:tracks:ID do database V2.
    Serato nie pokazuje utworów w .crate bez wpisu w bazie (inaczej niż ręczne dodanie z Tidal).
    """
    import time
    from datetime import datetime

    from vdj_streaming import extract_tidal_id, is_serato_tidal_path
    from tidal_vdj_metadata import find_vdj_song_for_tidal_id

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    db_file = base / "database V2"
    if not db_file.is_file():
        db_file = base / "Database V2"
    if not db_file.is_file():
        return {"ok": False, "error": f"Brak database V2 w {base}"}

    raw = db_file.read_bytes()
    existing = _database_path_keys(raw)
    meta = tidal_meta or {}
    now = int(time.time())
    new_payloads: list[bytes] = []
    added = 0

    for path in tidal_paths or []:
        if not is_serato_tidal_path(path):
            continue
        key = serato_path_identity_key(path)
        if not key or key in existing:
            continue
        tid = extract_tidal_id(path) or ""
        song = find_vdj_song_for_tidal_id(
            tid,
            songs or [],
            author=(meta.get(tid) or {}).get("Tags.Author") or "",
            title=(meta.get(tid) or {}).get("Tags.Title") or "",
        ) or meta.get(tid) or {
            "FilePath": path,
            "Tags.Title": f"Tidal {tid}",
        }
        new_payloads.append(_build_otrk_payload(song, path, now))
        existing.add(key)
        added += 1

    result = {
        "ok": True,
        "added_tidal_streaming": added,
        "requested": len(tidal_paths or []),
        "dry_run": dry_run,
    }
    if dry_run or not new_payloads:
        return result

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = Path(str(db_file) + f".pre-merge-tidal-streaming-{stamp}.bak")
    bak.write_bytes(raw)
    merged = _append_otrks_to_database(raw, new_payloads)
    db_file.write_bytes(merged)
    result["backup"] = str(bak)
    return result


def merge_grow_crate_track_paths(existing: list[str], new: list[str]) -> list[str]:
    """
    Scalanie rosnącego crate: zachowaj kolejność istniejących, dopisz nowe bez duplikatów.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(existing or []) + list(new or []):
        p = (raw or "").strip()
        if not p:
            continue
        key = serato_path_identity_key(p)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def snapshot_grow_crate_tracks(
    serato_dir: Optional[Path] = None,
    *,
    drive_root: Optional[str] = None,
) -> dict[str, list[str]]:
    """
    Odczytaj istniejące Subcrates rosnące (np. LINKI) przed nadpisaniem.
    Tylko istniejące pliki lokalne. Klucz = liść nazwy (lowercase).
    """
    from vdjfolder import is_grow_serato_crate

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    out: dict[str, list[str]] = {}
    if not sub_dir.is_dir():
        return out
    # Nie używaj drive_root=Music — ścieżki relatywne Users/… dublują się.
    _ = drive_root
    for p in sub_dir.glob("*.crate"):
        stem = p.stem
        if not is_grow_serato_crate(stem=stem):
            continue
        try:
            pl = load_serato_crate(p.read_bytes(), stem, drive_root=None)
        except Exception:
            continue
        leaf = stem.split("%%")[-1].strip().lower()
        if not leaf:
            continue
        prev = out.get(leaf) or []
        locals_only = keep_existing_local_crate_paths(list(pl.track_ids or []))
        out[leaf] = merge_grow_crate_track_paths(prev, locals_only)
    return out


def apply_grow_merge_to_prepared_entries(
    prepared_entries: list[tuple[str, list[str]]],
    grow_existing: dict[str, list[str]],
) -> list[tuple[str, list[str]]]:
    """Dopisz stare lokalne ścieżki do rosnących crate'ów (LINKI) — bez streamingu / duchów."""
    from vdjfolder import is_grow_serato_crate

    out: list[tuple[str, list[str]]] = []
    for stem, tracks in prepared_entries or []:
        if not is_grow_serato_crate(stem=stem):
            out.append((stem, tracks))
            continue
        leaf = stem.split("%%")[-1].strip().lower()
        merged = merge_grow_crate_track_paths(
            grow_existing.get(leaf) or [],
            keep_existing_local_crate_paths(tracks),
        )
        out.append((stem, keep_existing_local_crate_paths(merged)))
    return out


def purge_vdj_filter_tree_subcrates(
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Usuwa Subcrates z drzew Sideview / Folders / Filters.
    Wywoływane przed i po instalacji — stare pliki .crate inaczej wracają w UI Serato.
    """
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    removed: list[str] = []
    if not sub_dir.is_dir():
        return {"ok": True, "removed": [], "count": 0, "dry_run": dry_run}

    seen: set[str] = set()
    for pat in ("Sideview%%*.crate", "Folders%%*.crate", "Filters%%*.crate"):
        for p in sub_dir.glob(pat):
            if p.name in seen:
                continue
            seen.add(p.name)
            removed.append(p.name)
            if not dry_run:
                try:
                    p.unlink()
                except OSError:
                    pass

    for p in list(sub_dir.glob("*.crate")):
        if p.name in seen:
            continue
        if is_vdj_filter_tree_serato_stem(p.stem):
            seen.add(p.name)
            removed.append(p.name)
            if not dry_run:
                try:
                    p.unlink()
                except OSError:
                    pass

    return {"ok": True, "removed": removed, "count": len(removed), "dry_run": dry_run}


def remove_excluded_transfer_subcrates(
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """Usuwa Subcrates z drzew filtrów VDJ oraz Compatible / My Library."""
    filter_removed = purge_vdj_filter_tree_subcrates(serato_dir, dry_run=dry_run)
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    removed: list[str] = list(filter_removed.get("removed") or [])
    removed_set = set(removed)
    if not sub_dir.is_dir():
        return {"ok": True, "removed": removed, "dry_run": dry_run}

    def _excluded_compatible_stem(stem: str) -> bool:
        low = (stem or "").replace("\\", "/").lower()
        for seg in low.split("%%"):
            s = seg.strip()
            if s in ("compatible", "my library", "my libery"):
                return True
            if s.startswith("compatible "):
                return True
        return False

    for p in list(sub_dir.glob("*.crate")):
        if p.name in removed_set:
            continue
        stem = p.stem
        if not _excluded_compatible_stem(stem):
            continue
        removed.append(p.name)
        removed_set.add(p.name)
        if not dry_run:
            try:
                p.unlink()
            except OSError:
                pass
    return {"ok": True, "removed": removed, "dry_run": dry_run}


def install_serato_subcrate_tree_from_playlists(
    playlists: list,
    serato_dir: Optional[Path] = None,
    *,
    drive_root: Optional[str] = None,
    path_style: Optional[str] = None,
    path_replace: Optional[dict[str, str]] = None,
    path_substitutes: Optional[dict[str, str]] = None,
    write_tracks: bool = True,
    prepared_entries: Optional[list[tuple[str, list[str]]]] = None,
) -> dict:
    """
    Zapisuje hierarchię Subcrates (VDJ%%MyLists%%…) — zwykłe playlisty ze snapshotem ścieżek.
    """
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    sub_dir.mkdir(parents=True, exist_ok=True)

    if prepared_entries is not None:
        entries = prepared_entries
    else:
        entries = [
            (stem, filter_track_paths_for_serato(tracks, path_replace, path_substitutes))
            for stem, tracks in iter_serato_crate_files(playlists or [])
        ]
    written: list[str] = []
    ensured_parents: set[str] = set()
    for stem, payload in entries:
        parts = [p for p in (stem or "").split("%%") if p]
        for i in range(2, len(parts)):
            parent_stem = "%%".join(parts[:i])
            if parent_stem in ensured_parents:
                continue
            parent_file = sub_dir / f"{parent_stem}.crate"
            if not parent_file.is_file():
                parent_file.write_bytes(
                    save_serato_crate(
                        [],
                        parent_stem,
                        drive_root,
                        path_style=path_style or "relative",
                        path_replace=path_replace,
                        path_substitutes=path_substitutes,
                        existing_files_only=False,
                    )
                )
            ensured_parents.add(parent_stem)
        out = sub_dir / f"{stem}.crate"
        if not write_tracks:
            payload = []
        out.write_bytes(
            save_serato_crate(
                payload,
                stem,
                drive_root,
                path_style=path_style or "relative",
                path_replace=path_replace,
                path_substitutes=path_substitutes,
                existing_files_only=False,
            )
        )
        written.append(stem)

    return {"ok": True, "written": written, "count": len(written)}


def install_vdj_offline_cache_crate(
    track_paths: list[str],
    serato_dir: Optional[Path] = None,
    *,
    drive_root: Optional[str] = None,
    path_style: Optional[str] = None,
    path_replace: Optional[dict[str, str]] = None,
    path_substitutes: Optional[dict[str, str]] = None,
) -> dict:
    """Subcrate ze wszystkimi utworami z cache VDJ, które Serato może odtworzyć."""
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    sub_dir.mkdir(parents=True, exist_ok=True)
    stem = "VDJ Offline Cache"
    out = sub_dir / f"{stem}.crate"
    payload = filter_track_paths_for_serato(
        track_paths or [], path_replace, path_substitutes
    )
    out.write_bytes(
        save_serato_crate(
            payload,
            stem,
            drive_root,
            path_style=path_style or "relative",
            path_replace=path_replace,
            path_substitutes=path_substitutes,
            existing_files_only=False,
        )
    )
    return {"ok": True, "stem": stem, "track_count": len(payload)}


def _song_bpm_display(s: dict) -> float:
    raw = (s.get("Tags.Bpm") or "").strip()
    if not raw:
        return 0.0
    try:
        val = float(raw)
        if 0.2 <= val <= 2.0:
            return 60.0 / val
        if 20 <= val <= 300:
            return val
    except ValueError:
        pass
    return 0.0


def _xml_esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_serato_tidal_metadata_from_songs(
    songs: list[dict],
    serato_dir: Optional[Path] = None,
) -> dict:
    """Zapisuje Metadata/Tidal/{id}.xml dla utworów Tidal (BPM, key z VDJ)."""
    from serato_library_sqlite import _read_serato_tidal_ssl_xml, is_tidal_placeholder_name
    from vdj_streaming import extract_tidal_id, is_tidal_path

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    meta_dir = base / "Metadata" / "Tidal"
    meta_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    updated = 0
    for s in songs or []:
        fp = (s.get("FilePath") or "").strip()
        if not is_tidal_path(fp):
            continue
        tid = extract_tidal_id(fp)
        if not tid:
            continue
        title = (s.get("Tags.Title") or s.get("Tags.Name") or "").strip()
        if is_tidal_placeholder_name(title, tid):
            title = ""
        if not title:
            continue
        artist = (s.get("Tags.Artist") or s.get("Tags.Author") or "").strip()
        album = (s.get("Tags.Album") or "").strip()
        bpm = _song_bpm_display(s)
        key = (s.get("Tags.Key") or "").strip()
        play_count = int(float(s.get("Infos.PlayCount") or 0))
        length = float(s.get("Infos.SongLength") or 0)
        xml_path = meta_dir / f"{tid}.xml"
        if xml_path.is_file():
            existing = _read_serato_tidal_ssl_xml(meta_dir, tid)
            existing_name = (existing.get("name") or "").strip()
            if existing_name and not is_tidal_placeholder_name(existing_name, tid):
                continue
            action = "updated"
        else:
            action = "written"
        lines = [
            "<SSLMetadata>",
            f"    <Name>{_xml_esc(title)}</Name>",
        ]
        if artist:
            lines.append(f"    <Artist>{_xml_esc(artist)}</Artist>")
        if album:
            lines.append(f"    <Album>{_xml_esc(album)}</Album>")
        if bpm > 0:
            lines.append(f"    <BPM>{bpm:.6f}</BPM>")
            lines.append("    <BeatGrid>")
            lines.append("        <BeatGridMarker>")
            lines.append("            <Position>0.000000</Position>")
            lines.append(f"            <BPM>{bpm:.6f}</BPM>")
            lines.append("        </BeatGridMarker>")
            lines.append("    </BeatGrid>")
        if key:
            lines.append(f"    <Key>{_xml_esc(key)}</Key>")
        if play_count:
            lines.append(f"    <PlayCount>{play_count}</PlayCount>")
        if length > 0:
            lines.append(f"    <Length>{length:.2f}</Length>")
        lines.append("</SSLMetadata>")
        xml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if action == "updated":
            updated += 1
        else:
            written += 1
    return {"ok": True, "written": written, "updated": updated}


def install_serato_playlists_from_tree(
    playlists: list,
    serato_dir: Optional[Path] = None,
    *,
    drive_root: Optional[str] = None,
    path_style: Optional[str] = None,
    path_replace: Optional[dict[str, str]] = None,
    remove_smart_crates: bool = True,
    songs: Optional[list[dict]] = None,
    merge_database: bool = True,
    vdjfolders: Optional[dict[str, str]] = None,
    install_offline_cache_crate: bool = True,
) -> dict:
    """
    Instalacja VDJ → Serato: usuwa Smart Crates VDJ, zapisuje Subcrates, czyści legacy MyLists%%.
    merge_database: dodaje brakujące utwory (w tym Tidal) do database V2.
    """
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    filter_purge_before = purge_vdj_filter_tree_subcrates(base, dry_run=False)
    entries = iter_serato_crate_files(playlists or [])
    if not entries:
        return {
            "ok": False,
            "error": (
                "Brak playlist VDJ do zapisu (0 Subcrates). "
                "Załaduj backup VDJ z plikami .vdjfolder — istniejące Subcrates nie zostały usunięte."
            ),
        }

    merge_stats: dict = {}
    offline_stats: dict = {}
    path_substitutes: dict[str, str] = {}
    from serato_offline import build_serato_offline_substitutes

    # Zawsze ładuj manifest NJR — nawet bez pełnej listy songs (vdjfolder netsearch→lokalny plik)
    path_substitutes, offline_stats = build_serato_offline_substitutes(songs or [])
    prepared_entries, streaming_by_crate, njr_tids = _prepare_serato_crate_entries(
        playlists,
        songs=songs,
        path_substitutes=path_substitutes or None,
        path_replace=path_replace,
    )

    # Rosnące listy (LINKI): scal lokalne; wyczyść kontenery przed świeżym zapisem
    # (lokalne → root/crate, jawne Tidal z listy → tidal.sqlite — bez masowego dumpa).
    grow_existing = snapshot_grow_crate_tracks(base, drive_root=drive_root)
    prepared_entries = apply_grow_merge_to_prepared_entries(
        prepared_entries, grow_existing
    )
    grow_clear_stats: dict = {}
    from vdjfolder import is_grow_serato_crate

    grow_stems = sorted(
        {
            s
            for s, _ in (prepared_entries or []) + (streaming_by_crate or [])
            if is_grow_serato_crate(stem=s)
        }
    )
    if grow_stems:
        try:
            from serato_library_sqlite import clear_container_assets_for_crate_stem

            for gs in grow_stems:
                grow_clear_stats[gs] = clear_container_assets_for_crate_stem(gs)
        except Exception as e:
            grow_clear_stats = {"ok": False, "error": str(e)}

    # Cue/meta/rating z VDJ → pliki lokalne (NJR m4a + MP3 z crate'ów).
    # Schemat: POPM/rate + Markers_/Markers2 + SQLite rating — bez „Rating:” w comment.
    meta_apply_stats: dict = {}
    if songs:
        try:
            from tidal_vdj_metadata import apply_vdj_metadata_to_local_paths
            from vdj_streaming import is_serato_tidal_path

            local_paths: list[str] = []
            seen_p: set[str] = set()
            for dst in (path_substitutes or {}).values():
                d = (dst or "").strip()
                if d and d not in seen_p:
                    seen_p.add(d)
                    local_paths.append(d)
            for _stem, tracks in prepared_entries or []:
                for tp in tracks or []:
                    t = (tp or "").strip()
                    if not t or is_serato_tidal_path(t) or t in seen_p:
                        continue
                    if Path(t).is_file():
                        seen_p.add(t)
                        local_paths.append(t)

            meta_apply_stats = apply_vdj_metadata_to_local_paths(
                songs,
                local_paths,
                path_substitutes=path_substitutes or None,
                path_replace=path_replace,
                skip_unchanged_cues=True,
            )
            meta_apply_stats["paths_total"] = len(local_paths)
        except Exception as e:
            meta_apply_stats = {"ok": False, "error": str(e)}
    offline_stats["vdj_metadata_apply"] = meta_apply_stats

    smart_removed: dict = {"removed": []}
    if remove_smart_crates:
        smart_removed = remove_vdj_smart_crates(base, dry_run=False)
    sub_removed = remove_vdj_subcrates(base, dry_run=False)
    legacy = cleanup_legacy_mylists_prefix_crates(base, dry_run=False)
    excluded_removed = remove_excluded_transfer_subcrates(base, dry_run=False)
    vdj_tree_removed: dict = {}
    try:
        from serato_library_sqlite import remove_vdj_serato_library_tree

        vdj_tree_removed = remove_vdj_serato_library_tree(serato_dir=base)
    except Exception as e:
        vdj_tree_removed = {"ok": False, "error": str(e)}
    if merge_database:
        if songs:
            merge_stats = merge_vdj_tracks_into_serato_database(
                songs,
                base,
                dry_run=False,
                path_substitutes=path_substitutes or None,
                path_replace=path_replace,
            )
            meta_stats = write_serato_tidal_metadata_from_songs(songs, base)
            merge_stats["tidal_metadata_written"] = meta_stats.get("written", 0)
        else:
            merge_stats = {"ok": True, "added": 0}
        tidal_meta = build_tidal_meta_index(vdjfolders or {}, songs)
        # Streaming → Library SQLite (nie database V2 / .crate — Serato je odrzuca)
        from serato_library_sqlite import (
            install_local_tracks_into_root_library,
            install_tidal_streaming_into_serato_library,
        )

        root_stats = install_local_tracks_into_root_library(
            prepared_entries,
            dry_run=False,
        )
        merge_stats["local_root_sqlite"] = root_stats
        merge_stats["local_root_links"] = root_stats.get("links_added", 0)
        merge_stats["local_root_master_links"] = root_stats.get("master_links", 0)
        if not root_stats.get("ok"):
            merge_stats["local_root_error"] = root_stats.get("error")

        sqlite_stats = install_tidal_streaming_into_serato_library(
            streaming_by_crate,
            tidal_meta=tidal_meta,
            songs=songs,
            serato_dir=base,
            dry_run=False,
            exclude_tids=njr_tids,
        )
        merge_stats["tidal_streaming_sqlite"] = sqlite_stats
        merge_stats["tidal_streaming_added"] = sqlite_stats.get("links_added", 0)
        merge_stats["tidal_streaming_requested"] = sqlite_stats.get("tracks_requested", 0)
        merge_stats["tidal_streaming_master_links"] = sqlite_stats.get("master_links", 0)
        merge_stats["njr_tids_excluded"] = len(njr_tids)
        if not sqlite_stats.get("ok"):
            merge_stats["tidal_streaming_error"] = sqlite_stats.get("error")
        merge_stats["offline_substitutes"] = {
            k: offline_stats.get(k)
            for k in (
                "tidal_njr_download",
                "tidal_local_substitute",
                "tidal_streaming",
                "cache_njr_download",
                "manifest_entries",
                "vdj_metadata_apply",
            )
            if k in offline_stats
        }
    sub_stats = install_serato_subcrate_tree_from_playlists(
        playlists,
        base,
        drive_root=drive_root,
        path_style=path_style,
        path_replace=path_replace,
        path_substitutes=path_substitutes or None,
        prepared_entries=prepared_entries,
    )
    filter_purge_after = purge_vdj_filter_tree_subcrates(base, dry_run=False)
    flat_alias_stats: dict = {}
    if grow_stems:
        try:
            from serato_library_sqlite import sync_grow_crate_flat_alias

            prepared_map = {s: t for s, t in (prepared_entries or [])}
            for gs in grow_stems:
                flat_alias_stats[gs] = sync_grow_crate_flat_alias(
                    gs,
                    prepared_map.get(gs) or [],
                    serato_dir=base,
                    drive_root=drive_root,
                    path_style=path_style,
                    path_replace=path_replace,
                    path_substitutes=path_substitutes or None,
                )
        except Exception as e:
            flat_alias_stats = {"ok": False, "error": str(e)}
    if not (sub_stats.get("count") or 0):
        return {
            "ok": False,
            "error": (
                "Zapis Subcrates nie powiódł się (0 plików). "
                "Przywróć listy z _Serato_/Export Backups/ lub ponów instalację z załadowanym backupem VDJ."
            ),
            "smart_crates_removed": smart_removed.get("removed") or [],
            "subcrates_removed": sub_removed.get("removed") or [],
            "merge_database": merge_stats,
        }
    cache_crate: dict = {}
    cache_paths = offline_stats.pop("offline_cache_crate_track_paths", None) or []
    if install_offline_cache_crate and cache_paths:
        cache_crate = install_vdj_offline_cache_crate(
            cache_paths,
            base,
            drive_root=drive_root,
            path_style=path_style,
            path_replace=path_replace,
            path_substitutes=path_substitutes or None,
        )
    finalize_stats: dict = {}
    try:
        from serato_library_sqlite import finalize_serato_sqlite_after_install

        finalize_stats = finalize_serato_sqlite_after_install(
            serato_dir=base,
            songs=songs,
            dry_run=False,
        )
        if not finalize_stats.get("ok"):
            return {
                "ok": False,
                "error": (
                    "Instalacja zakończona, ale finalizacja biblioteki Serato nie powiodła się. "
                    f"Szczegóły: {finalize_stats}. Zamknij Serato i uruchom skrypty repair_*."
                ),
                "finalize_sqlite": finalize_stats,
                "subcrates_count": sub_stats.get("count", 0),
                "merge_database": merge_stats,
            }
    except Exception as e:
        finalize_stats = {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "smart_crates_removed": smart_removed.get("removed") or [],
        "subcrates_removed": sub_removed.get("removed") or [],
        "legacy_subcrates_removed": legacy.get("removed") or [],
        "excluded_subcrates_removed": excluded_removed.get("removed") or [],
        "filter_tree_purged_before": filter_purge_before.get("count", 0),
        "filter_tree_purged_after": filter_purge_after.get("count", 0),
        "grow_crates_merged": sorted(grow_existing.keys()) if grow_existing else [],
        "grow_containers_cleared": grow_clear_stats,
        "grow_flat_aliases": flat_alias_stats,
        "vdj_library_tree_removed": vdj_tree_removed,
        "subcrates_written": sub_stats.get("written") or [],
        "subcrates_count": sub_stats.get("count", 0),
        "merge_database": merge_stats,
        "offline_substitutes": offline_stats,
        "vdj_offline_cache_crate": cache_crate,
        "finalize_sqlite": finalize_stats,
        "serato_dir": str(base),
    }


def is_broken_serato_smart_crate_name(name: str) -> bool:
    """
    Zła nazwa Smart Crate: %% (powinno być ≫≫), śmieci Unicode,
    albo płaska nazwa bez hierarchii gdy wygląda na stary eksport liścia.
    Poprawne: VDJ≫≫MyLists≫≫gatunki≫≫TECHNO _1
    """
    stem = name[:-7] if name.lower().endswith(".scrate") else name
    if "%%" in stem:
        return True
    if _SMART_NAME_JUNK_RE.search(stem):
        return True
    if "\u241b" in stem or "\ufe6a" in stem:
        return True
    # już z hierarchią ≫≫ — OK
    if SERATO_SMART_SEP in stem:
        return False
    return False


def _split_broken_smart_stem(stem: str) -> tuple[str, ...]:
    """Rozdziela VDJ%%… / VDJ≫≫… / Unicode na segmenty."""
    s = stem
    if SERATO_SMART_SEP in s:
        return tuple(p for p in s.split(SERATO_SMART_SEP) if p.strip())
    s = s.replace("\u241b", "").replace("\ufe6a", "%").replace("\uff05", "%")
    while "%%%" in s:
        s = s.replace("%%%", "%%")
    s = re.sub(r"%+", "%%", s)
    parts = [p for p in s.split("%%") if p.strip()]
    return tuple(parts)


def repair_serato_smart_crate_filenames(
    serato_dir: Optional[Path] = None,
    *,
    dry_run: bool = False,
) -> dict:
    """
    Przemianowuje zepsute Smart Crates (%% / Unicode) na hierarchię ≫≫,
    zachowując reguły w pliku. Usuwa odpowiadające liście Subcrates.
    """
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    smart_dir = base / "SmartCrates"
    sub_dir = base / "Subcrates"
    renamed: list[dict] = []
    removed_sub: list[str] = []
    used: set[str] = set()

    if not smart_dir.is_dir():
        return {"ok": True, "renamed": [], "removed_subcrates": [], "dry_run": dry_run}

    for p in smart_dir.glob("*.scrate"):
        if not is_broken_serato_smart_crate_name(p.name):
            used.add(p.stem.lower())

    for p in list(smart_dir.glob("*.scrate")):
        if not is_broken_serato_smart_crate_name(p.name):
            continue
        parts = _split_broken_smart_stem(p.stem)
        if not parts:
            continue
        # zawsze z korzeniem VDJ gdy brak
        if parts[0].upper() != "VDJ":
            parts = ("VDJ",) + parts
        new_stem = serato_smart_crate_stem(parts, used)
        dest = smart_dir / f"{new_stem}.scrate"
        renamed.append({"from": p.name, "to": dest.name, "parts": list(parts)})
        if not dry_run:
            if dest.resolve() != p.resolve():
                if dest.exists():
                    dest.unlink()
                p.rename(dest)
        candidates = {
            "%%".join(parts),
            "%%".join(safe_serato_crate_segment(x) for x in parts),
        }
        if sub_dir.is_dir():
            for stem in candidates:
                fp = sub_dir / f"{stem}.crate"
                if fp.is_file():
                    removed_sub.append(fp.name)
                    if not dry_run:
                        try:
                            fp.unlink()
                        except OSError:
                            pass

    return {
        "ok": True,
        "renamed": renamed,
        "removed_subcrates": removed_sub,
        "dry_run": dry_run,
        "smart_dir": str(smart_dir),
    }


def finalize_serato_smart_vs_regular(serato_dir: Optional[Path] = None) -> dict:
    """Po eksporcie/naprawie: zero dubli Smart vs zwykły crate o tej samej nazwie."""
    r1 = repair_serato_smart_crate_filenames(serato_dir, dry_run=False)
    r2 = remove_subcrates_duplicating_smart_crates(serato_dir, dry_run=False)
    return {
        "ok": True,
        "renamed": r1.get("renamed") or [],
        "removed_subcrates": list(
            dict.fromkeys(
                list(r1.get("removed_subcrates") or []) + list(r2.get("removed") or [])
            )
        ),
    }


def cleanup_serato_smart_crate_names(
    serato_dir: Optional[Path] = None,
    *,
    remove_vdj_subcrate_leaves: Optional[set[str]] = None,
    dry_run: bool = False,
) -> dict:
    """
    Najpierw naprawia nazwy (rename), potem usuwa wskazane liście Subcrates.
    """
    repair = repair_serato_smart_crate_filenames(serato_dir, dry_run=dry_run)
    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    sub_dir = base / "Subcrates"
    removed_sub: list[str] = list(repair.get("removed_subcrates") or [])
    leaves = remove_vdj_subcrate_leaves or set()
    if leaves and sub_dir.is_dir():
        for stem in leaves:
            if "%%" not in stem and not stem.startswith("VDJ"):
                continue
            fp = sub_dir / f"{stem}.crate"
            if fp.is_file():
                if fp.name not in removed_sub:
                    removed_sub.append(fp.name)
                if not dry_run:
                    try:
                        fp.unlink()
                    except OSError:
                        pass
    return {
        "ok": True,
        "smart_dir": str(base / "SmartCrates"),
        "renamed": repair.get("renamed") or [],
        "removed_smart": [],
        "removed_subcrates": removed_sub,
        "dry_run": dry_run,
    }


def install_serato_smart_crates_from_tree(
    playlists: list,
    serato_dir: Optional[Path] = None,
    *,
    replace_broken: bool = True,
) -> dict:
    """
    Zapisuje Smart Crates z drzewa VDJ (czytelne nazwy) i odbudowuje drzewo Subcrates.
    Usuwa zepsute nazwy, duble płaskie oraz legacy MyLists%% (bez VDJ%%).
    """
    from serato_smart_crate import save_serato_smart_crate, vdj_filter_to_serato_rules

    base = Path(serato_dir) if serato_dir else Path.home() / "Music" / "_Serato_"
    smart_dir = base / "SmartCrates"
    smart_dir.mkdir(parents=True, exist_ok=True)

    if replace_broken:
        cleanup_serato_smart_crate_names(base)

    # Najpierw pełne drzewo folderów + listy nie-smart (hierarchia VDJ%%…)
    tree_stats = install_serato_subcrate_tree_from_playlists(
        playlists or [], base, write_tracks=True
    )

    smart_entries = iter_serato_smart_crate_files(playlists or [])
    written: list[str] = []
    skipped: list[str] = []
    sub_leaves_to_remove: set[str] = set()

    for display_stem, filt, path_parts in smart_entries:
        rules = vdj_filter_to_serato_rules(filt)
        if not rules:
            skipped.append(display_stem)
            continue
        out = smart_dir / f"{display_stem}.scrate"
        out.write_bytes(save_serato_smart_crate(rules))
        written.append(display_stem)
        # liść hierarchii Subcrates do usunięcia (zastąpiony Smart Crate)
        if path_parts:
            sub_leaves_to_remove.add("%%".join(path_parts))

    # Usuń stare płaskie / %% Smart Crates zastąpione hierarchią ≫≫
    keep = {w.lower() for w in written}
    removed_old_smart: list[str] = []
    for p in list(smart_dir.glob("*.scrate")):
        if p.stem.lower() in keep:
            continue
        # zostaw tylko jeśli nie jest naszym starym eksportem (płaski liść / %%)
        leaf = normalize_serato_leaf_name(serato_smart_crate_leaf(p.stem))
        written_leaves = {
            normalize_serato_leaf_name(serato_smart_crate_leaf(w)) for w in written
        }
        if (
            SERATO_SMART_SEP not in p.stem
            or "%%" in p.stem
            or leaf in written_leaves
        ):
            removed_old_smart.append(p.name)
            try:
                p.unlink()
            except OSError:
                pass

    cleanup_serato_smart_crate_names(
        base, remove_vdj_subcrate_leaves=sub_leaves_to_remove
    )
    dup = remove_subcrates_duplicating_smart_crates(base)
    flat = cleanup_orphan_flat_subcrates(base)
    legacy = cleanup_legacy_mylists_prefix_crates(base)

    # Upewnij się, że foldery-przodkowie istnieją w Subcrates (drzewo Crates)
    sub_dir = base / "Subcrates"
    sub_dir.mkdir(parents=True, exist_ok=True)
    parents_written = 0
    for _stem, _filt, path_parts in smart_entries:
        for i in range(1, len(path_parts)):
            parent_stem = "%%".join(path_parts[:i])
            parent_file = sub_dir / f"{parent_stem}.crate"
            if not parent_file.is_file():
                parent_file.write_bytes(save_serato_crate([], parent_stem))
                parents_written += 1

    return {
        "ok": True,
        "written": written,
        "skipped": skipped,
        "parents_ensured": parents_written,
        "tree_crates": tree_stats.get("count") or 0,
        "removed_subcrate_leaves": sorted(sub_leaves_to_remove),
        "removed_name_duplicates": dup.get("removed") or [],
        "removed_flat_orphans": flat.get("removed") or [],
        "removed_legacy_mylists": legacy.get("removed") or [],
        "removed_old_smart": removed_old_smart,
        "smart_dir": str(smart_dir),
    }
