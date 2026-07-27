"""
Konwersja ścieżek streamingowych VDJ → Rekordbox.
VDJ: td123456, netsearch://td123456 (Tidal) | va..., sc... (inne)
RB:  file://localhosttidal:tracks:123456

Obsługuje też błędny format MIXO: file://localhosttd31895290 (brak 'tidal:').
"""
import re
from pathlib import Path
from typing import Optional, Tuple


def _is_streaming_prefix(path: str, prefixes: tuple) -> bool:
    p = (path or "").strip().lower()
    return any(p.startswith(x) for x in prefixes)


def format_path_display(path: str, status: Optional[str] = None) -> str:
    """
    Zwraca czytelną etykietę zamiast surowej ścieżki.
    np. td123456 → TIDAL, sc123 → SoundCloud, va123 → inna usługa.
    status: 'offline' | 'online' | None – dodaje (offline)/(online) dla streamingu.
    """
    if not path or not isinstance(path, str):
        return ""
    p = path.strip()
    # Tidal: td123, netsearch://td123, tidal:tracks:123, file://localhosttidal:tracks:123
    if is_tidal_path(p):
        label = "TIDAL"
    elif _is_streaming_prefix(p, ("soundcloud:", "file://localhostsoundcloud:")) or (p.lower().startswith("sc") and len(p) > 2 and p[2:].replace("-", "").isdigit()):
        label = "SoundCloud"
    elif _is_streaming_prefix(p, ("beatport:", "file://localhostbeatport:")) or (p.lower().startswith("bp") and len(p) > 2 and p[2:].replace("-", "").isdigit()):
        label = "Beatport"
    elif _is_streaming_prefix(p, ("deezer:", "file://localhostdeezer:")):
        label = "Deezer"
    elif p.startswith("netsearch:"):
        label = "Streaming"
    elif p.lower().endswith(".vdjcache"):
        label = "Cache (offline)"
    else:
        return p  # ścieżka lokalna – zwróć jak jest
    if status == "offline":
        return f"{label} (offline)"
    if status == "online":
        return f"{label} (online)"
    return label


def get_path_status(path: str, vdj_cache_path: Optional[str] = None) -> Optional[str]:
    """
    Dla streamingu: 'offline' jeśli w cache, 'online' jeśli nie.
    Dla plików lokalnych: None (brak oznaczenia).
    vdj_cache_path: ścieżka do folderu VirtualDJ Cache (np. C:\\VirtualDJ\\Cache).
    """
    if not path or not isinstance(path, str):
        return None
    p = path.strip()
    # Plik .vdjcache – lokalny cache
    if p.lower().endswith(".vdjcache"):
        try:
            return "offline" if Path(p).exists() else None
        except OSError:
            return None
    # Tidal: td123456 – sprawdź bezpośrednią ścieżkę (unika wolnego rglob)
    tid = extract_tidal_id(p)
    if tid and vdj_cache_path:
        cache_dir = Path(vdj_cache_path)
        if cache_dir.is_dir():
            for name in (f"td{tid}.vdjcache", f"{tid}.vdjcache"):
                if (cache_dir / name).is_file():
                    return "offline"
        return "online"
    return None


def is_vdj_cache_path(path: str) -> bool:
    return bool(path and str(path).strip().lower().endswith(".vdjcache"))


def is_tidal_path(path: str) -> bool:
    """Czy ścieżka to utwór Tidal (VDJ / Serato / RB)."""
    return extract_tidal_id(path) is not None


def extract_tidal_id(path: str) -> Optional[str]:
    """
    Wyciąga Tidal track ID ze ścieżki VDJ / Serato / RB.
    Obsługuje: td123, netsearch://td123, streaming://tidal/123, tidal:tracks:123,
    file://localhosttidal:tracks:123, .vdjcache.
    """
    if not path:
        return None
    p = path.strip()
    pl = p.lower()
    if pl.startswith("netsearch://td"):
        num = p[len("netsearch://td"):].strip()
        return num if num.isdigit() else None
    if pl.startswith("streaming://tidal/"):
        num = p[len("streaming://tidal/"):].strip().split("/", 1)[0]
        return num if num.isdigit() else None
    if pl.startswith("tidal:tracks:"):
        num = p[len("tidal:tracks:"):].strip()
        return num if num.isdigit() else None
    if "tidal:tracks:" in pl:
        # file://localhosttidal:tracks:123
        idx = pl.index("tidal:tracks:")
        num = p[idx + len("tidal:tracks:"):].strip()
        return num if num.isdigit() else None
    if pl.startswith("td") and len(p) > 2 and p[2:].isdigit():
        return p[2:]
    if p.lower().endswith(".vdjcache"):
        stem = Path(p).stem
        if stem.startswith("td") and len(stem) > 2 and stem[2:].isdigit():
            return stem[2:]
        if stem.isdigit():
            return stem
    return None


def vdj_to_rb_location(path: str) -> Optional[str]:
    """
    Konwertuje ścieżkę VDJ na format Location Rekordbox.
    Zwraca None dla ścieżek lokalnych (nie streaming).
    RB format Tidal: file://localhosttidal:tracks:TRACK_ID
    """
    tid = extract_tidal_id(path)
    if tid:
        return f"file://localhosttidal:tracks:{tid}"
    # TODO: SoundCloud (sc), Beatport (bp?) – gdy znamy format
    return None


def vdj_to_serato_tidal_path(path: str) -> Optional[str]:
    """
    VDJ td123 / netsearch://td123 → ścieżka streamingu Serato Library.
    Nowoczesne Serato (Library SQLite): streaming://tidal/TRACK_ID
    (stary tidal:tracks:ID jest odrzucany przy imporcie .crate / database V2).
    """
    tid = extract_tidal_id(path)
    if tid:
        return f"streaming://tidal/{tid}"
    return None


def is_serato_tidal_path(path: str) -> bool:
    """Serato streaming URI (aktualny lub legacy)."""
    p = (path or "").strip().lower()
    return p.startswith("streaming://tidal/") or p.startswith("tidal:tracks:")


def expand_valid_paths_with_tidal_aliases(
    valid_paths: set[str],
    songs: list[dict],
) -> set[str]:
    """Dopina aliasy td123 / netsearch://td123 do valid_paths z bazy VDJ."""
    out = set(valid_paths or [])
    for s in songs or []:
        fp = (s.get("FilePath") or "").strip()
        if not fp or not is_tidal_path(fp):
            continue
        np = fp.replace("\\", "/")
        # normalize_path jest w vdjfolder — unikamy importu cyklicznego tutaj
        from vdjfolder import normalize_path

        out.add(normalize_path(fp))
        tid = extract_tidal_id(fp)
        if tid:
            for alias in (
                f"td{tid}",
                f"netsearch://td{tid}",
                f"streaming://tidal/{tid}",
                f"tidal:tracks:{tid}",
            ):
                out.add(normalize_path(alias))
    return out
