from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, jsonify, send_from_directory

from version_info import read_app_version

bp = Blueprint('meta', __name__)

APP_VERSION = read_app_version()


@bp.route('/')
def index():
    return send_from_directory('static', 'index.html')


@bp.route('/tidal-embed-autoplay.user.js')
def tidal_autoplay_script():
    script_dir = Path(__file__).resolve().parent.parent / 'scripts'
    return send_from_directory(script_dir, 'tidal-embed-autoplay.user.js', mimetype='application/javascript')


@bp.route('/api/version')
def api_version():
    return jsonify({'version': APP_VERSION})


@bp.route('/api/check-updates', methods=['POST'])
def api_check_updates():
    return jsonify({
        'available': False,
        'message': 'Masz najnowszą wersję.',
        'manualUrl': '',
    })


@bp.route('/favicon.ico')
def favicon():
    return Response(b'', status=204)
