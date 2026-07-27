from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request

import app_state as st
from constants import AUDIO_EXTENSIONS
from native_dialogs import pick_folder_native
from vdjfolder import normalize_path

bp = Blueprint('files', __name__)


@bp.route('/api/pick-folder', methods=['GET'])
def api_pick_folder():
    path = pick_folder_native()
    if path:
        return jsonify({'path': path})
    return jsonify({'error': 'Nie wybrano folderu lub brak obsługi okna dialogowego'}), 400


@bp.route('/api/database-folders', methods=['GET'])
def api_database_folders():
    st.ensure_loaded()
    folders = set()
    for s in st.songs:
        fp = s.get('FilePath', '') or ''
        if fp and not fp.strip().startswith(('td', 'netsearch:', 'soundcloud:', 'beatport:', 'deezer:')):
            if not fp.lower().endswith('.vdjcache'):
                try:
                    p = Path(fp.replace('\\', '/'))
                    parent = p.parent.resolve()
                    if parent and str(parent) not in ('.', '') and parent.exists() and parent.is_dir():
                        folders.add(str(parent))
                except (OSError, ValueError):
                    pass
    return jsonify({'folders': sorted(folders), 'count': len(folders)})


def _scan_folder_for_orphans(folder: str, db_paths: set) -> list:
    orphans = []
    p = Path(folder)
    for f in p.rglob('*'):
        if not f.is_file():
            continue
        if f.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        np = normalize_path(str(f.resolve()))
        if np not in db_paths:
            orphans.append({'path': np, 'name': f.name})
    return orphans


def _enrich_orphan_with_metadata(o: dict) -> dict:
    try:
        from file_analyzer import read_file_metadata_extended
        meta = read_file_metadata_extended(o['path'])
        o['Tags.Author'] = meta.get('artist') or ''
        o['Tags.Artist'] = meta.get('artist') or ''
        o['Tags.Title'] = meta.get('title') or o.get('name', '').rsplit('.', 1)[0] if o.get('name') else ''
        o['Tags.Genre'] = meta.get('genre') or ''
        o['Tags.User1'] = ''
        o['Tags.User2'] = ''
        o['Infos.PlayCount'] = ''
        o['Infos.SongLength'] = meta.get('length') or 0
        bpm = meta.get('bpm') or 0
        o['Tags.Bpm'] = str(60 / bpm) if bpm and bpm > 0 else ''
        o['Tags.Key'] = meta.get('key') or ''
        o['Tags.Stars'] = meta.get('rating') or ''
        o['FilePath'] = o['path']
        o['pathDisplay'] = o['path']
    except Exception:
        pass
    return o


@bp.route('/api/scan-orphan-files', methods=['POST'])
def api_scan_orphan_files():
    st.ensure_loaded()
    data = request.get_json() or {}
    folders = []
    if data.get('folderPaths'):
        folders = [str(f).strip() for f in data['folderPaths'] if str(f).strip()]
    if not folders and (data.get('folderPath') or '').strip():
        folders = [(data.get('folderPath') or '').strip()]
    if not folders:
        return jsonify({'error': 'Podaj ścieżkę folderu lub foldery'}), 400

    db_paths = set()
    for s in st.songs:
        fp = s.get('FilePath', '') or ''
        if fp and not fp.strip().startswith(('td', 'netsearch:', 'soundcloud:', 'beatport:', 'deezer:')):
            if not fp.lower().endswith('.vdjcache'):
                np = normalize_path(fp)
                if np:
                    db_paths.add(np)

    all_orphans = []
    seen_paths = set()
    errors = []
    for folder in folders:
        p = Path(folder)
        if not p.exists():
            errors.append(f'Folder nie istnieje: {folder}')
            continue
        if not p.is_dir():
            errors.append(f'Ścieżka nie jest folderem: {folder}')
            continue
        if not st.is_folder_scan_allowed(p):
            errors.append(f'Folder poza biblioteką (niedozwolony): {folder}')
            continue
        try:
            for o in _scan_folder_for_orphans(folder, db_paths):
                np = normalize_path(o['path'])
                if np and np not in seen_paths:
                    seen_paths.add(np)
                    all_orphans.append(_enrich_orphan_with_metadata(o))
        except PermissionError as e:
            errors.append(f'Brak dostępu do {folder}: {e}')
        except OSError as e:
            errors.append(f'Błąd skanowania {folder}: {e}')
    if errors and not all_orphans:
        return jsonify({'error': '; '.join(errors)}), 400
    return jsonify({'files': all_orphans, 'count': len(all_orphans), 'errors': errors if errors else None})


@bp.route('/api/open-folder', methods=['POST'])
def api_open_folder():
    data = request.get_json() or {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'error': 'Brak ścieżki'}), 400
    try:
        p = Path(path)
        if p.is_file():
            folder_path = p.parent
        elif p.is_dir():
            folder_path = p
        else:
            folder_path = p.parent if p.parent else p
        if not st.is_path_safe(folder_path, must_be_file=False) and not st.is_folder_scan_allowed(folder_path):
            return jsonify({'error': 'Ścieżka niedozwolona (poza katalogami bazy)'}), 403
        folder = str(folder_path)
        if platform.system() == 'Darwin':
            subprocess.run(['open', folder], check=True, timeout=5)
        elif platform.system() == 'Windows':
            subprocess.run(['explorer', folder], check=True, timeout=5)
        else:
            for cmd in [['xdg-open', folder], ['nautilus', folder], ['dolphin', folder]]:
                try:
                    subprocess.run(cmd, check=True, timeout=5)
                    break
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            else:
                return jsonify({'error': 'Brak obsługi otwierania folderu na tym systemie'}), 400
        return jsonify({'ok': True})
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Przekroczono limit czasu'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/orphan-file', methods=['DELETE'])
def api_delete_orphan_file():
    st.ensure_loaded()
    import session_trash as trash
    data = request.get_json() or {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'error': 'Brak ścieżki'}), 400
    p = Path(path)
    if not st.is_path_safe(p, must_be_file=True):
        return jsonify({'error': 'Ścieżka niedozwolona (poza katalogami bazy)'}), 403
    if not p.exists():
        return jsonify({'error': 'Plik nie istnieje'}), 404
    if not p.is_file():
        return jsonify({'error': 'Nie jest plikiem'}), 400
    if p.suffix.lower() not in AUDIO_EXTENSIONS:
        return jsonify({'error': 'Nieprawidłowy typ pliku'}), 400
    try:
        trash.move_file_to_system_trash(p)
        trash.add_file_trash(str(p), source='orphan-file')
    except PermissionError:
        return jsonify({'error': 'Brak uprawnień do usunięcia'}), 403
    except OSError as e:
        return jsonify({'error': 'Błąd usuwania: ' + str(e)}), 500
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True, 'trash': trash.trash_summary()})
