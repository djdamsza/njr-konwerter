from __future__ import annotations

import platform
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from version_info import read_app_version
import updater

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
    return jsonify({'version': APP_VERSION, 'windows': platform.system() == 'Windows'})


@bp.route('/api/check-updates', methods=['POST'])
def api_check_updates():
    result = updater.check_for_updates(APP_VERSION)
    return jsonify(result)


@bp.route('/api/update-status')
def api_update_status():
    return jsonify(updater.get_status())


@bp.route('/api/download-update', methods=['POST'])
def api_download_update():
    st = updater.get_status()
    if st.get("status") == "downloading":
        return jsonify({"ok": True, "status": "downloading"})
    url = st.get("downloadUrl") or ""
    version = st.get("version") or ""
    name = st.get("assetName") or ""
    sha = st.get("sha256") or ""
    if not url or not name or not sha:
        return jsonify({"ok": False, "error": "Najpierw sprawdź, czy jest nowa wersja."}), 400
    updater.start_download(url, version, name, sha)
    return jsonify({"ok": True, "status": "downloading"})


@bp.route('/api/update-reveal', methods=['POST'])
def api_update_reveal():
    body = request.get_json(silent=True) or {}
    path = body.get("path") or updater.get_status().get("path") or ""
    return jsonify(updater.reveal_download(path))


@bp.route('/api/quit-for-update', methods=['POST'])
def api_quit_for_update():
    import os
    import threading
    threading.Timer(0.4, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


@bp.route('/api/install-update', methods=['POST'])
def api_install_update():
    body = request.get_json(silent=True) or {}
    result = updater.install_update(
        package_path=body.get('path') or None,
        target_path=body.get('target') or None,
        relaunch=bool(body.get('relaunch', True)),
    )
    return jsonify(result)


@bp.route('/favicon.ico')
def favicon():
    brand = Path(__file__).resolve().parent.parent / 'static' / 'brand'
    return send_from_directory(brand, 'app-icon.ico')
