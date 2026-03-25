"""
Generator DJXML – otwarty format do migracji między programami DJ.
https://www.djxml.com / https://github.com/mixo-marcus/DJXML

Eksport UnifiedDatabase do DJXML v2.0.0 (kompatybilny z Mixo i innymi).
"""
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from unified_model import UnifiedDatabase, Track, Playlist
from vdjfolder import normalize_path


def _path_to_location(path: str, path_replace: Optional[dict] = None) -> str:
    """Konwertuje ścieżkę na format Location (file://localhost/...)."""
    if not path:
        return ""
    if path_replace:
        for old_prefix, new_prefix in path_replace.items():
            if path.startswith(old_prefix):
                path = new_prefix + path[len(old_prefix) :]
                break
    if path.startswith("/"):
        return "file://localhost" + quote(path, safe="/")
    if len(path) > 1 and path[1] == ":":
        return "file://localhost/" + quote(path, safe="/")
    return "file://localhost/" + quote(path, safe="/")


def _esc(s: str) -> str:
    """Escape dla XML (DJXML: &, ", <, >)."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _track_to_djxml(
    track: Track, track_id: str, path_replace: Optional[dict] = None
) -> ET.Element:
    """Tworzy element Track w formacie DJXML."""
    loc = _path_to_location(track.path, path_replace)

    kind = "Unknown"
    ext = Path(track.path).suffix.lower()
    if ext == ".mp3":
        kind = "MP3"
    elif ext in (".wav", ".aiff", ".aif"):
        kind = "WAV"
    elif ext == ".flac":
        kind = "FLAC"
    elif ext in (".m4a", ".aac", ".mp4"):
        kind = "MP4"
    elif ext == ".ogg":
        kind = "OGG"

    tr = ET.Element("Track")
    ET.SubElement(tr, "Id").text = track_id
    ET.SubElement(tr, "Title").text = _esc(track.title or Path(track.path).stem)
    ET.SubElement(tr, "Album").text = _esc(track.album)
    ET.SubElement(tr, "Artist").text = _esc(track.artist)
    ET.SubElement(tr, "Remixer").text = ""
    ET.SubElement(tr, "Producer").text = ""
    ET.SubElement(tr, "Bpm").text = f"{track.bpm:.2f}" if track.bpm else "0.00"
    ET.SubElement(tr, "BitRate").text = "0"
    ET.SubElement(tr, "Colour").text = "0"
    ET.SubElement(tr, "Comments").text = _esc(track.comment or " ".join(track.tags))
    ET.SubElement(tr, "DateAdded").text = "2020-01-01"
    ET.SubElement(tr, "DiscNumber").text = "0"
    ET.SubElement(tr, "Genre").text = _esc(track.genre)
    ET.SubElement(tr, "SubGenre").text = ""
    ET.SubElement(tr, "SubSubGenre").text = ""
    ET.SubElement(tr, "Grouping").text = ""
    ET.SubElement(tr, "Key").text = _esc(track.key)
    ET.SubElement(tr, "Kind").text = kind
    ET.SubElement(tr, "Label").text = ""
    ET.SubElement(tr, "Location").text = loc
    ET.SubElement(tr, "Mix").text = ""
    ET.SubElement(tr, "PlayCount").text = str(track.play_count)
    ET.SubElement(tr, "Rating").text = str(track.rating)
    ET.SubElement(tr, "SampleRate").text = "44100"
    ET.SubElement(tr, "Size").text = "0"
    ET.SubElement(tr, "MusicalKey").text = _esc(track.key)
    ET.SubElement(tr, "TotalTime").text = str(int(track.duration)) if track.duration else "0"
    ET.SubElement(tr, "TrackNumber").text = "0"
    ET.SubElement(tr, "Year").text = str(track.year)
    ET.SubElement(tr, "KeywordTags").text = _esc(" ".join(track.tags))
    ET.SubElement(tr, "PurchasedFrom").text = ""
    ET.SubElement(tr, "PurchaseLink").text = ""

    # Beatgrid
    if track.beatgrid:
        for bg in track.beatgrid:
            bg_el = ET.SubElement(tr, "Beatgrid")
            ET.SubElement(bg_el, "StartTime").text = f"{bg.pos:.3f}"
            ET.SubElement(bg_el, "Bpm").text = f"{bg.bpm:.2f}"
            ET.SubElement(bg_el, "BeatType").text = "4/4"
    elif track.bpm > 0:
        bg_el = ET.SubElement(tr, "Beatgrid")
        ET.SubElement(bg_el, "StartTime").text = "0.000"
        ET.SubElement(bg_el, "Bpm").text = f"{track.bpm:.2f}"
        ET.SubElement(bg_el, "BeatType").text = "4/4"

    # CuePoint (Type 0=Cue, 4=Loop)
    for cp in track.cue_points:
        cp_el = ET.SubElement(tr, "CuePoint")
        ET.SubElement(cp_el, "Name").text = _esc(cp.name)
        ET.SubElement(cp_el, "Type").text = "0"
        ET.SubElement(cp_el, "Start").text = f"{cp.pos:.3f}"
        ET.SubElement(cp_el, "End").text = f"{cp.pos:.3f}"
        ET.SubElement(cp_el, "Num").text = str(cp.num)
        r = ((cp.color or 0) >> 16) & 0xFF
        g = ((cp.color or 0) >> 8) & 0xFF
        b = (cp.color or 0) & 0xFF
        ET.SubElement(cp_el, "Red").text = str(r)
        ET.SubElement(cp_el, "Green").text = str(g)
        ET.SubElement(cp_el, "Blue").text = str(b)

    return tr


def _playlist_to_djxml(pl: Playlist, path_to_id: dict[str, str], folder_id: str = "0") -> ET.Element:
    """Rekurencyjnie buduje Folder/Playlist w formacie DJXML."""
    if pl.is_folder:
        folder = ET.Element("Folder")
        fid = f"f_{pl.name}_{id(pl)}".replace(" ", "_")
        ET.SubElement(folder, "Id").text = fid
        ET.SubElement(folder, "Name").text = _esc(pl.name)
        ET.SubElement(folder, "Entries").text = str(len(pl.children))
        ET.SubElement(folder, "ParentFolderId").text = folder_id
        for child in pl.children:
            folder.append(_playlist_to_djxml(child, path_to_id, fid))
        return folder
    else:
        playlist = ET.Element("Playlist")
        pid = f"p_{pl.name}_{id(pl)}".replace(" ", "_")
        track_ids = [path_to_id.get(normalize_path(p), path_to_id.get(p)) for p in pl.track_ids]
        track_ids = [tid for tid in track_ids if tid]
        ET.SubElement(playlist, "Id").text = pid
        ET.SubElement(playlist, "PlaylistName").text = _esc(pl.name)
        ET.SubElement(playlist, "Entries").text = str(len(track_ids))
        ET.SubElement(playlist, "ParentFolderId").text = folder_id
        for tid in track_ids:
            pt = ET.SubElement(playlist, "PlaylistTrack")
            ET.SubElement(pt, "TrackId").text = tid
        return playlist


def generate_djxml(db: UnifiedDatabase, path_replace: Optional[dict] = None) -> bytes:
    """
    Generuje DJXML v2.0.0 z UnifiedDatabase.
    Zwraca bytes (UTF-8).
    """
    root = ET.Element("DJXML")
    ET.SubElement(root, "Version").text = "2.0.0"
    ET.SubElement(root, "Software").text = "VDJ Database Editor"
    lib_count = ET.SubElement(root, "Library")
    lib_count.text = str(len(db.tracks))

    # Mapowanie path -> TrackId
    path_to_id = {}
    next_id = 1
    for t in db.tracks:
        tid = t.source_id or str(next_id)
        if not t.source_id:
            next_id += 1
        path_to_id[normalize_path(t.path)] = tid
        path_to_id[t.path] = tid

    # Tracks (kontener)
    tracks_container = ET.SubElement(root, "Tracks")
    for t in db.tracks:
        tid = path_to_id.get(normalize_path(t.path)) or path_to_id.get(t.path)
        tracks_container.append(_track_to_djxml(t, tid, path_replace))

    # Playlists
    playlists_root = ET.SubElement(root, "Playlists")
    root_folder = ET.SubElement(playlists_root, "Folder")
    ET.SubElement(root_folder, "Id").text = "0"
    ET.SubElement(root_folder, "Name").text = "ROOT"
    ET.SubElement(root_folder, "Entries").text = str(len(db.playlists))
    ET.SubElement(root_folder, "ParentFolderId").text = ""
    for pl in db.playlists:
        root_folder.append(_playlist_to_djxml(pl, path_to_id, "0"))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    buf = BytesIO()
    tree.write(
        buf,
        encoding="utf-8",
        xml_declaration=True,
        default_namespace="",
        method="xml",
    )
    return buf.getvalue()
