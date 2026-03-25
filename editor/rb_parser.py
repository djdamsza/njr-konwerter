"""
Parser eksportu XML Rekordbox (File → Export Collection).
Odczyt rbxml.xml → UnifiedDatabase.
Obsługuje eksporty MIXO (w tym błędny format Tidal file://localhosttd123).
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Union
from urllib.parse import unquote
from unified_model import (
    UnifiedDatabase,
    Track,
    Playlist,
    BeatgridPoint,
    CuePoint,
)


def _normalize_tidal_path(path: str) -> str:
    """
    Normalizuje błędny format MIXO td123 → tidal:tracks:123.
    MIXO czasem eksportuje Tidal jako file://localhosttd31895290 zamiast
    file://localhosttidal:tracks:31895290.
    """
    if not path or len(path) < 3:
        return path
    # td + same cyfry → tidal:tracks:XXX
    if path.startswith("td") and path[2:].isdigit():
        return f"tidal:tracks:{path[2:]}"
    return path


def _parse_location(loc: str) -> str:
    """Konwertuje Location (file://localhost/...) na ścieżkę."""
    if not loc:
        return ""
    # file://localhost/Users/test/Music/... – lokalne pliki
    if loc.startswith("file://localhost/"):
        path = unquote(loc.replace("file://localhost/", ""))
        # macOS/Unix: /Users/... – dodaj / jeśli brak
        if path and not path.startswith("/") and not (len(path) > 1 and path[1] == ":"):
            path = "/" + path
        return path
    # file://localhosttidal:tracks:123 – streaming (bez slash)
    # file://localhosttd31895290 – błędny format MIXO
    if loc.startswith("file://localhost"):
        path = loc[len("file://localhost"):]
        return _normalize_tidal_path(path)
    return _normalize_tidal_path(loc)


def _parse_track(elem: ET.Element) -> Track:
    """Parsuje element <TRACK> z RB XML."""
    track_id = elem.get("TrackID", "")
    name = elem.get("Name", "")
    artist = elem.get("Artist", "")
    album = elem.get("Album", "")
    genre = elem.get("Genre", "")
    comments = elem.get("Comments", "")
    location = _parse_location(elem.get("Location", ""))

    # Tagi: RB ma Genre + Comments (tam są #tag w stylu VDJ)
    tags = []
    if genre:
        for t in genre.split():
            if t.strip():
                tags.append(t.strip())
    if comments:
        for t in comments.split():
            if t.strip() and t.strip().startswith("#"):
                tags.append(t.strip())

    # BPM
    bpm_str = elem.get("AverageBpm", "0")
    try:
        bpm = float(bpm_str) if bpm_str else 0.0
    except ValueError:
        bpm = 0.0

    # Czas
    total_time = elem.get("TotalTime", "0")
    try:
        duration = float(total_time) if total_time else 0.0
    except ValueError:
        duration = 0.0

    # Rating (RB: 0, 51, 102, 153, 204, 255 = 0-5 gwiazdek)
    rating = int(elem.get("Rating", "0") or "0")
    play_count = int(elem.get("PlayCount", "0") or "0")
    year = int(elem.get("Year", "0") or "0")

    # Beatgrid
    beatgrid = []
    for tempo in elem.findall("TEMPO"):
        inizio = float(tempo.get("Inizio", "0") or "0")
        bpm_val = float(tempo.get("Bpm", "0") or "0")
        beatgrid.append(BeatgridPoint(pos=inizio, bpm=bpm_val))

    # Cue points
    cue_points = []
    for pm in elem.findall("POSITION_MARK"):
        name_cue = pm.get("Name", "Cue")
        start = float(pm.get("Start", "0") or "0")
        num = int(pm.get("Num", "0") or "0")
        r = int(pm.get("Red", "0") or "0")
        g = int(pm.get("Green", "0") or "0")
        b = int(pm.get("Blue", "0") or "0")
        color = (0xFF << 24) | (r << 16) | (g << 8) | b
        cue_points.append(CuePoint(name=name_cue, pos=start, num=num, color=color))

    return Track(
        path=location,
        title=name,
        artist=artist,
        album=album,
        genre=genre,
        tags=tags,
        bpm=bpm,
        key=elem.get("Tonality", ""),
        year=year,
        duration=duration,
        play_count=play_count,
        rating=rating,
        beatgrid=beatgrid,
        cue_points=cue_points,
        source_id=track_id,
    )


def _parse_playlists(
    root: ET.Element,
    track_by_id: dict[str, Track],
    track_by_location: Optional[dict[str, Track]] = None,
) -> list[Playlist]:
    """
    Parsuje drzewo PLAYLISTS → NODE.
    KeyType=0: Key to TrackID.
    KeyType=1: Key to Location (file://localhost/... lub file://localhosttidal:tracks:...).
    """
    playlists = []
    plists = root.find("PLAYLISTS")
    if plists is None:
        return playlists

    def resolve_track(key: str, key_type: str) -> Optional[Track]:
        if key_type == "0":
            return track_by_id.get(key)
        if key_type == "1" and track_by_location:
            return track_by_location.get(key)
        return None

    def parse_node(node: ET.Element, parent_name: str = "") -> list[Playlist]:
        result = []
        for child in node:
            if child.tag != "NODE":
                continue
            name = child.get("Name", "")
            ntype = child.get("Type", "1")
            if ntype == "0":
                # Folder
                pl = Playlist(name=name, track_ids=[], is_folder=True)
                pl.children = parse_node(child, name)
                result.append(pl)
            elif ntype == "1":
                # Playlist
                key_type = child.get("KeyType", "0")
                track_ids = []
                for tr in child.findall("TRACK"):
                    key = tr.get("Key", "")
                    t = resolve_track(key, key_type) if key else None
                    if t:
                        track_ids.append(t.path)
                result.append(Playlist(name=name, track_ids=track_ids, is_folder=False))
        return result

    root_node = plists.find("NODE")
    if root_node is not None:
        playlists = parse_node(root_node)
    return playlists


def load_rb_xml(path: Union[str, Path]) -> UnifiedDatabase:
    """
    Ładuje eksport XML Rekordbox (rbxml.xml).
    Zwraca UnifiedDatabase.
    Obsługuje KeyType=0 (TrackID) i KeyType=1 (Location) w playlistach.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Plik nie istnieje: {path}")

    tree = ET.parse(path)
    root = tree.getroot()

    collection = root.find("COLLECTION")
    if collection is None:
        raise ValueError("Brak sekcji COLLECTION w pliku RB XML")

    tracks = []
    track_by_id = {}
    track_by_location = {}
    for tr in collection.findall("TRACK"):
        t = _parse_track(tr)
        tracks.append(t)
        if t.source_id:
            track_by_id[t.source_id] = t
    try:
        from rb_generator import _path_to_location
        for t in tracks:
            if t.path:
                loc = _path_to_location(t.path)
                if loc:
                    track_by_location[loc] = t
    except ImportError:
        pass

    playlists = _parse_playlists(root, track_by_id, track_by_location)

    return UnifiedDatabase(
        tracks=tracks,
        playlists=playlists,
        smart_playlists=[],  # RB XML export nie zawiera SmartList – tylko statyczne
        source="rb",
    )
