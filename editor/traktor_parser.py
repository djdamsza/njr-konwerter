"""
Parser bazy Traktor Pro – collection.nml (XML).
Import do formatu _songs (VDJ-style).
Eksport: na razie brak – zapis NML wymaga zachowania struktury.
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from unified_model import UnifiedDatabase, Track, Playlist


def _location_to_path(loc: str) -> str:
    """Konwertuje Location (file://localhost/...) na ścieżkę lokalną."""
    if not loc or not isinstance(loc, str):
        return ""
    loc = loc.strip()
    for prefix in ("file://localhost/", "file://localhost", "file:///", "file://"):
        if loc.lower().startswith(prefix.lower()):
            loc = loc[len(prefix):]
            if loc and not loc.startswith("/") and not (len(loc) > 1 and loc[1] == ":"):
                loc = "/" + loc
            break
    return unquote(loc)


def _attr(el: Optional[ET.Element], name: str, default: str = "") -> str:
    if el is None:
        return default
    return (el.get(name) or "").strip() or default


def _build_location_path(loc_el: ET.Element) -> str:
    """Buduje ścieżkę z LOCATION (VOLUME + DIR + FILE)."""
    vol = loc_el.find("VOLUME")
    dir_el = loc_el.find("DIR")
    file_el = loc_el.find("FILE")
    vol_name = _attr(vol, "NAME") if vol is not None else ""
    dir_path = _attr(dir_el, "PATH") if dir_el is not None else ""
    file_name = _attr(file_el, "NAME") if file_el is not None else ""
    if vol_name and dir_path and file_name:
        return f"{vol_name}:{dir_path}/{file_name}".replace("\\", "/")
    if dir_path and file_name:
        return f"{dir_path}/{file_name}".replace("\\", "/")
    return file_name or dir_path or ""


def load_traktor_nml(nml_path: Path) -> UnifiedDatabase:
    """Ładuje collection.nml Traktor Pro."""
    tree = ET.parse(nml_path)
    root = tree.getroot()
    ns = {}
    if "}" in str(root.tag):
        ns = {"nml": root.tag.split("}")[0].strip("{")}
    def find(el, tag):
        for p in (tag, f"nml:{tag}" if ns else tag):
            r = el.find(p, ns) if ns else el.find(p)
            if r is not None:
                return r
        return None
    tracks = []
    track_id_to_path = {}
    for entry in root.iter("ENTRY"):
        loc_el = find(entry, "LOCATION")
        if loc_el is None:
            loc_el = entry.find("LOCATION")
        path = _build_location_path(loc_el) if loc_el is not None else ""
        if not path:
            continue
        info = find(entry, "INFO") or entry.find("INFO")
        title = _attr(info, "TITLE") if info is not None else ""
        artist = _attr(info, "ARTIST") if info is not None else ""
        album = _attr(info, "ALBUM") if info is not None else ""
        genre = _attr(info, "GENRE") if info is not None else ""
        key = _attr(info, "KEY") or _attr(info, "MUSICAL_KEY") if info else ""
        bpm = 0.0
        try:
            bpm = float(_attr(info, "BPM") or _attr(info, "TEMPO") or 0) if info else 0
        except ValueError:
            pass
        rating = 0
        try:
            rv = int(_attr(info, "RATING") or 0) if info else 0
            rating = min(5, max(0, rv // 51)) if rv else 0
        except ValueError:
            pass
        playcount = 0
        try:
            playcount = int(_attr(info, "PLAYCOUNT") or 0) if info else 0
        except ValueError:
            pass
        duration = 0.0
        try:
            duration = float(_attr(info, "PLAYTIME") or _attr(info, "LENGTH") or 0) if info else 0
        except ValueError:
            pass
        year = 0
        try:
            year = int(_attr(info, "RELEASE_DATE") or _attr(info, "YEAR") or 0) if info else 0
        except ValueError:
            pass
        if not title and path:
            title = Path(path).stem
        tags = [t.strip() for t in (genre or "").split(",") if t.strip()]
        tracks.append(Track(
            path=path,
            title=title or "",
            artist=artist or "",
            album=album or "",
            genre=genre or "",
            tags=tags,
            bpm=bpm,
            key=key or "",
            year=year,
            duration=duration,
            play_count=playcount,
            rating=rating,
        ))
        track_id_to_path[path] = path
    playlists = []
    for node in root.iter("NODE"):
        if node.get("TYPE") == "PLAYLIST" and node.get("NAME"):
            name = node.get("NAME", "")
            pl_tracks = []
            for sub in node.iter("PRIMARYKEY"):
                tid = sub.get("KEY", "")
                if tid and tid in track_id_to_path:
                    pl_tracks.append(track_id_to_path[tid])
            for sub in node.iter("ENTRY"):
                loc_el = find(sub, "LOCATION") or sub.find("LOCATION")
                if loc_el is not None:
                    path = _build_location_path(loc_el)
                    if path and path in track_id_to_path:
                        pl_tracks.append(path)
            if pl_tracks:
                playlists.append(Playlist(name=name, track_ids=pl_tracks))
    return UnifiedDatabase(tracks=tracks, playlists=playlists, source="traktor")
