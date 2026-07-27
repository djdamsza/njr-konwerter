from __future__ import annotations

from flask import Blueprint, jsonify, request

import session_trash as trash

bp = Blueprint('trash', __name__)


@bp.route('/api/trash', methods=['GET'])
def api_trash_list():
    return jsonify({
        'items': trash.list_trash(active_only=True),
        'summary': trash.trash_summary(),
    })


@bp.route('/api/trash/restore', methods=['POST'])
def api_trash_restore():
    data = request.get_json() or {}
    ids = [str(i) for i in (data.get('ids') or []) if i]
    if not ids:
        return jsonify({'error': 'Podaj ids'}), 400
    result = trash.restore_items(ids)
    return jsonify(result)


@bp.route('/api/trash/dismiss', methods=['POST'])
def api_trash_dismiss():
    """
    Usuwa zaznaczone elementy z kosza sesji (bez przywracania).
    Pliki muzyczne pozostają w koszu systemowym macOS — opróżnij Kosz Findera, aby usunąć je na stałe.
    """
    data = request.get_json() or {}
    ids = [str(i) for i in (data.get('ids') or []) if i]
    if not ids:
        return jsonify({'error': 'Podaj ids'}), 400
    if not data.get('confirmed'):
        return jsonify({
            'error': 'confirmation_required',
            'message': (
                'Potwierdź trwałe usunięcie z kosza sesji. '
                'Pliki muzyczne nadal są w koszu systemowym — opróżnij Kosz Findera, aby usunąć je z dysku.'
            ),
        }), 400
    result = trash.dismiss_items(ids)
    return jsonify(result)
