"""
Generator XML Rekordbox (File → Import).
Tworzy rbxml.xml z UnifiedDatabase do importu w RB.
"""
import os
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from unified_model import UnifiedDatabase, Track, Playlist
from vdjfolder import normalize_path


def _read_file_meta(path: str) -> tuple[int, float, int, int]:
    """Odczytuje Size, TotalTime (s), BitRate, SampleRate z pliku. RB wymaga tych wartości – bez nich może pokazywać czerwone ikony."""
    size = 0
    duration = 0.0
    bitrate = 0
    sample_rate = 0
    try:
        p = Path(path)
        if not p.exists():
            return 0, 0.0, 0, 0
        size = p.stat().st_size
        ext = p.suffix.lower()
        if ext in (".mp3", ".mp2", ".mp1"):
            from mutagen.mp3 import MP3
            audio = MP3(path)
            duration = audio.info.length
            bitrate = int(audio.info.bitrate / 1000) if audio.info.bitrate else 0
            sample_rate = audio.info.sample_rate or 0
        elif ext == ".wav":
            from mutagen.wave import WAVE
            audio = WAVE(path)
            duration = audio.info.length
            sample_rate = audio.info.sample_rate or 0
            bitrate = int(sample_rate * 16 * 2 / 1000) if sample_rate else 0  # typowy WAV
        elif ext in (".m4a", ".mp4", ".aac"):
            from mutagen.mp4 import MP4
            audio = MP4(path)
            duration = audio.info.length
            if hasattr(audio.info, "bitrate") and audio.info.bitrate:
                bitrate = int(audio.info.bitrate / 1000)
            if hasattr(audio.info, "sample_rate") and audio.info.sample_rate:
                sample_rate = audio.info.sample_rate
        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(path)
            duration = audio.info.length
            if hasattr(audio.info, "bits_per_sample") and audio.info.sample_rate:
                sample_rate = audio.info.sample_rate
                bitrate = int(audio.info.sample_rate * (audio.info.bits_per_sample or 16) * (audio.info.channels or 2) / 1000)
    except Exception:
        pass
    return size, duration, bitrate, sample_rate or 44100


def _path_to_location(path: str, path_replace: Optional[dict] = None) -> str:
    """Konwertuje ścieżkę na format Location RB (file://localhost/...)."""
    if not path:
        return ""
    if path_replace:
        for old_prefix, new_prefix in path_replace.items():
            if path.startswith(old_prefix):
                path = new_prefix + path[len(old_prefix):]
                break
    # VDJ Tidal (td123, netsearch://td123) → RB tidal:tracks:123
    try:
        from vdj_streaming import vdj_to_rb_location
        rb_loc = vdj_to_rb_location(path)
        if rb_loc:
            return rb_loc
    except ImportError:
        pass
    # Już w formacie RB (tidal:tracks:123) lub inny streaming
    if path.startswith("tidal:") or path.startswith("soundcloud:") or (
        ":" in path and len(path) > 1 and path[1] != ":"
    ):
        return f"file://localhost{path}"
    # Lokalny plik – ścieżka absolutna
    if path.startswith("/"):
        return "file://localhost" + quote(path, safe="/")
    # Windows C:\...
    if len(path) > 1 and path[1] == ":":
        return "file://localhost/" + quote(path, safe="/")
    return "file://localhost/" + quote(path, safe="/")


def _track_to_rb_xml(track: Track, track_id: str, path_replace: Optional[dict] = None) -> ET.Element:
    """Tworzy element TRACK w formacie RB XML."""
    loc = _path_to_location(track.path, path_replace)

    # Kind – uproszczone
    kind = "Unknown Format"
    if track.path.lower().endswith(".mp3"):
        kind = "MP3 File"
    elif track.path.lower().endswith(".wav"):
        kind = "WAV File"
    elif track.path.lower().endswith(".flac"):
        kind = "FLAC File"
    elif track.path.lower().endswith(".m4a") or track.path.lower().endswith(".aac"):
        kind = "MP4 File"

    # Size, TotalTime, BitRate, SampleRate – RB wymaga z pliku (win.xml: drag-drop ma te wartości, import z 0 ma czerwone)
    size, duration_sec, bitrate, sample_rate = _read_file_meta(track.path)
    total_time = int(duration_sec) if duration_sec else (int(track.duration) if track.duration else 0)

    # Comments = tagi z # (RB My Tags w eksporcie często w Comments)
    comments = " ".join(t for t in track.tags if t) if track.tags else ""

    attrib = {
        "TrackID": track_id,
        "Name": track.title or Path(track.path).stem,
        "Artist": track.artist,
        "Composer": "",
        "Album": track.album,
        "Grouping": "",
        "Genre": track.genre,
        "Kind": kind,
        "Size": str(size),
        "TotalTime": str(total_time),
        "DiscNumber": "0",
        "TrackNumber": "0",
        "Year": str(track.year),
        "AverageBpm": f"{track.bpm:.2f}" if track.bpm else "0.00",
        "DateAdded": "2020-01-01",
        "BitRate": str(bitrate),
        "SampleRate": str(sample_rate),
        "Comments": comments,
        "PlayCount": str(track.play_count),
        "Rating": str(track.rating),
        "Location": loc,
        "Remixer": "",
        "Tonality": track.key,
        "Label": "",
        "Mix": "",
    }
    tr = ET.Element("TRACK", attrib)

    # TEMPO (beatgrid)
    if track.beatgrid:
        for bg in track.beatgrid:
            ET.SubElement(
                tr,
                "TEMPO",
                {
                    "Inizio": f"{bg.pos:.3f}",
                    "Bpm": f"{bg.bpm:.2f}",
                    "Metro": "4/4",
                    "Battito": "1",
                },
            )
    elif track.bpm > 0:
        ET.SubElement(
            tr,
            "TEMPO",
            {"Inizio": "0.000", "Bpm": f"{track.bpm:.2f}", "Metro": "4/4", "Battito": "1"},
        )

    # POSITION_MARK (cue points)
    for cp in track.cue_points:
        r = ((cp.color or 0) >> 16) & 0xFF
        g = ((cp.color or 0) >> 8) & 0xFF
        b = (cp.color or 0) & 0xFF
        pm = ET.SubElement(
            tr,
            "POSITION_MARK",
            {
                "Name": cp.name,
                "Type": "0",
                "Start": f"{cp.pos:.3f}",
                "Num": str(cp.num),
                "Red": str(r),
                "Green": str(g),
                "Blue": str(b),
            },
        )
        # RB czasem ma End dla loop – pomijamy

    return tr


def _playlist_to_node(pl: Playlist, path_to_id: dict[str, str]) -> ET.Element:
    """Rekurencyjnie buduje NODE dla playlisty/folderu."""
    if pl.is_folder:
        count = len(pl.children)
        node = ET.Element("NODE", {"Type": "0", "Name": pl.name, "Count": str(count)})
        for child in pl.children:
            node.append(_playlist_to_node(child, path_to_id))
        return node
    else:
        entries = 0
        track_elems = []
        for path in pl.track_ids:
            # path jest znormalizowany (z vdjfolders_to_playlists)
            tid = path_to_id.get(path)
            if tid:
                track_elems.append(ET.Element("TRACK", {"Key": tid}))
                entries += 1
        node = ET.Element(
            "NODE",
            {"Name": pl.name, "Type": "1", "KeyType": "0", "Entries": str(entries)},
        )
        for te in track_elems:
            node.append(te)
        return node


def generate_rb_playlists_only_xml(
    playlists: list[Playlist],
    path_to_rb_id: dict[str, str],
    path_replace: Optional[dict] = None,
    tracks_for_collection: Optional[list[Track]] = None,
) -> bytes:
    """
    Generuje XML z playlistami – do importu w RB gdy utwory są już w kolekcji.
    RB wymaga, by TRACK Key w playlistach odnosił się do TrackID w COLLECTION.
    path_to_rb_id: mapowanie ścieżka → TrackID (z eksportu RB po dodaniu folderu).
    path_replace: {path_from: path_to} – zamiana ścieżki (gdy VDJ ma inne ścieżki niż RB).
    tracks_for_collection: utwory z eksportu RB – tylko te referencjonowane w playlistach.
    """
    from vdjfolder import normalize_path

    # path_to_rb_id ma klucze = ścieżki z RB (znormalizowane)
    def vdj_path_to_rb_key(vdj_path: str) -> str:
        np = normalize_path(vdj_path)
        if path_replace:
            for old_prefix, new_prefix in path_replace.items():
                no = normalize_path(old_prefix)
                if np.startswith(no):
                    np = normalize_path(new_prefix.rstrip("/") + np[len(no):])
                    break
        return np

    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="rekordbox", Version="7.0.0", Company="AlphaTheta")

    # COLLECTION – RB wymaga, by Key w playlistach odnosił się do TrackID w COLLECTION
    coll_tracks = list(tracks_for_collection) if tracks_for_collection else []
    coll = ET.SubElement(root, "COLLECTION", Entries=str(len(coll_tracks)))
    for t in coll_tracks:
        if t.source_id:
            coll.append(_track_to_rb_xml(t, t.source_id, path_replace=None))

    plists = ET.SubElement(root, "PLAYLISTS")
    root_node = ET.SubElement(plists, "NODE", Type="0", Name="ROOT", Count=str(len(playlists)))

    # KeyType=1 (Location) – RB lepiej dopasowuje utwory przy przeciąganiu playlist
    id_to_location = {t.source_id: _path_to_location(t.path) for t in coll_tracks if t.source_id}

    def pl_to_node(pl: Playlist) -> ET.Element:
        if pl.is_folder:
            node = ET.Element("NODE", {"Type": "0", "Name": pl.name, "Count": str(len(pl.children))})
            for child in pl.children:
                node.append(pl_to_node(child))
            return node
        else:
            track_elems = []
            for path in pl.track_ids:
                rb_key = vdj_path_to_rb_key(path)
                tid = path_to_rb_id.get(rb_key)
                if tid:
                    loc = id_to_location.get(tid)
                    if loc:
                        track_elems.append(ET.Element("TRACK", {"Key": loc}))
            node = ET.Element("NODE", {"Name": pl.name, "Type": "1", "KeyType": "1", "Entries": str(len(track_elems))})
            for te in track_elems:
                node.append(te)
            return node

    for pl in playlists:
        root_node.append(pl_to_node(pl))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    buf = BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True, default_namespace="", method="xml")
    return buf.getvalue()


def generate_rb_xml(db: UnifiedDatabase, path_replace: Optional[dict] = None) -> bytes:
    """
    Generuje XML Rekordbox (DJ_PLAYLISTS) z UnifiedDatabase.
    Zwraca bytes (UTF-8).
    """
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="rekordbox", Version="7.0.0", Company="AlphaTheta")

    # Mapowanie path -> TrackID (znormalizowane ścieżki – dopasowanie do playlist z vdjfolder)
    path_to_id = {}
    next_id = 100000000
    for t in db.tracks:
        tid = t.source_id or str(next_id)
        if not t.source_id:
            next_id += 1
        path_to_id[normalize_path(t.path)] = tid

    # COLLECTION
    coll = ET.SubElement(root, "COLLECTION", Entries=str(len(db.tracks)))
    for t in db.tracks:
        tid = path_to_id[normalize_path(t.path)]
        coll.append(_track_to_rb_xml(t, tid, path_replace))

    # PLAYLISTS
    plists = ET.SubElement(root, "PLAYLISTS")
    root_node = ET.SubElement(plists, "NODE", Type="0", Name="ROOT", Count=str(len(db.playlists)))
    for pl in db.playlists:
        root_node.append(_playlist_to_node(pl, path_to_id))

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
