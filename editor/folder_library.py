"""Skan folderów z muzyką — tryb RB Beta (bez bazy DJ)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from constants import AUDIO_EXTENSIONS
from vdjfolder import normalize_path


def file_md5(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """MD5 całego pliku (do grupowania duplikatów bajt-w-bajt)."""
    p = Path(path)
    h = hashlib.md5()
    with p.open('rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _meta_to_song(path: str, meta: dict) -> dict:
    bpm = meta.get('bpm') or 0
    return {
        'FilePath': path,
        'Tags.Author': meta.get('artist') or '',
        'Tags.Artist': meta.get('artist') or '',
        'Tags.Title': meta.get('title') or Path(path).stem,
        'Tags.Album': meta.get('album') or '',
        'Tags.Genre': meta.get('genre') or '',
        'Tags.User1': '',
        'Tags.User2': '',
        'Tags.Bpm': str(60 / bpm) if bpm and bpm > 0 else '',
        'Tags.Key': meta.get('key') or '',
        'Tags.Stars': meta.get('rating') or '',
        'Infos.PlayCount': '',
        'Infos.SongLength': meta.get('length') or 0,
        'Infos.Bitrate': '',
        'Infos.FileSize': meta.get('fileSize') or 0,
        'Infos.FileHash': meta.get('fileHash') or '',
    }


def scan_folders(folder_paths: list[str], *, compute_hash: bool = False) -> tuple[list[dict], list[str], list[str]]:
    """
    Rekurencyjnie skanuje foldery audio.
    Zwraca (songs, resolved_roots, errors).
    """
    from file_analyzer import read_file_metadata_extended

    songs: list[dict] = []
    roots: list[str] = []
    errors: list[str] = []
    seen_paths: set[str] = set()

    for folder in folder_paths:
        raw = (folder or '').strip()
        if not raw:
            continue
        try:
            root = Path(raw).expanduser().resolve()
        except (OSError, ValueError) as e:
            errors.append(f'Nieprawidłowa ścieżka {raw}: {e}')
            continue
        if not root.exists():
            errors.append(f'Folder nie istnieje: {root}')
            continue
        if not root.is_dir():
            errors.append(f'Nie jest folderem: {root}')
            continue
        roots.append(str(root))
        try:
            for f in root.rglob('*'):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in AUDIO_EXTENSIONS:
                    continue
                np = normalize_path(str(f.resolve()))
                if not np or np in seen_paths:
                    continue
                seen_paths.add(np)
                try:
                    meta = read_file_metadata_extended(np)
                    try:
                        meta['fileSize'] = f.stat().st_size
                    except OSError:
                        meta['fileSize'] = 0
                    if compute_hash:
                        try:
                            meta['fileHash'] = file_md5(f)
                        except OSError as e:
                            errors.append(f'Hash {np}: {e}')
                            meta['fileHash'] = ''
                    songs.append(_meta_to_song(np, meta))
                except Exception as e:
                    errors.append(f'Metadane {np}: {e}')
        except PermissionError as e:
            errors.append(f'Brak dostępu do {root}: {e}')
        except OSError as e:
            errors.append(f'Błąd skanowania {root}: {e}')

    return songs, roots, errors
