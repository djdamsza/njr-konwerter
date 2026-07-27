"""Kosz sesji NJR — bezpieczne usuwanie z możliwością przywrócenia."""
from __future__ import annotations

import copy
import json
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import app_state as st

KIND_DB_TRACK = 'db_track'
KIND_FILE = 'file'
KIND_PLAYLIST_ENTRY = 'playlist_entry'
KIND_COMBINED = 'combined'

STATUS_ACTIVE = 'active'
STATUS_RESTORED = 'restored'
STATUS_DISMISSED = 'dismissed'


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _song_label(song: dict) -> str:
    author = (song.get('Tags.Author') or song.get('Tags.Artist') or '').strip()
    title = (song.get('Tags.Title') or '').strip()
    if author and title:
        return f'{author} — {title}'
    path = (song.get('FilePath') or '').strip()
    return title or author or Path(path).name if path else 'Utwór'


def _move_to_macos_trash_fallback(resolved: Path) -> None:
    trash_dir = Path.home() / '.Trash'
    trash_dir.mkdir(exist_ok=True)
    dest = trash_dir / resolved.name
    if dest.exists():
        stem, suf = resolved.stem, resolved.suffix
        n = 1
        while dest.exists():
            dest = trash_dir / f'{stem} {n}{suf}'
            n += 1
    resolved.rename(dest)


def move_file_to_system_trash(path: Path) -> None:
    """Przenosi plik do kosza systemowego (macOS Finder / Windows Recycle Bin)."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    if platform.system() == 'Darwin':
        path_lit = json.dumps(str(resolved))
        script = f'tell application "Finder" to delete POSIX file {path_lit}'
        proc = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            return
        try:
            _move_to_macos_trash_fallback(resolved)
            return
        except OSError as e:
            err = (proc.stderr or proc.stdout or '').strip() or str(e)
            raise RuntimeError(err) from e
    if platform.system() == 'Windows':
        try:
            from send2trash import send2trash
        except ImportError:
            send2trash = None
        if send2trash:
            send2trash(str(resolved))
            return
        raise RuntimeError('Brak obsługi kosza systemowego na Windows (zainstaluj send2trash).')
    try:
        from send2trash import send2trash
    except ImportError:
        raise RuntimeError('Brak obsługi kosza systemowego (zainstaluj send2trash).')
    send2trash(str(resolved))


def restore_file_from_system_trash(original_path: str) -> bool:
    """Próbuje przywrócić plik z kosza systemowego na pierwotną ścieżkę."""
    orig = Path(original_path).expanduser()
    name = orig.name
    if platform.system() == 'Darwin':
        trash_dir = Path.home() / '.Trash'
        if not trash_dir.is_dir():
            return False
        candidate = trash_dir / name
        if not candidate.exists():
            for f in trash_dir.iterdir():
                if f.name == name or f.name.startswith(name + ' '):
                    candidate = f
                    break
        if not candidate.exists():
            return False
        orig.parent.mkdir(parents=True, exist_ok=True)
        if orig.exists():
            stem, suf = orig.stem, orig.suffix
            n = 1
            while orig.exists():
                orig = orig.parent / f'{stem} ({n}){suf}'
                n += 1
        candidate.rename(orig)
        return True
    try:
        from send2trash import send2trash  # noqa: F401
    except ImportError:
        pass
    return False


def capture_vdjfolder_removals(paths_to_remove: set[str]) -> list[dict]:
    """Zapisuje fragmenty XML usuwane z playlist (do przywrócenia)."""
    import xml.etree.ElementTree as ET

    from vdjfolder import normalize_path

    refs: list[dict] = []
    for rel_path, content in st.vdjfolders.items():
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            continue
        for song in root.findall('song'):
            p = normalize_path(song.get('path') or '')
            if p in paths_to_remove:
                refs.append({
                    'rel_path': rel_path,
                    'song_xml': ET.tostring(song, encoding='unicode'),
                })
    return refs


def _append_item(item: dict) -> dict:
    st.trash_items.append(item)
    return item


def add_db_track_trash(
    song: dict,
    *,
    original_index: int,
    vdjfolder_refs: Optional[list[dict]] = None,
    source: str = 'remove-songs',
) -> dict:
    item = {
        'id': str(uuid.uuid4()),
        'kind': KIND_DB_TRACK,
        'status': STATUS_ACTIVE,
        'label': _song_label(song),
        'path': (song.get('FilePath') or '').strip(),
        'song': copy.deepcopy(song),
        'original_index': original_index,
        'vdjfolder_refs': vdjfolder_refs or [],
        'in_system_trash': False,
        'deleted_at': _now_iso(),
        'source': source,
    }
    return _append_item(item)


def add_file_trash(path: str, *, label: Optional[str] = None, source: str = 'delete-files') -> dict:
    p = Path(path)
    item = {
        'id': str(uuid.uuid4()),
        'kind': KIND_FILE,
        'status': STATUS_ACTIVE,
        'label': label or p.name,
        'path': str(p.expanduser()),
        'song': None,
        'original_index': None,
        'vdjfolder_refs': [],
        'in_system_trash': True,
        'deleted_at': _now_iso(),
        'source': source,
    }
    return _append_item(item)


def add_playlist_entry_trash(
    *,
    playlist_name: str,
    rel_path: str,
    song_path: str,
    song_xml: Optional[str] = None,
    filter_change: Optional[dict] = None,
    label: Optional[str] = None,
    source: str = 'playlist-remove-from',
) -> dict:
    item = {
        'id': str(uuid.uuid4()),
        'kind': KIND_PLAYLIST_ENTRY,
        'status': STATUS_ACTIVE,
        'label': label or f'{playlist_name}: {Path(song_path).name}',
        'path': song_path,
        'playlist_name': playlist_name,
        'playlist_rel_path': rel_path,
        'song_xml': song_xml,
        'filter_change': filter_change,
        'in_system_trash': False,
        'deleted_at': _now_iso(),
        'source': source,
    }
    return _append_item(item)


def add_combined_trash(
    song: dict,
    *,
    original_index: int,
    path: str,
    vdjfolder_refs: Optional[list[dict]] = None,
    source: str = 'combined',
) -> dict:
    item = {
        'id': str(uuid.uuid4()),
        'kind': KIND_COMBINED,
        'status': STATUS_ACTIVE,
        'label': _song_label(song),
        'path': path,
        'song': copy.deepcopy(song),
        'original_index': original_index,
        'vdjfolder_refs': vdjfolder_refs or [],
        'in_system_trash': True,
        'deleted_at': _now_iso(),
        'source': source,
    }
    return _append_item(item)


def list_trash(*, active_only: bool = True) -> list[dict]:
    items = st.trash_items
    if active_only:
        items = [i for i in items if i.get('status') == STATUS_ACTIVE]
    return [public_item(i) for i in items]


def public_item(item: dict) -> dict:
    kind = item.get('kind', '')
    category = 'other'
    if kind in (KIND_FILE,):
        category = 'files'
    elif kind in (KIND_DB_TRACK, KIND_COMBINED):
        category = 'tracks'
    elif kind == KIND_PLAYLIST_ENTRY:
        category = 'playlists'
    return {
        'id': item['id'],
        'kind': kind,
        'category': category,
        'status': item.get('status', STATUS_ACTIVE),
        'label': item.get('label', ''),
        'path': item.get('path', ''),
        'playlist_name': item.get('playlist_name'),
        'in_system_trash': bool(item.get('in_system_trash')),
        'deleted_at': item.get('deleted_at'),
        'source': item.get('source', ''),
        'can_restore': item.get('status') == STATUS_ACTIVE,
    }


def trash_summary() -> dict:
    active = [i for i in st.trash_items if i.get('status') == STATUS_ACTIVE]
    return {
        'count': len(active),
        'files': sum(1 for i in active if i.get('kind') in (KIND_FILE, KIND_COMBINED)),
        'tracks': sum(1 for i in active if i.get('kind') in (KIND_DB_TRACK, KIND_COMBINED)),
        'playlists': sum(1 for i in active if i.get('kind') == KIND_PLAYLIST_ENTRY),
    }


def clear_trash() -> None:
    st.trash_items.clear()


def _find_item(item_id: str) -> Optional[dict]:
    for item in st.trash_items:
        if item.get('id') == item_id:
            return item
    return None


def _restore_vdjfolder_refs(refs: list[dict]) -> None:
    import xml.etree.ElementTree as ET

    for ref in refs:
        rel_path = ref.get('rel_path')
        song_xml = ref.get('song_xml')
        if not rel_path or not song_xml:
            continue
        content = st.vdjfolders.get(rel_path)
        if not content:
            continue
        try:
            root = ET.fromstring(content)
            child = ET.fromstring(song_xml)
            root.append(child)
            st.vdjfolders[rel_path] = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
                root, encoding='unicode'
            )
        except ET.ParseError:
            continue


def restore_items(item_ids: list[str]) -> dict:
    restored = 0
    errors: list[str] = []
    for item_id in item_ids:
        item = _find_item(item_id)
        if not item or item.get('status') != STATUS_ACTIVE:
            errors.append(f'Pominięto (brak lub już przywrócono): {item_id[:8]}')
            continue
        try:
            _restore_one(item)
            item['status'] = STATUS_RESTORED
            restored += 1
        except Exception as e:
            errors.append(f'{item.get("label", item_id)[:40]}: {e}')
    return {'ok': True, 'restored': restored, 'errors': errors}


def _restore_one(item: dict) -> None:
    kind = item.get('kind')
    if kind == KIND_FILE:
        path = item.get('path') or ''
        if not restore_file_from_system_trash(path):
            raise RuntimeError('Nie znaleziono pliku w koszu systemowym')
        return

    if kind == KIND_DB_TRACK:
        song = item.get('song')
        if not song:
            raise RuntimeError('Brak danych utworu')
        idx = item.get('original_index')
        if isinstance(idx, int) and 0 <= idx <= len(st.songs):
            st.songs.insert(idx, copy.deepcopy(song))
        else:
            st.songs.append(copy.deepcopy(song))
        _restore_vdjfolder_refs(item.get('vdjfolder_refs') or [])
        return

    if kind == KIND_COMBINED:
        path = item.get('path') or ''
        if path and not restore_file_from_system_trash(path):
            raise RuntimeError('Nie znaleziono pliku w koszu systemowym')
        song = item.get('song')
        if song:
            idx = item.get('original_index')
            if isinstance(idx, int) and 0 <= idx <= len(st.songs):
                st.songs.insert(idx, copy.deepcopy(song))
            else:
                st.songs.append(copy.deepcopy(song))
        _restore_vdjfolder_refs(item.get('vdjfolder_refs') or [])
        return

    if kind == KIND_PLAYLIST_ENTRY:
        rel_path = item.get('playlist_rel_path')
        song_xml = item.get('song_xml')
        filter_change = item.get('filter_change')
        if song_xml and rel_path:
            _restore_vdjfolder_refs([{'rel_path': rel_path, 'song_xml': song_xml}])
            return
        if filter_change:
            idx = filter_change.get('idx')
            field = filter_change.get('field')
            tag = filter_change.get('tag')
            if isinstance(idx, int) and 0 <= idx < len(st.songs) and field and tag:
                key = f'Tags.{field}'
                cur = st.songs[idx].get(key, '') or ''
                tags = [t.strip() for t in str(cur).split(',') if t.strip()]
                if tag not in tags:
                    tags.append(tag)
                    st.songs[idx][key] = ','.join(tags)
            return
        raise RuntimeError('Brak danych do przywrócenia wpisu playlisty')


def dismiss_items(item_ids: list[str]) -> dict:
    """Usuwa z kosza sesji (pliki pozostają w koszu systemowym do opróżnienia przez użytkownika)."""
    dismissed = 0
    for item_id in item_ids:
        item = _find_item(item_id)
        if not item or item.get('status') != STATUS_ACTIVE:
            continue
        item['status'] = STATUS_DISMISSED
        dismissed += 1
    return {'ok': True, 'dismissed': dismissed}


def delete_files_to_trash(paths: list[str], *, source: str = 'delete-files') -> tuple[int, list[str]]:
    from file_analyzer import is_streaming

    deleted = 0
    errors: list[str] = []
    for path in paths:
        if is_streaming(path):
            errors.append(f'Pomijam (streaming): {path[:60]}…')
            continue
        p = Path(path)
        if not st.is_path_safe(p, must_be_file=True):
            errors.append(f'Ścieżka niedozwolona: {path[:50]}…')
            continue
        if not p.exists():
            errors.append(f'Nie istnieje: {path[:50]}…')
            continue
        try:
            move_file_to_system_trash(p)
            add_file_trash(str(p), source=source)
            deleted += 1
        except Exception as e:
            errors.append(f'{path[:50]}…: {e}')
    return deleted, errors
