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


def strip_rating_hack_from_comment(comment: Optional[str]) -> str:
    """Usuwa stary hack „Rating: N” / „… | Rating: N” z komentarza (Serato ★ ≠ comment)."""
    c = (comment or "").strip()
    if not c:
        return ""
    if " | Rating: " in c:
        c = c.split(" | Rating: ", 1)[0].strip()
    if c.startswith("Rating: "):
        rest = c[8:].strip()
        if rest.isdigit() or (rest[:1].isdigit() and rest[1:].strip() == ""):
            return ""
        # „Rating: 4 something” — zostaw bez prefiksu tylko gdy to czysty numer
        if rest.split()[0].isdigit() and len(rest.split()) == 1:
            return ""
    return c


def unified_rating_to_stars(rating_255: int) -> int:
    """Unified 0–255 (VDJ/RB) → 1–5 gwiazdek Serato."""
    if not rating_255 or rating_255 <= 0:
        return 0
    return min(5, max(1, round(int(rating_255) / 51)))


def serato_popm_from_stars(stars: int) -> int:
    """Skala POPM Serato: 1★=1, 2★=64, 3★=128, 4★=196, 5★=255."""
    return {1: 1, 2: 64, 3: 128, 4: 196, 5: 255}.get(min(5, max(1, int(stars))), 0)


def serato_rate_pct_from_stars(stars: int) -> int:
    """Atom M4A ``rate`` / ``rtng``: 20/40/60/80/100."""
    return min(5, max(1, int(stars))) * 20


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


def write_dj_extended_metadata(track: Track, path: Optional[str] = None) -> tuple[bool, str]:
    """
    BPM, key, rating (POPM/rtng), comment — pola używane przez Serato / DJ software.
    """
    p = path or track.path
    if _is_streaming_path(p):
        return False, "STREAMING_SKIP"
    file_path = Path(p)
    if not file_path.is_file():
        return False, f"Plik nie istnieje: {file_path}"

    ext = file_path.suffix.lower()
    if ext not in (".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".wav", ".aiff", ".aif"):
        return False, f"Format nieobsługiwany: {ext}"

    wrote = False
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError, POPM, TBPM, TKEY, TXXX, COMM, TCOM
        from mutagen.mp3 import MP3
        from mutagen.flac import FLAC
        from mutagen.mp4 import MP4, MP4FreeForm
        from mutagen.wave import WAVE
        from mutagen.aiff import AIFF
    except ImportError:
        return False, "Brak mutagen"

    try:
        if ext == ".mp3":
            try:
                tags = ID3(str(file_path))
            except ID3NoHeaderError:
                tags = ID3()
            if track.bpm and track.bpm > 0:
                tags.delall("TBPM")
                tags.add(TBPM(encoding=3, text=str(int(round(track.bpm)))))
                wrote = True
            if track.key:
                tags.delall("TKEY")
                tags.add(TKEY(encoding=3, text=track.key))
                wrote = True
            if track.rating and track.rating > 0:
                stars = unified_rating_to_stars(track.rating)
                popm_val = serato_popm_from_stars(stars)
                tags.delall("POPM:Serato")
                tags.delall("POPM:")
                tags.add(POPM(email="", rating=popm_val, count=0))
                wrote = True
            cmt = strip_rating_hack_from_comment(track.comment)
            if cmt:
                tags.delall("COMM::eng")
                tags.add(COMM(encoding=3, lang="eng", desc="", text=cmt))
                wrote = True
            elif track.comment and strip_rating_hack_from_comment(track.comment) == "":
                # sam hack Rating: — wyczyść COMM jeśli tylko to
                for key in list(tags.keys()):
                    if key.startswith("COMM"):
                        texts = [str(t) for t in getattr(tags[key], "text", [])]
                        if texts and all(
                            strip_rating_hack_from_comment(t) == "" for t in texts
                        ):
                            del tags[key]
                            wrote = True
            if wrote:
                tags.save(str(file_path), v2_version=3)

        elif ext == ".flac":
            audio = FLAC(str(file_path))
            if track.bpm and track.bpm > 0:
                audio["bpm"] = str(int(round(track.bpm)))
                wrote = True
            if track.key:
                audio["initialkey"] = track.key
                wrote = True
            if track.rating and track.rating > 0:
                stars = unified_rating_to_stars(track.rating)
                audio["rating"] = str(stars)
                wrote = True
            cmt = strip_rating_hack_from_comment(track.comment)
            if cmt:
                audio["comment"] = cmt
                wrote = True
            if wrote:
                audio.save()

        elif ext in (".m4a", ".mp4"):
            audio = MP4(str(file_path))
            if track.bpm and track.bpm > 0:
                audio["tmpo"] = [int(round(track.bpm))]
                wrote = True
            if track.key:
                audio["----:com.apple.iTunes:initialkey"] = [
                    MP4FreeForm(track.key.encode("utf-8"))
                ]
                wrote = True
            if track.rating and track.rating > 0:
                # Serato M4A: kolumna ★ czyta atom „rate” (string 20/40/…/100)
                stars = unified_rating_to_stars(track.rating)
                pct = serato_rate_pct_from_stars(stars)
                audio["rate"] = [str(pct)]
                audio["rtng"] = [pct]
                wrote = True
            cmt = strip_rating_hack_from_comment(track.comment)
            if cmt:
                audio["\xa9cmt"] = [cmt]
                wrote = True
            if wrote:
                audio.save()

        elif ext in (".wav", ".aiff", ".aif"):
            cls = WAVE if ext == ".wav" else AIFF
            audio = cls(str(file_path))
            if audio.tags is None:
                audio.add_tags()
            if track.bpm and track.bpm > 0:
                audio.tags.delall("TBPM")
                audio.tags.add(TBPM(encoding=3, text=str(int(round(track.bpm)))))
                wrote = True
            if track.key:
                audio.tags.delall("TKEY")
                audio.tags.add(TKEY(encoding=3, text=track.key))
                wrote = True
            if track.rating and track.rating > 0:
                stars = unified_rating_to_stars(track.rating)
                popm_val = serato_popm_from_stars(stars)
                audio.tags.delall("POPM:Serato")
                audio.tags.delall("POPM:")
                audio.tags.add(POPM(email="", rating=popm_val, count=0))
                wrote = True
            cmt = strip_rating_hack_from_comment(track.comment)
            if cmt:
                audio.tags.delall("COMM::eng")
                audio.tags.add(COMM(encoding=3, lang="eng", desc="", text=cmt))
                wrote = True
            if wrote:
                audio.save()

        return (True, "OK") if wrote else (False, "NOTHING_TO_WRITE")
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
