from __future__ import annotations

from flask import Blueprint, jsonify, request

import app_state as st
from license_njr import check_export_license, get_machine_id, save_license_key

bp = Blueprint('license', __name__)


@bp.route('/api/license/status', methods=['GET'])
def api_license_status():
    lic = check_export_license()
    return jsonify({
        'canExport': lic.get('allowed', False),
        'machineId': lic.get('machineId', get_machine_id()),
        'reason': lic.get('reason') if not lic.get('allowed') else None,
    })


@bp.route('/api/license/machine-id', methods=['GET'])
def api_license_machine_id():
    return jsonify({'machineId': get_machine_id()})


@bp.route('/api/license/activate', methods=['POST'])
def api_license_activate():
    data = request.get_json() or {}
    key = (data.get('key') or '').strip()
    if not key:
        return jsonify({'error': 'Brak klucza licencji'}), 400
    if save_license_key(key):
        return jsonify({'ok': True, 'message': 'Licencja aktywowana'})
    lic = check_export_license()
    return jsonify({'error': lic.get('reason', 'Nieprawidłowy klucz')}), 400
