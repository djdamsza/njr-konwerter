"""
Parser bazy Serato DJ – DatabaseV2 i pliki .crate.
Format binarny (tag 4B + length 4B + data). Źródło: Holzhaus/serato-tags, Mixxx wiki.
Import do formatu _songs (VDJ-style).
"""
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


def _parse_track(otrk: list) -> Optional[Track]:
    """Wyciąga Track z rekordu otrk (lista (name, value))."""
    path = ""
    title = ""
    artist = ""
    genre = ""
    comment = ""
    play_count = 0
    rating = 0
    bpm = 0.0
    key = ""
    duration = 0.0
    bitrate = 0
    for name, value in otrk:
        if name == "pfil" or name == "ptrk":
            path = (value or "").strip()
        elif name == "tsng":
            title = (value or "").strip()
        elif name == "tart":
            artist = (value or "").strip()
        elif name == "tgen":
            genre = (value or "").strip()
        elif name == "tcom":
            raw = (value or "").strip()
            if " | Rating: " in raw:
                parts = raw.split(" | Rating: ", 1)
                comment = parts[0].strip()
                try:
                    rating = min(5, max(0, int(parts[1].strip())))
                except (ValueError, IndexError):
                    pass
            else:
                comment = raw
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
        genre=genre or "",
        tags=tags,
        comment=comment or "",
        play_count=play_count,
        rating=rating_255,
        bpm=bpm,
        key=key or "",
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


def _path_to_serato_relative(path: str, drive_root: Optional[str] = None) -> str:
    """
    Konwertuje ścieżkę na format Serato – względną do roota dysku.
    Serato wymaga ścieżek względnych (np. Music/song.mp3), nie absolutnych.
    drive_root: np. C:\\, / (dysk główny macOS), /Volumes/DriveName/
    """
    p = (path or "").strip()
    if not p:
        return ""
    p_norm = p.replace("\\", "/")
    if drive_root is not None and (drive_root or "").strip():
        root = (drive_root or "").strip().rstrip("/\\")
        root_norm = (root.replace("\\", "/") + "/") if root else "/"
        if root_norm == "/":
            # Dysk główny macOS – ścieżka względna do /
            if p_norm.startswith("/"):
                p = p_norm[1:].lstrip("/")
        elif root:
            if p_norm.lower().startswith(root_norm.lower()):
                p = p_norm[len(root_norm):].lstrip("/")
            elif len(p) > len(root) and (p.replace("/", "\\").lower().startswith(root.lower() + "\\") or p.lower().startswith(root.lower() + "/")):
                p = p[len(root):].lstrip("\\/")
    return p.replace("\\", "/")


def save_serato_database_v2(songs: list[dict], drive_root: Optional[str] = None) -> bytes:
    """
    Generuje plik DatabaseV2 Serato z listy _songs (VDJ-style).
    drive_root: root dysku – ścieżki względne. Mac główny: /. Zewnętrzny: /Volumes/Nazwa/.
    Format zgodny z oryginalnym Serato (2.0/Serato Scratch LIVE Database).
    Eksportuje: Genre (tgen), Comment+Rating (tcom), Play count (utpc).
    Uwaga: Cue points (hot cues) Serato przechowuje w plikach audio (Serato Markers_/Markers2),
    nie w Database V2 – do ich przeniesienia potrzebne jest zapisanie do plików MP3/FLAC.
    """
    import time
    buf = BytesIO()
    _write_serato_record(buf, "vrsn", _encode_utf16be("2.0/Serato Scratch LIVE Database"))
    now = int(time.time())
    for s in songs:
        path = _path_to_serato_relative((s.get("FilePath") or "").strip(), drive_root)
        if not path:
            continue
        title = (s.get("Tags.Title") or s.get("Tags.Author") or "").strip() or Path(path).stem
        artist = (s.get("Tags.Author") or s.get("Tags.Artist") or "").strip()
        bpm = 0.0
        try:
            bpm_raw = s.get("Tags.Bpm", "")
            if bpm_raw:
                val = float(bpm_raw)
                bpm = 60.0 / val if 0.2 <= val <= 2.0 else (val if 20 <= val <= 300 else 0.0)
        except (TypeError, ValueError):
            pass
        key = (s.get("Tags.Key") or "").strip()
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
        if bpm > 0:
            _write_serato_record(otrk, "tbpm", _encode_utf16be(f"{bpm:.2f}"))
        if key:
            _write_serato_record(otrk, "tkey", _encode_utf16be(key))
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
        g = (s.get("Tags.Genre") or "").strip()
        u1 = (s.get("Tags.User1") or "").strip()
        u2 = (s.get("Tags.User2") or "").strip()
        genre_str = " ".join(x for x in (g, u1, u2) if x)
        if genre_str:
            _write_serato_record(otrk, "tgen", _encode_utf16be(genre_str))
        comment = _get_comment_from_song(s)
        rating = 0
        try:
            raw = s.get("Tags.Stars") or s.get("Infos.Rating") or s.get("Tags.Rating") or 0
            if raw is not None and str(raw).strip():
                val = int(float(raw))
                rating = min(5, max(0, val // 51 if val > 5 else val))
        except (TypeError, ValueError):
            pass
        if comment or rating:
            tcom_val = comment
            if rating:
                tcom_val = f"{tcom_val} | Rating: {rating}" if tcom_val else f"Rating: {rating}"
            _write_serato_record(otrk, "tcom", _encode_utf16be(tcom_val))
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
        _write_serato_record(buf, "otrk", otrk.getvalue())
    return buf.getvalue()


def save_serato_crate(track_paths: list[str], crate_name: str, drive_root: Optional[str] = None) -> bytes:
    """Generuje plik .crate z listą ścieżek utworów. drive_root – jak w save_serato_database_v2."""
    buf = BytesIO()
    _write_serato_record(buf, "vrsn", _encode_utf16be("1.0/Serato ScratchLive Crate"))
    for path in track_paths:
        p = _path_to_serato_relative((path or "").strip(), drive_root)
        if not p:
            continue
        otrk = BytesIO()
        _write_serato_record(otrk, "ptrk", _encode_utf16be(p))
        _write_serato_record(buf, "otrk", otrk.getvalue())
    return buf.getvalue()
