"""
Model uniwersalny dla konwertera VDJ ↔ Rekordbox.
Używany jako pośrednia reprezentacja przy imporcie i eksporcie.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BeatgridPoint:
    """Punkt beatgridu (pozycja + tempo)."""
    pos: float  # sekundy
    bpm: float


@dataclass
class CuePoint:
    """Punkt cue (hot cue, memory cue)."""
    name: str
    pos: float  # sekundy
    num: int
    color: Optional[int] = None  # ARGB 32-bit (VDJ) lub None


@dataclass
class Track:
    """Uniwersalna reprezentacja utworu."""
    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = ""
    tags: list[str] = field(default_factory=list)  # User1+User2+Genre łącznie lub osobno
    comment: str = ""  # VDJ <Comment> – do RB Commnt (nie tagi)
    bpm: float = 0.0
    key: str = ""
    year: int = 0
    duration: float = 0.0
    play_count: int = 0
    rating: int = 0
    beatgrid: list[BeatgridPoint] = field(default_factory=list)
    cue_points: list[CuePoint] = field(default_factory=list)
    # Identyfikator źródłowy (TrackID w RB, ścieżka w VDJ)
    source_id: Optional[str] = None


@dataclass
class Playlist:
    """Playlista statyczna – lista utworów."""
    name: str
    track_ids: list[str]  # path lub TrackID
    is_folder: bool = False
    children: list["Playlist"] = field(default_factory=list)


@dataclass
class SmartPlaylist:
    """Playlista inteligentna – reguły filtrowania."""
    name: str
    filter_text: str  # np. "User 1 has tag PARTY or User 1 has tag TANECZNE"
    scope: str = "database"  # VDJ: database | folder


@dataclass
class UnifiedDatabase:
    """Pełna baza – utwory + playlisty."""
    tracks: list[Track] = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)
    smart_playlists: list[SmartPlaylist] = field(default_factory=list)
    source: str = ""  # "vdj" | "rb"
