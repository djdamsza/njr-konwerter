"""
Zapis tagów ID3 do plików audio (inspiracja Lexicon).
Gdy VDJ czyta RB master.db – metadane bierze z plików, nie z bazy.
Zapis tagów zapewnia poprawne wyświetlanie Title/Artist/Genre w VDJ.

Eksport tagów do ID3: zapisuje Genre, User1, User2 (wszystkie tagi) do pola Genre w pliku MP3.
Tagi są wpisywane bezpośrednio do plików – zmiany są trwałe.
"""
from pathlib import Path
from typing import Optional

from unified_model import Track


def _is_streaming_path(path: str) -> bool:
    """Czy ścieżka to utwór streamingowy (Tidal, SoundCloud, Beatport Link itd.) – nie ma pliku lokalnego."""
    p = (path or "").lower()
    return any(
        p.startswith(x)
        for x in (
            "tidal:", "soundcloud:", "beatport:",
            "file://localhosttidal:", "file://localhostsoundcloud:", "file://localhostbeatport:",
        )
    )


def _genre_for_id3(track: Track) -> str:
    """Wszystkie tagi (Genre+User1+User2) łączone do pola Genre w ID3 – umożliwia wyszukiwanie."""
    if track.tags:
        return " ".join(t for t in track.tags if t)
    return track.genre or ""


def write_tags_to_file(track: Track, path: Optional[str] = None) -> tuple[bool, str]:
    """
    Zapisuje metadane (Title, Artist, Album, Genre) do pliku audio.
    Genre = wszystkie tagi (Genre+User1+User2) – umożliwia wyszukiwanie w programach DJ.
    Obsługuje: MP3, FLAC, M4A, OGG, WAV, AIFF.
    Zwraca: (sukces, komunikat). Dla streaming: (False, "STREAMING_SKIP").
    """
    p = path or track.path
    if _is_streaming_path(p):
        return False, "STREAMING_SKIP"
    file_path = Path(p)
    if not file_path.exists():
        return False, f"Plik nie istnieje: {file_path}"

    ext = file_path.suffix.lower()
    if ext not in ('.mp3', '.flac', '.m4a', '.ogg', '.opus', '.wav', '.aiff', '.aif'):
        return False, f"Format nieobsługiwany: {ext}"

    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3
        from mutagen.flac import FLAC
        from mutagen.mp4 import MP4
        from mutagen.oggvorbis import OggVorbis
        from mutagen.oggopus import OggOpus
        from mutagen.wave import WAVE
        from mutagen.aiff import AIFF
    except ImportError:
        return False, "Brak mutagen: pip install mutagen"

    try:
        if ext == '.mp3':
            try:
                audio = EasyID3(str(file_path))
            except Exception:
                from mutagen.mp3 import MP3
                m = MP3(str(file_path))
                if m.tags is None:
                    m.add_tags()
                    m.save()
                audio = EasyID3(str(file_path))
            if track.title:
                audio['title'] = track.title
            if track.artist:
                audio['artist'] = track.artist
            if track.album:
                audio['album'] = track.album
            genre_val = _genre_for_id3(track)
            if genre_val:
                audio['genre'] = genre_val
            if track.year:
                audio['date'] = str(track.year)
            audio.save()

        elif ext == '.flac':
            audio = FLAC(str(file_path))
            if track.title:
                audio['title'] = track.title
            if track.artist:
                audio['artist'] = track.artist
            if track.album:
                audio['album'] = track.album
            genre_val = _genre_for_id3(track)
            if genre_val:
                audio['genre'] = genre_val
            if track.year:
                audio['date'] = str(track.year)
            audio.save()

        elif ext in ('.m4a', '.mp4'):
            audio = MP4(str(file_path))
            if track.title:
                audio['\xa9nam'] = track.title
            if track.artist:
                audio['\xa9ART'] = track.artist
            if track.album:
                audio['\xa9alb'] = track.album
            genre_val = _genre_for_id3(track)
            if genre_val:
                audio['\xa9gen'] = genre_val
            if track.year:
                audio['\xa9day'] = str(track.year)
            audio.save()

        elif ext == '.ogg':
            audio = OggVorbis(str(file_path))
            if track.title:
                audio['title'] = track.title
            if track.artist:
                audio['artist'] = track.artist
            if track.album:
                audio['album'] = track.album
            genre_val = _genre_for_id3(track)
            if genre_val:
                audio['genre'] = genre_val
            if track.year:
                audio['date'] = str(track.year)
            audio.save()

        elif ext == '.opus':
            audio = OggOpus(str(file_path))
            if track.title:
                audio['title'] = track.title
            if track.artist:
                audio['artist'] = track.artist
            if track.album:
                audio['album'] = track.album
            genre_val = _genre_for_id3(track)
            if genre_val:
                audio['genre'] = genre_val
            if track.year:
                audio['date'] = str(track.year)
            audio.save()

        elif ext in ('.wav', '.aiff', '.aif'):
            # WAV/AIFF – ID3 przez mutagen.id3
            from mutagen.id3 import TIT2, TPE1, TALB, TCON, TDRC
            cls = WAVE if ext == '.wav' else AIFF
            audio = cls(str(file_path))
            if audio.tags is None:
                audio.add_tags()
            if track.title:
                audio.tags.add(TIT2(encoding=3, text=track.title))
            if track.artist:
                audio.tags.add(TPE1(encoding=3, text=track.artist))
            if track.album:
                audio.tags.add(TALB(encoding=3, text=track.album))
            genre_val = _genre_for_id3(track)
            if genre_val:
                audio.tags.add(TCON(encoding=3, text=genre_val))
            if track.year:
                audio.tags.add(TDRC(encoding=3, text=str(track.year)))
            audio.save()

        else:
            return False, f"Format nieobsługiwany: {ext}"

        return True, "OK"
    except Exception as e:
        return False, str(e)


def write_tags_batch(tracks: list[Track], path_resolver=None) -> tuple[int, int, int, list[str]]:
    """
    Zapisuje tagi do wielu plików.
    path_resolver: opcjonalnie (track) -> str – ścieżka pliku (np. po path_replace).
    Zwraca: (zapisane, pominięte_streaming, błędy, lista_błędów).
    """
    ok, skipped, err = 0, 0, 0
    errors = []
    for t in tracks:
        path = path_resolver(t) if path_resolver else t.path
        success, msg = write_tags_to_file(t, path)
        if success:
            ok += 1
        elif msg == "STREAMING_SKIP":
            skipped += 1
        else:
            err += 1
            errors.append(f"{Path(path).name}: {msg}")
    return ok, skipped, err, errors
