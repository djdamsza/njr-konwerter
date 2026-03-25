"""
Parser DJXML – otwarty format do migracji między programami DJ.
https://www.djxml.com / https://github.com/mixo-marcus/DJXML

Import DJXML v2.0.0 do UnifiedDatabase.
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Union
from urllib.parse import unquote

from unified_model import (
    UnifiedDatabase,
    Track,
    Playlist,
    BeatgridPoint,
    CuePoint,
)


def _location_to_path(loc: str) -> str:
    """Konwertuje Location (file://localhost/...) na ścieżkę lokalną."""
    if not loc or not isinstance(loc, str):
        return ""
    loc = loc.strip()
    for prefix in ("file://localhost/", "file://localhost", "file:///", "file://"):
        if loc.lower().startswith(prefix.lower()):
            loc = loc[len(prefix) :]
            if loc and not loc.startswith("/") and not (len(loc) > 1 and loc[1] == ":"):
                loc = "/" + loc
            break
    return unquote(loc)


def _text(el: ET.Element, tag: str, default: str = "") -> str:
    """Pobiera tekst dziecka."""
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else default


def _float(el: ET.Element, tag: str, default: float = 0.0) -> float:
    try:
        return float(_text(el, tag) or default)
    except ValueError:
        return default


def _int(el: ET.Element, tag: str, default: int = 0) -> int:
    try:
        return int(_text(el, tag) or default)
    except ValueError:
        return default


def _parse_track(tr: ET.Element) -> Track:
    """Parsuje element Track do modelu Track."""
    loc = _text(tr, "Location")
    path = _location_to_path(loc)
    if not path:
        path = _text(tr, "Location")

    title = _text(tr, "Title") or Path(path).stem if path else ""
    artist = _text(tr, "Artist")
    album = _text(tr, "Album")
    genre = _text(tr, "Genre")
    tags_str = _text(tr, "KeywordTags")
    tags = [t.strip() for t in tags_str.split() if t.strip()] if tags_str else []
    comment = _text(tr, "Comments")
    bpm = _float(tr, "Bpm")
    key = _text(tr, "Key") or _text(tr, "MusicalKey")
    year = _int(tr, "Year")
    duration = _float(tr, "TotalTime")
    play_count = _int(tr, "PlayCount")
    rating = _int(tr, "Rating")
    track_id = _text(tr, "Id")

    beatgrid = []
    for bg in tr.findall("Beatgrid"):
        st = _float(bg, "StartTime")
        bpm_val = _float(bg, "Bpm")
        if bpm_val > 0:
            beatgrid.append(BeatgridPoint(pos=st, bpm=bpm_val))
    if not beatgrid and bpm > 0:
        beatgrid.append(BeatgridPoint(pos=0.0, bpm=bpm))

    cue_points = []
    for cp in tr.findall("CuePoint"):
        name = _text(cp, "Name", "Cue")
        start = _float(cp, "Start")
        num = _int(cp, "Num")
        r = _int(cp, "Red")
        g = _int(cp, "Green")
        b = _int(cp, "Blue")
        color = (r << 16) | (g << 8) | b if (r or g or b) else None
        cue_points.append(CuePoint(name=name, pos=start, num=num, color=color))

    return Track(
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
        play_count=play_count,
        rating=rating,
        beatgrid=beatgrid,
        cue_points=cue_points,
        source_id=track_id,
    )


def _parse_playlists(root: ET.Element, id_to_path: dict[str, str]) -> list[Playlist]:
    """Parsuje Playlists (Folder/Playlist) do listy Playlist."""
    result = []
    playlists_el = root.find("Playlists")
    if playlists_el is None:
        return result

    def _collect_playlists(parent: ET.Element, folder_id: str) -> None:
        for folder in parent.findall("Folder"):
            fid = _text(folder, "Id")
            name = _text(folder, "Name")
            if fid == "0" and name == "ROOT":
                _collect_playlists(folder, fid)
            else:
                _collect_playlists(folder, fid)
            for pl in folder.findall("Playlist"):
                track_ids = []
                for pt in pl.findall("PlaylistTrack"):
                    tid = _text(pt, "TrackId")
                    path = id_to_path.get(tid)
                    if path:
                        track_ids.append(path)
                if track_ids:
                    result.append(Playlist(name=_text(pl, "PlaylistName"), track_ids=track_ids))

    _collect_playlists(playlists_el, "0")
    return result


def load_djxml(xml_content: Union[str, bytes]) -> UnifiedDatabase:
    """
    Ładuje DJXML do UnifiedDatabase.
    xml_content: string lub bytes (UTF-8).
    """
    if isinstance(xml_content, bytes):
        xml_content = xml_content.decode("utf-8", errors="replace")
    root = ET.fromstring(xml_content)

    tracks = []
    id_to_path = {}
    tracks_el = root.find("Tracks")
    if tracks_el is not None:
        for tr in tracks_el.findall("Track"):
            t = _parse_track(tr)
            tid = _text(tr, "Id")
            if tid:
                id_to_path[tid] = t.path
            tracks.append(t)
    else:
        for tr in root.findall("Track"):
            t = _parse_track(tr)
            tid = _text(tr, "Id")
            if tid:
                id_to_path[tid] = t.path
            tracks.append(t)

    playlists = _parse_playlists(root, id_to_path)
    return UnifiedDatabase(
        tracks=tracks,
        playlists=playlists,
        smart_playlists=[],
        source="djxml",
    )
