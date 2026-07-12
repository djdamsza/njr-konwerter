"""RB Beta — porządek na plikach muzycznych bez bazy Rekordbox."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

import app_state as st

bp = Blueprint('rb_beta', __name__)


@bp.route('/api/rb-beta/status', methods=['GET'])
def api_rb_beta_status():
    return jsonify({
        'active': st.is_folder_beta(),
        'source': st.source,
        'count': len(st.songs),
        'folders': sorted(str(p) for p in st.folder_roots),
    })


@bp.route('/api/rb-beta/scan-folders', methods=['POST'])
def api_rb_beta_scan_folders():
    """
    Skanuje foldery z muzyką i ładuje je jako sesję RB Beta (bez bazy DJ).
    Body: { folderPaths: [...], computeHash?: bool }
    """
    data = request.get_json() or {}
    folders: list[str] = []
    if data.get('folderPaths'):
        folders = [str(f).strip() for f in data['folderPaths'] if str(f).strip()]
    if not folders and (data.get('folderPath') or '').strip():
        folders = [(data.get('folderPath') or '').strip()]
    if not folders:
        return jsonify({'error': 'Podaj co najmniej jeden folder (folderPaths)'}), 400

    compute_hash = bool(data.get('computeHash'))
    try:
        result = st.load_folder_beta(folders, compute_hash=compute_hash)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    if not result['count'] and result.get('errors'):
        return jsonify({'error': '; '.join(result['errors'][:5])}), 400

    return jsonify({
        'ok': True,
        'message': f'RB Beta: załadowano {result["count"]} plików z {len(result["folders"])} folderów',
        **result,
    })


@bp.route('/api/rb-beta/delete-files', methods=['POST'])
def api_rb_beta_delete_files():
    """
    Usuwa pliki fizycznie z dysku (tylko w obrębie zeskanowanych folderów RB Beta).
    Body: { paths: [...] }
    """
    if not st.is_folder_beta():
        return jsonify({'error': 'Dostępne tylko w trybie RB Beta'}), 400

    from pathlib import Path
    from file_analyzer import is_streaming

    data = request.get_json() or {}
    paths = [p for p in (data.get('paths') or []) if isinstance(p, str) and p.strip()]
    deleted = 0
    errors: list[str] = []
    removed_indices: list[int] = []

    path_to_idx = {
        (s.get('FilePath') or ''): i
        for i, s in enumerate(st.songs)
        if s.get('FilePath')
    }

    for path in paths:
        if is_streaming(path):
            errors.append(f'Pomijam (streaming): {path[:60]}…')
            continue
        p = Path(path)
        if not st.is_path_safe(p, must_be_file=True):
            errors.append(f'Ścieżka niedozwolona: {path[:50]}…')
            continue
        if p.exists():
            try:
                p.unlink()
                deleted += 1
                idx = path_to_idx.get(path)
                if idx is not None:
                    removed_indices.append(idx)
            except OSError as e:
                errors.append(f'Błąd {path[:50]}…: {e}')
        else:
            errors.append(f'Nie istnieje: {path[:50]}…')
            idx = path_to_idx.get(path)
            if idx is not None:
                removed_indices.append(idx)

    for i in sorted(set(removed_indices), reverse=True):
        if 0 <= i < len(st.songs):
            st.songs.pop(i)

    return jsonify({
        'ok': True,
        'deleted': deleted,
        'removedFromSession': len(set(removed_indices)),
        'count': len(st.songs),
        'errors': errors,
    })
