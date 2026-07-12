from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify

import app_state as st

bp = Blueprint('session', __name__)


@bp.route('/api/undo-available', methods=['GET'])
def api_undo_available():
    return jsonify({'available': len(st.undo_stack) > 0, 'count': len(st.undo_stack)})


@bp.route('/api/undo', methods=['POST'])
def api_undo():
    if not st.undo_stack:
        return jsonify({'error': 'Brak operacji do cofnięcia'}), 400
    state = st.undo_stack.pop()
    st.songs = state['songs']
    st.vdjfolders = state['vdjfolders']
    st.extra_files = state.get('extra_files', {})
    st.version = state['version']
    st.source = state['source']
    st.db_path = Path(state['db_path']) if state.get('db_path') else None
    return jsonify({'ok': True, 'count': len(st.songs), 'undoRemaining': len(st.undo_stack)})


@bp.route('/api/status', methods=['GET'])
def api_status():
    return jsonify({
        'loaded': len(st.songs) > 0,
        'count': len(st.songs),
        'version': st.version,
        'path': str(st.db_path) if st.db_path else None,
        'loadedVia': 'path' if st.db_path else ('file' if st.songs else None),
        'source': st.source,
        'undoAvailable': len(st.undo_stack) > 0,
        'undoCount': len(st.undo_stack),
    })
