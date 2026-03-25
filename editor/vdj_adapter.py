"""
Adapter VDJ ↔ Unified model.
Konwersja między formatem _songs (dict) a UnifiedDatabase.
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from unified_model import (
    UnifiedDatabase,
    Track,
    Playlist,
    BeatgridPoint,
    CuePoint,
)
from vdj_parser import parse_tags_value, join_tags


def _parse_comment(children_xml: list) -> str:
    """Wyciąga tekst z elementu Comment."""
    for xml_str in children_xml or []:
        try:
            elem = ET.fromstring(xml_str)
            if elem.tag == "Comment" and elem.text:
                return (elem.text or "").strip()[:1024]
        except (ET.ParseError, ValueError):
            continue
    return ""


def _parse_scan_key(children_xml: list) -> str:
    """Wyciąga Key z elementu Scan (gdy Tags.Key pusty)."""
    for xml_str in children_xml or []:
        try:
            elem = ET.fromstring(xml_str)
            if elem.tag == "Scan":
                return (elem.get("Key") or "").strip()
        except (ET.ParseError, ValueError):
            continue
    return ""


def _parse_poi_children(children_xml: list) -> tuple[list[BeatgridPoint], list[CuePoint]]:
    """Parsuje _children_xml i wyciąga beatgrid + cue points z elementów Poi."""
    beatgrid = []
    cue_points = []
    for xml_str in children_xml or []:
        try:
            elem = ET.fromstring(xml_str)
            if elem.tag != "Poi":
                continue
            poi_type = elem.get("Type", "")
            if poi_type == "beatgrid":
                pos = float(elem.get("Pos", "0") or "0")
                bpm = float(elem.get("Bpm", "0") or "0")
                if bpm > 0:
                    beatgrid.append(BeatgridPoint(pos=pos, bpm=bpm))
            elif poi_type == "cue":
                name = elem.get("Name", "Cue")
                pos = float(elem.get("Pos", "0") or "0")
                num = int(elem.get("Num", "0") or "0")
                color_str = elem.get("Color", "")
                color = int(color_str) if color_str else None
                cue_points.append(CuePoint(name=name, pos=pos, num=num, color=color))
        except (ET.ParseError, ValueError):
            continue
    return beatgrid, cue_points


def vdj_songs_to_unified(songs: list[dict]) -> UnifiedDatabase:
    """
    Konwertuje listę utworów VDJ (_songs) na UnifiedDatabase.
    """
    tracks = []
    for s in songs:
        path = s.get("FilePath", "")
        if not path:
            continue

        # Tagi
        genre = s.get("Tags.Genre", "") or ""
        user1 = s.get("Tags.User1", "") or ""
        user2 = s.get("Tags.User2", "") or ""
        tags = list(parse_tags_value(genre)) + list(parse_tags_value(user1)) + list(parse_tags_value(user2))
        tags = list(dict.fromkeys(tags))  # unikalne bez zmiany kolejności

        beatgrid, cue_points = _parse_poi_children(s.get("_children_xml", []))
        children_xml = s.get("_children_xml", [])

        # Key: Tags.Key lub Scan.Key
        key = s.get("Tags.Key", "") or ""
        if not key:
            key = _parse_scan_key(children_xml)

        # Comment: VDJ <Comment> (nie tagi – tagi idą do My Tags)
        comment = _parse_comment(children_xml)

        # BPM: preferuj beatgrid (Poi Bpm=130.0) – zawsze rzeczywiste BPM
        # Tags.Bpm = 60/bpm_display gdy val 0.2–2; czasem val to bezpośrednio BPM (30–300)
        bpm = 0.0
        if beatgrid:
            bpm = beatgrid[0].bpm  # pierwszy punkt beatgridu
        bpm_raw = s.get("Tags.Bpm", "")
        if bpm_raw and not bpm:
            try:
                val = float(bpm_raw)
                if 0.2 <= val <= 2.0:
                    bpm = 60.0 / val  # format 60/bpm
                elif 20 <= val <= 300:
                    bpm = val  # bezpośrednio BPM
            except ValueError:
                pass

        # Duration z Infos.SongLength (sekundy)
        duration = 0.0
        sl = s.get("Infos.SongLength", "")
        if sl:
            try:
                duration = float(sl)
            except ValueError:
                pass

        # Rating: VDJ Stars 0–5 → RB 0,51,102,153,204,255
        stars = 0
        stars_raw = s.get("Tags.Stars", "")
        if stars_raw:
            try:
                sval = int(stars_raw)
                stars = min(5, max(0, sval))
            except ValueError:
                pass
        rating = int(stars * 51) if stars else 0  # 0→0, 1→51, 2→102, 3→153, 4→204, 5→255

        # PlayCount z Infos.PlayCount
        play_count = 0
        pc = s.get("Infos.PlayCount", "")
        if pc:
            try:
                play_count = int(pc)
            except ValueError:
                pass

        # Artist/Title: VDJ ma Author i Artist – preferuj Author, fallback Artist
        artist = s.get("Tags.Author", "") or s.get("Tags.Artist", "") or ""
        title = s.get("Tags.Title", "") or ""
        album = s.get("Tags.Album", "") or ""
        genre_from_db = genre  # już z Tags.Genre
        year_from_db = int(s.get("Tags.Year", "0") or "0")

        # Fallback: gdy VDJ ma puste metadane, odczytaj z pliku (ID3)
        # Baza VDJ często nie zapisuje Artist/Album/Genre – tylko co użytkownik ręcznie ustawił
        needs_fallback = bool((not artist or not title or not album or not genre_from_db) and path)
        if needs_fallback:
            try:
                from file_analyzer import read_file_metadata
                from pathlib import Path as _P
                f_artist, f_title, f_album, f_genre, f_year, f_bpm = read_file_metadata(path)
                if not artist and f_artist:
                    artist = f_artist
                if not title and f_title:
                    title = f_title
                if not album and f_album:
                    album = f_album
                if not genre_from_db and f_genre:
                    genre = f_genre
                    # Tagi: dodaj genre z pliku jeśli brakowało
                    extra = [t for t in parse_tags_value(f_genre) if t and t not in tags]
                    tags = list(dict.fromkeys(tags + extra))
                if not year_from_db and f_year:
                    year_from_db = f_year
                if not bpm and f_bpm and 20 <= f_bpm <= 300:
                    bpm = f_bpm
            except ImportError:
                pass
            except Exception:
                pass

        if not artist and title:
            # Format "Artist - Title (Remix)" w Title
            if " - " in title:
                parts = title.split(" - ", 1)
                artist, title = parts[0].strip(), parts[1].strip()
        if not artist and not title:
            stem = Path(path).stem
            if " - " in stem:
                parts = stem.split(" - ", 1)
                artist, title = parts[0].strip(), parts[1].strip()
            else:
                title = stem

        tracks.append(Track(
            path=path,
            title=title,
            artist=artist,
            album=album,
            genre=genre,
            tags=tags,
            bpm=bpm,
            key=key,
            year=year_from_db,
            duration=duration,
            play_count=play_count,
            rating=rating,
            comment=comment,
            beatgrid=beatgrid,
            cue_points=cue_points,
            source_id=None,
        ))
    return UnifiedDatabase(tracks=tracks, playlists=[], smart_playlists=[], source="vdj")


def _track_to_vdj_dict(t: Track) -> dict:
    """Konwertuje Track na słownik w formacie VDJ _songs."""
    # VDJ Bpm: 60/bpm
    bpm_val = str(60.0 / t.bpm) if t.bpm > 0 else ""

    # Tagi: Genre osobno, reszta w User1+User2 (połowę każdemu)
    genre_str = t.genre or ""
    all_tags = [x for x in t.tags if x]
    mid = (len(all_tags) + 1) // 2
    user1_str = join_tags(all_tags[:mid])
    user2_str = join_tags(all_tags[mid:])

    children_xml = []
    for bg in t.beatgrid:
        children_xml.append(f'<Poi Pos="{bg.pos:.6f}" Type="beatgrid" Bpm="{bg.bpm:.2f}" />')
    def _esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    for cp in t.cue_points:
        color_attr = f' Color="{cp.color}"' if cp.color is not None else ""
        children_xml.append(f'<Poi Name="{_esc(cp.name)}" Pos="{cp.pos:.6f}" Num="{cp.num}" Type="cue"{color_attr} />')
    if t.comment:
        children_xml.append(f"<Comment>{_esc(t.comment)}</Comment>")

    # Rating: Unified 0–255 (Rekordbox) → VDJ 0–5
    stars = min(5, max(0, t.rating // 51)) if t.rating else 0
    # Infos.SongLength: VDJ używa SongLength (sekundy), nie Duration
    song_len = str(int(t.duration)) if t.duration else ""
    result = {
        "FilePath": t.path,
        "FileSize": "",
        "Flag": "",
        "Tags.Author": t.artist,
        "Tags.Title": t.title,
        "Tags.Album": t.album,
        "Tags.Genre": genre_str,
        "Tags.User1": user1_str,
        "Tags.User2": user2_str,
        "Tags.Bpm": bpm_val,
        "Tags.Key": t.key,
        "Tags.Year": str(t.year),
        "Infos.SongLength": song_len,
        "Infos.PlayCount": str(t.play_count) if t.play_count else "",
        "Tags.Stars": str(stars) if stars else "",
        "_children_xml": children_xml,
    }
    return result


def unified_to_vdj_songs(db: UnifiedDatabase) -> list[dict]:
    """
    Konwertuje UnifiedDatabase na listę słowników w formacie VDJ _songs.
    """
    return [_track_to_vdj_dict(t) for t in db.tracks]
