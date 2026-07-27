"""Współdzielony stan sesji NJR Konwerter (baza VDJ w pamięci)."""
from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from typing import Optional

from flask import jsonify
from unified_model import UnifiedDatabase

try:
    from license_njr import check_export_license, save_license_key, get_machine_id
except ImportError:
    def check_export_license():
        return {'allowed': True}

    def save_license_key(_):
        return False

    def get_machine_id():
        return 'unknown'

db_path: Optional[Path] = None
songs: list[dict] = []
version: str = ''
vdjfolders: dict[str, str] = {}
extra_files: dict[str, bytes] = {}
source: str = 'vdj'
unified: Optional[UnifiedDatabase] = None
folder_roots: set[Path] = set()

undo_stack: list[dict] = []
UNDO_MAX = 10

trash_items: list[dict] = []

_NJR_KEY = b'NJR-SAVE-KEY'


def ensure_loaded() -> None:
    if songs:
        return
    if source == 'folder_beta':
        raise ValueError(
            'Nie załadowano folderów. W zakładce RB Beta wybierz foldery z muzyką i kliknij „Skanuj”.'
        )
    raise ValueError(
        'Baza nie została załadowana. Najpierw załaduj backup VDJ: '
        '„VDJ: plik ZIP (backup)” lub „VDJ: folder” + Załaduj. '
        'Uwaga: po restarcie serwera baza jest czyszczona – załaduj ponownie.'
    )


def is_folder_beta() -> bool:
    return source == 'folder_beta'


def get_allowed_path_roots() -> set[Path]:
    from file_analyzer import is_streaming

    if folder_roots:
        return set(folder_roots)

    roots: set[Path] = set()
    for s in songs:
        p = (s.get('FilePath') or s.get('path') or '').strip()
        if not p or is_streaming(p):
            continue
        try:
            resolved = Path(p).expanduser().resolve()
            if resolved.is_file():
                roots.add(resolved.parent)
            elif resolved.parent and resolved.parent != resolved:
                roots.add(resolved.parent)
        except Exception:
            pass
    return roots


def is_path_safe(path: Path, *, must_be_file: bool = False) -> bool:
    if not path:
        return False
    try:
        resolved = path.expanduser().resolve()
        if must_be_file and not resolved.is_file():
            return False
        roots = get_allowed_path_roots()
        if not roots:
            return False
        for root in roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False
    except Exception:
        return False


def is_folder_scan_allowed(folder: Path) -> bool:
    try:
        resolved = folder.expanduser().resolve()
        if not resolved.is_dir():
            return False
        roots = get_allowed_path_roots()
        if not roots:
            return False
        for root in roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                pass
            try:
                root.relative_to(resolved)
                return True
            except ValueError:
                pass
        return False
    except Exception:
        return False


def is_media_path_safe(path: Path, *, vdj_cache_path: Optional[str] = None, must_be_file: bool = True) -> bool:
    if is_path_safe(path, must_be_file=must_be_file):
        return True
    if not vdj_cache_path:
        return False
    try:
        cache_dir = Path(vdj_cache_path).expanduser().resolve()
        if not cache_dir.is_dir():
            return False
        resolved = path.expanduser().resolve()
        if must_be_file and not resolved.is_file():
            return False
        resolved.relative_to(cache_dir)
        return True
    except Exception:
        return False


def clear_undo_stack() -> None:
    undo_stack.clear()


def push_undo_state() -> None:
    if len(undo_stack) >= UNDO_MAX:
        undo_stack.pop(0)
    undo_stack.append({
        'songs': copy.deepcopy(songs),
        'vdjfolders': copy.deepcopy(vdjfolders),
        'extra_files': {k: v for k, v in extra_files.items()},
        'version': version,
        'source': source,
        'db_path': str(db_path) if db_path else None,
    })


def require_export_license():
    """Open source: brak blokady eksportu."""
    return None


def encode_njr(data: dict) -> bytes:
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    compressed = gzip.compress(raw)
    return bytes(b ^ _NJR_KEY[i % len(_NJR_KEY)] for i, b in enumerate(compressed))


def decode_njr(encoded: bytes) -> dict:
    decoded = bytes(b ^ _NJR_KEY[i % len(_NJR_KEY)] for i, b in enumerate(encoded))
    return json.loads(gzip.decompress(decoded).decode('utf-8'))


def reset_session() -> None:
    global db_path, songs, version, vdjfolders, extra_files, source, unified, folder_roots, trash_items
    db_path = None
    songs = []
    version = ''
    vdjfolders = {}
    extra_files = {}
    source = 'vdj'
    unified = None
    folder_roots = set()
    clear_undo_stack()
    trash_items = []


def load_folder_beta(folders: list[str], *, compute_hash: bool = False) -> dict:
    """Skan folderów → sesja RB Beta."""
    global songs, version, vdjfolders, extra_files, source, unified, db_path, folder_roots, trash_items

    from folder_library import scan_folders

    clear_undo_stack()
    trash_items = []
    scanned, roots, errors = scan_folders(folders, compute_hash=compute_hash)
    songs = scanned
    version = ''
    vdjfolders = {}
    extra_files = {}
    unified = None
    db_path = None
    source = 'folder_beta'
    folder_roots = {Path(r) for r in roots}
    return {
        'count': len(songs),
        'folders': roots,
        'errors': errors,
        'source': source,
    }
