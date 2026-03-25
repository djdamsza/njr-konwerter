"""
Analiza plików audio – brakujące, bitrate, metadane ID3.
Wymaga dostępu do plików na dysku.
"""
from pathlib import Path
from typing import Optional, Tuple

from tag_writer import _is_streaming_path


def _is_streaming_or_remote(path: str) -> bool:
    """Czy ścieżka to streaming (Tidal, netsearch) – nie ma pliku lokalnego."""
    if not path:
        return True
    p = (path or "").strip()
    if _is_streaming_path(p):
        return True
    if p.startswith("netsearch:"):
        return True
    if p.startswith("td") and len(p) > 2 and p[2:].isdigit():
        return True
    return False


def read_file_metadata_extended(path: str) -> dict:
    """
    Odczytuje pełne metadane z pliku audio (artist, title, genre, bpm, length, key, rating).
    Zwraca dict z kluczami: artist, title, album, genre, year, bpm, length, key, rating.
    """
    result = {
        "artist": "", "title": "", "album": "", "genre": "", "year": 0, "bpm": 0.0,
        "length": 0, "key": "", "rating": ""
    }
    if not path or _is_streaming_or_remote(path):
        return result
    p = Path(path)
    if not p.exists() or not p.is_file():
        return result
    artist, title, album, genre, year, bpm = read_file_metadata(path)
    result.update(artist=artist or "", title=title or "", album=album or "", genre=genre or "", year=year, bpm=bpm)
    ext = p.suffix.lower()
    try:
        if ext in (".mp3", ".mp2", ".mp1"):
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3
            audio = MP3(str(path))
            result["length"] = int(audio.info.length) if audio.info.length else 0
            try:
                id3 = ID3(str(path))
                if "TKEY" in id3 and id3["TKEY"].text:
                    result["key"] = (id3["TKEY"].text[0] or "").strip()
                for frame in id3.getall("TXXX"):
                    d = getattr(frame, "desc", "")
                    if d and d.lower() in ("initial key", "key", "tonality") and frame.text:
                        result["key"] = (frame.text[0] or "").strip()
                        break
                for frame in id3.getall("POPM"):
                    if hasattr(frame, "rating") and frame.rating is not None:
                        r = frame.rating
                        if r <= 0:
                            result["rating"] = "0"
                        else:
                            result["rating"] = str(min(5, max(1, round(r / 51))))
                        break
            except Exception:
                pass
        elif ext in (".m4a", ".mp4", ".aac"):
            from mutagen.mp4 import MP4
            audio = MP4(path)
            result["length"] = int(audio.info.length) if audio.info.length else 0
            if "----:com.apple.iTunes:initialkey" in audio:
                try:
                    result["key"] = (audio["----:com.apple.iTunes:initialkey"][0].decode("utf-8", errors="ignore") or "").strip()
                except Exception:
                    pass
        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(path)
            result["length"] = int(audio.info.length) if audio.info.length else 0
            if "initialkey" in audio:
                result["key"] = (audio["initialkey"][0] or "").strip()
            if "rating" in audio:
                try:
                    result["rating"] = str(min(5, max(0, int(float(audio["rating"][0])))))
                except Exception:
                    pass
        elif ext in (".ogg", ".opus"):
            try:
                from mutagen.oggvorbis import OggVorbis
                audio = OggVorbis(path)
            except Exception:
                try:
                    from mutagen.oggopus import OggOpus
                    audio = OggOpus(path)
                except Exception:
                    return result
            result["length"] = int(audio.info.length) if audio.info.length else 0
            if "initialkey" in audio:
                result["key"] = (audio["initialkey"][0] or "").strip()
    except Exception:
        pass
    return result


def read_file_metadata(path: str) -> Tuple[str, str, str, str, int, float]:
    """
    Odczytuje Artist, Title, Album, Genre, Year, BPM z pliku audio (ID3/Vorbis/MP4).
    Zwraca (artist, title, album, genre, year, bpm). Puste stringi gdy brak, bpm=0.0.
    Dla streaming (Tidal, netsearch) zwraca puste.
    """
    if not path or _is_streaming_or_remote(path):
        return "", "", "", "", 0, 0.0
    p = Path(path)
    if not p.exists():
        return "", "", "", "", 0, 0.0
    ext = p.suffix.lower()
    artist, title, album, genre, year, bpm = "", "", "", "", 0, 0.0
    try:
        if ext in (".mp3", ".mp2", ".mp1"):
            from mutagen.easyid3 import EasyID3
            from mutagen.id3 import ID3
            try:
                audio = EasyID3(str(path))
                artist = (audio.get("artist") or [""])[0]
                title = (audio.get("title") or [""])[0]
                album = (audio.get("album") or [""])[0]
                genre = (audio.get("genre") or [""])[0]
                date = (audio.get("date") or [""])[0]
                if date and date[:4].isdigit():
                    year = int(date[:4])
                # BPM: TBPM (ID3) lub TXXX z desc "BPM"
                try:
                    id3 = ID3(str(path))
                    if "TBPM" in id3:
                        bpm = float(id3["TBPM"].text[0])
                    else:
                        for frame in id3.getall("TXXX"):
                            if getattr(frame, "desc", "") == "BPM" and frame.text:
                                bpm = float(frame.text[0])
                                break
                except Exception:
                    pass
            except Exception:
                pass
        elif ext in (".m4a", ".mp4", ".aac"):
            from mutagen.mp4 import MP4
            audio = MP4(path)
            artist = (audio.get("\xa9ART") or [""])[0]
            title = (audio.get("\xa9nam") or [""])[0]
            album = (audio.get("\xa9alb") or [""])[0]
            genre = (audio.get("\xa9gen") or [""])[0]
            date = (audio.get("\xa9day") or [""])[0]
            if date and date[:4].isdigit():
                year = int(date[:4])
            # BPM w tmpo (Rekordbox/MIXO zapisuje)
            if "tmpo" in audio:
                try:
                    bpm = float(audio["tmpo"][0])
                except Exception:
                    pass
        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(path)
            artist = (audio.get("artist") or [""])[0]
            title = (audio.get("title") or [""])[0]
            album = (audio.get("album") or [""])[0]
            genre = (audio.get("genre") or [""])[0]
            date = (audio.get("date") or [""])[0]
            if date and date[:4].isdigit():
                year = int(date[:4])
            if "bpm" in audio:
                try:
                    bpm = float(audio["bpm"][0])
                except Exception:
                    pass
        elif ext in (".ogg", ".opus"):
            try:
                from mutagen.oggvorbis import OggVorbis
                audio = OggVorbis(path)
            except Exception:
                try:
                    from mutagen.oggopus import OggOpus
                    audio = OggOpus(path)
                except Exception:
                    return "", "", "", "", 0, 0.0
            artist = (audio.get("artist") or [""])[0]
            title = (audio.get("title") or [""])[0]
            album = (audio.get("album") or [""])[0]
            genre = (audio.get("genre") or [""])[0]
            date = (audio.get("date") or [""])[0]
            if date and date[:4].isdigit():
                year = int(date[:4])
    except Exception:
        pass
    return (artist or "", title or "", album or "", genre or "", year, bpm)


def _get_bitrate(path: str) -> Optional[int]:
    """Odczytuje bitrate (kbps) z pliku. Zwraca None jeśli nie można odczytać."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    ext = p.suffix.lower()
    try:
        if ext == ".mp3":
            from mutagen.mp3 import MP3
            info = MP3(path).info
            return int(info.bitrate / 1000) if info.bitrate else None
        if ext in (".m4a", ".mp4", ".aac"):
            from mutagen.mp4 import MP4
            info = MP4(path).info
            if hasattr(info, "bitrate") and info.bitrate:
                return int(info.bitrate / 1000)
            return None
        if ext == ".flac":
            from mutagen.flac import FLAC
            info = FLAC(path).info
            if hasattr(info, "bits_per_sample") and info.sample_rate:
                return int(info.sample_rate * (info.bits_per_sample or 16) * (info.channels or 2) / 1000)
            return None
        if ext == ".ogg":
            try:
                from mutagen.oggvorbis import OggVorbis
                f = OggVorbis(path)
                return int(f.info.bitrate / 1000) if f.info.bitrate else None
            except Exception:
                return None
        if ext == ".opus":
            try:
                from mutagen.oggopus import OggOpus
                f = OggOpus(path)
                return int(f.info.bitrate / 1000) if f.info.bitrate else None
            except Exception:
                return None
    except Exception:
        pass
    return None


def is_streaming(path: str) -> bool:
    """Czy ścieżka to utwór streamingowy (Tidal, SoundCloud itd.)."""
    if not path:
        return False
    p = (path or "").strip().lower()
    if p.startswith("td") and len(p) > 2 and p[2:].isdigit():
        return True
    if p.startswith("netsearch:"):
        return True
    return _is_streaming_path(path)
