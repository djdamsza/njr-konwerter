"""
Engine DJ — standardowe ścieżki Music/Artist/Album w bibliotece.

Engine Desktop i Sync Manager oczekują utworów w ``Engine Library/Music/…``
(path w m.db: ``Music/Artist/Album/plik.mp3``). Import z Serato/VDJ często
zapisuje ``../../Desktop/…`` — Sync Manager wtedy gorzej mapuje utwory na
Patriot i zostawia PlaylistEntity z ID Maca.

Tworzymy symlinki w ``Music/`` (bez kopiowania plików) i zapisujemy
standardową ścieżkę względną — waveformy Engine DJ działają normalnie.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def is_junk_engine_path(path: str) -> bool:
    """Ścieżki VDJ/cloud, których Engine nie powinien analizować ani eksportować."""
    p = (path or "").strip().replace("\\", "/")
    if not p:
        return True
    low = p.lower()
    if "clouddrive:" in low or "googledrive" in low:
        return True
    if "/g:/" in low or p.startswith("G:/") or p.startswith("g:/"):
        return True
    if "mój dysk/" in low or "moj dysk/" in low:
        return True
    if p.startswith("netsearch:") or p.startswith("streaming:"):
        return True
    return False


def _sanitize_component(name: str, fallback: str) -> str:
    s = (name or "").strip() or fallback
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = s.strip(" .") or fallback
    return s[:120]


def resolve_local_file(path: str) -> Path | None:
    """Absolutna ścieżka do istniejącego pliku audio lub None."""
    raw = (path or "").strip().replace("\\", "/")
    if not raw or is_junk_engine_path(raw):
        return None
    candidates: list[Path] = []
    if raw.startswith("/"):
        candidates.append(Path(raw))
    else:
        candidates.append(Path("/") / raw.lstrip("/"))
        candidates.append(Path(raw))
    for cand in candidates:
        try:
            resolved = cand.expanduser().resolve()
            if resolved.is_file():
                return resolved
        except OSError:
            continue
    return None


def _unique_music_rel(
    base: Path,
    artist: str,
    album: str,
    filename: str,
    occupied: set[str],
) -> str:
    artist_d = _sanitize_component(artist, "Unknown Artist")
    album_d = _sanitize_component(album, "Unknown Album")
    name = _sanitize_component(filename, "track.mp3")
    if not Path(name).suffix:
        name = f"{name}.mp3"
    stem = Path(name).stem
    suffix = Path(name).suffix

    for n in range(1000):
        fn = name if n == 0 else f"{stem} ({n}){suffix}"
        rel = (Path("Music") / artist_d / album_d / fn).as_posix()
        if rel not in occupied:
            occupied.add(rel)
            return rel
    raise RuntimeError(f"Nie udało się wygenerować unikalnej ścieżki Music/ dla {filename}")


def prefer_patriot_music_path(
    filename: str,
    *,
    title: str = "",
    file_bytes: int = 0,
    pat_index: dict[str, list[dict]] | None,
    occupied: set[str],
) -> str | None:
    """
    Gdy Patriot podłączony — użyj istniejącej ścieżki Music/ z dysku Rane
    (zapobiega rozjazdom Mac vs Patriot i duplikatom przy Export to Drive).
    """
    if not pat_index:
        return None
    from engine_stems import _pick_best_patriot_candidate

    key = Path(filename or "").name.lower()
    if not key:
        return None
    candidates = pat_index.get(key)
    if not candidates:
        return None
    best = _pick_best_patriot_candidate(
        candidates,
        title=title,
        source_file_bytes=file_bytes,
    )
    rel = (best.get("path") or "").replace("\\", "/")
    if not rel or rel in occupied:
        return None
    occupied.add(rel)
    return rel


def music_rel_for_export(
    engine_dir: Path,
    *,
    artist: str,
    album: str,
    abs_file: Path,
    title: str = "",
    file_bytes: int = 0,
    occupied: set[str],
    pat_index: dict[str, list[dict]] | None = None,
) -> str:
    """Ścieżka Music/ — najpierw zgodna z Patriot (jeśli podłączony), potem nowa."""
    aligned = prefer_patriot_music_path(
        abs_file.name,
        title=title,
        file_bytes=file_bytes,
        pat_index=pat_index,
        occupied=occupied,
    )
    if aligned:
        return aligned
    return _unique_music_rel(
        engine_dir,
        artist,
        album,
        abs_file.name,
        occupied,
    )


def ensure_music_symlink(
    engine_dir: Path,
    rel_path: str,
    source_file: Path,
) -> bool:
    """Tworzy symlink Engine Library/Music/… → plik źródłowy. Zwraca True gdy OK."""
    engine_dir = engine_dir.expanduser().resolve()
    rel = rel_path.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        return False
    dest = engine_dir / rel
    source_file = source_file.resolve()
    try:
        dest.parent.relative_to(engine_dir)
    except ValueError:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        try:
            if dest.resolve().samefile(source_file):
                return True
        except OSError:
            pass
        try:
            dest.unlink()
        except OSError:
            return False
    elif dest.exists() and dest.is_file():
        try:
            if dest.resolve().samefile(source_file):
                return True
        except OSError:
            pass
        return False
    try:
        dest.symlink_to(source_file)
        return True
    except OSError:
        try:
            os.link(source_file, dest)
            return True
        except OSError:
            return False


def absolute_path_for_engine_relative(engine_dir: Path, rel_path: str) -> Path | None:
    """Rozwiązuje ścieżkę względną Engine (Music/… lub ../../…) do pliku."""
    engine_dir = engine_dir.expanduser().resolve()
    rel = (rel_path or "").replace("\\", "/")
    if not rel:
        return None
    try:
        full = (engine_dir / rel).resolve()
        if full.is_file():
            return full
    except OSError:
        pass
    return None
