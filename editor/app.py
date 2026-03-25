"""
Edytor bazy danych VirtualDJ – serwer Flask.
Uruchom: python app.py
Otwórz: http://127.0.0.1:5050
"""
from __future__ import annotations

import concurrent.futures
import copy
import json
import platform
import re
import shutil
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional


def _path_exists_timeout(path: str, timeout_sec: float = 0.5) -> bool:
    """Path.exists() z timeout – unika blokady przy ścieżkach sieciowych."""
    if not path or not path.strip():
        return False
    p = Path(path.strip())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        f = ex.submit(p.exists)
        try:
            return f.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            return True

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

from vdj_parser import (
    load_database,
    save_database,
    get_all_tags,
    merge_tags_in_songs,
    merge_tags_across_fields,
    remove_tags_in_songs,
    merge_tags_in_songs_by_indices,
    remove_tags_in_songs_by_indices,
    parse_tags_value,
    join_tags,
)
from vdjfolder import (
    update_filter_merge,
    update_filter_remove,
    vdjfolders_to_playlists,
    filter_lists_to_regular_playlists,
    normalize_path,
    scan_vdjfolders,
)
from rb_parser import load_rb_xml
from vdj_adapter import vdj_songs_to_unified, unified_to_vdj_songs
from engine_parser import load_engine_db
from traktor_parser import load_traktor_nml
from serato_parser import load_serato_database_v2, load_serato_folder, save_serato_database_v2, save_serato_crate
from rb_generator import generate_rb_xml, generate_rb_playlists_only_xml
from rb_masterdb_generator import unified_to_master_db
from djxml_generator import generate_djxml
from djxml_parser import load_djxml
from unified_model import UnifiedDatabase
from tag_writer import write_tags_batch

import sys

_static_dir = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'static'
app = Flask(__name__, static_folder=str(_static_dir))
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024 * 1024  # 4 GB – bazy RB bywają 2 GB+

_CORS_ORIGINS = [f'http://127.0.0.1:{p}' for p in range(5050, 5061)] + [f'http://localhost:{p}' for p in range(5050, 5061)]
CORS(app, origins=_CORS_ORIGINS, supports_credentials=True)

APP_VERSION = "1.0.0"  # Będzie z config przy integracji z GitHub

# Stan w pamięci – baza załadowana w sesji
_db_path: Optional[Path] = None
_songs: list[dict] = []
_version: str = ''
_vdjfolders: dict[str, str] = {}  # {relative_path: content}
_extra_files: dict[str, bytes] = {}  # History/*.m3u, *.subfolders/order – pliki spoza vdjfolder (zachowujemy 1:1)
_source: str = 'vdj'  # 'vdj' | 'rb' – skąd załadowano
_unified: Optional[UnifiedDatabase] = None  # Zachowane przy imporcie RB (playlisty)

# Cofnij – stos stanów przed modyfikacjami
_undo_stack: list[dict] = []
_UNDO_MAX = 10

# Licencja – eksport wymaga klucza (wersja bezpłatna: pełna edycja, brak eksportu)
try:
    from license_njr import check_export_license, save_license_key, get_machine_id
except ImportError:
    def check_export_license():
        return {'allowed': True}
    def save_license_key(_):
        return False
    def get_machine_id():
        return 'unknown'


def _ensure_loaded():
    if not _songs:
        raise ValueError(
            'Baza nie została załadowana. Najpierw załaduj backup VDJ: '
            '„VDJ: plik ZIP (backup)” lub „VDJ: folder” + Załaduj. '
            'Uwaga: po restarcie serwera baza jest czyszczona – załaduj ponownie.'
        )


def _get_allowed_path_roots() -> set:
    """Zwraca katalogi nadrzędne plików z bazy – tylko tam wolno usuwać/modyfikować pliki."""
    roots = set()
    from file_analyzer import is_streaming
    for s in _songs:
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


def _is_path_safe(path: Path, *, must_be_file: bool = False) -> bool:
    """Czy ścieżka znajduje się w dozwolonym katalogu (nadrzędnym względem plików z bazy)."""
    if not path:
        return False
    try:
        resolved = path.expanduser().resolve()
        if must_be_file and not resolved.is_file():
            return False
        roots = _get_allowed_path_roots()
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


def _clear_undo_stack():
    """Czyści stos cofnięć przy ładowaniu nowej bazy."""
    global _undo_stack
    _undo_stack.clear()


def _push_undo_state():
    """Zapisuje bieżący stan przed modyfikacją (do cofnięcia)."""
    global _undo_stack
    if len(_undo_stack) >= _UNDO_MAX:
        _undo_stack.pop(0)
    _undo_stack.append({
        'songs': copy.deepcopy(_songs),
        'vdjfolders': copy.deepcopy(_vdjfolders),
        'extra_files': {k: v for k, v in _extra_files.items()},
        'version': _version,
        'source': _source,
        'db_path': str(_db_path) if _db_path else None,
    })


def _require_export_license():
    """Zwraca (response, 403) gdy brak licencji, inaczej None."""
    lic = check_export_license()
    if not lic.get('allowed'):
        return jsonify({
            'error': 'license_required',
            'reason': lic.get('reason', 'Eksport wymaga licencji. Zachowaj postęp i wykup licencję.'),
            'machineId': lic.get('machineId', ''),
        }), 403
    return None


_NJR_KEY = b'NJR-SAVE-KEY'


def _encode_njr(data: dict) -> bytes:
    """Koduje dane do formatu .njr (gzip + XOR) – tylko aplikacja może odczytać."""
    import gzip
    raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
    compressed = gzip.compress(raw)
    return bytes(b ^ _NJR_KEY[i % len(_NJR_KEY)] for i, b in enumerate(compressed))


def _decode_njr(encoded: bytes) -> dict:
    """Dekoduje plik .njr."""
    import gzip
    decoded = bytes(b ^ _NJR_KEY[i % len(_NJR_KEY)] for i, b in enumerate(encoded))
    return json.loads(gzip.decompress(decoded).decode('utf-8'))


@app.errorhandler(ValueError)
def handle_value_error(e):
    """Zwraca 400 z JSON zamiast 500 przy braku załadowanej bazy."""
    return jsonify({'error': str(e)}), 400


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/tidal-embed-autoplay.user.js')
def tidal_autoplay_script():
    """Userscript Tampermonkey – auto-klik Play w Tidal embed."""
    script_dir = Path(__file__).resolve().parent / 'scripts'
    return send_from_directory(script_dir, 'tidal-embed-autoplay.user.js', mimetype='application/javascript')


@app.route('/api/version')
def api_version():
    return jsonify({'version': APP_VERSION})


@app.route('/api/check-updates', methods=['POST'])
def api_check_updates():
    """Placeholder – później: request do GitHub Releases."""
    return jsonify({
        'available': False,
        'message': 'Masz najnowszą wersję.',
        'manualUrl': '',
    })


@app.route('/favicon.ico')
def favicon():
    from flask import Response
    return Response(b'', status=204)


def _load_from_content(content: bytes) -> tuple[list, str]:
    """Ładuje bazę z zawartości XML (bytes)."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as f:
        f.write(content)
        tmp = Path(f.name)
    try:
        songs, version = load_database(tmp)
        return songs, version
    finally:
        tmp.unlink(missing_ok=True)


def _fix_zip_filename_encoding(name: str) -> str:
    """
    Naprawia błędy kodowania nazw w ZIP (np. polskie ł).
    Gdy ZIP ma UTF-8/CP1250 bez flagi, Python używa CP437 – przywracamy właściwe kodowanie.
    """
    try:
        raw = name.encode('cp437')
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            return raw.decode('cp1250')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return name


def _load_from_zip(zip_path_or_file) -> tuple[bytes, dict[str, str], dict[str, bytes]]:
    """
    Czyta ZIP (backup VDJ) i zwraca (database.xml bytes, {rel_path: vdjfolder_content}, {rel_path: bytes}).
    Zachowuje History/*.m3u, *.subfolders/order i inne pliki – zasada: nie usuwamy informacji.
    """
    db_content = None
    vdjfiles: dict[str, str] = {}
    extra_files: dict[str, bytes] = {}
    try:
        z = zipfile.ZipFile(zip_path_or_file, 'r', metadata_encoding='utf-8')
    except TypeError:
        z = zipfile.ZipFile(zip_path_or_file, 'r')
    with z:
        for name in z.namelist():
            bn = name.split('/')[-1].split('\\')[-1].lower()
            if bn.startswith('database') and bn.endswith('.xml'):
                db_content = z.read(name)
                break
        if db_content is None:
            for name in z.namelist():
                if name.lower().endswith('database.xml') or '/database.xml' in name.lower():
                    db_content = z.read(name)
                    break
        if db_content is None:
            raise ValueError('W archiwum ZIP nie znaleziono database.xml')
        for name in z.namelist():
            if name.endswith('/'):
                continue
            bn = name.split('/')[-1].split('\\')[-1].lower()
            if bn.startswith('database') and bn.endswith('.xml'):
                continue
            try:
                fixed_name = _fix_zip_filename_encoding(name)
                raw = z.read(name)
                if name.lower().endswith('.vdjfolder'):
                    vdjfiles[fixed_name] = raw.decode('utf-8', errors='replace')
                else:
                    extra_files[fixed_name] = raw
            except Exception:
                pass
    return db_content, vdjfiles, extra_files


@app.route('/api/load', methods=['POST'])
def api_load():
    """Ładuje database.xml z podanej ścieżki (lub ZIP – backup VDJ)."""
    global _db_path, _songs, _version, _vdjfolders, _source, _unified
    _clear_undo_stack()
    data = request.get_json() or {}
    path = data.get('path', '').strip()
    if not path:
        return jsonify({'error': 'Brak ścieżki'}), 400
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return jsonify({'error': f'Plik nie istnieje: {p}'}), 404
    try:
        if p.is_dir():
            serato_dir = p / "_Serato_"
            db_v2 = serato_dir / "database V2"
            if not db_v2.exists():
                db_v2 = serato_dir / "DatabaseV2"
            if serato_dir.is_dir() and db_v2.exists():
                drive_root = (data.get("driveRoot") or "").strip() or None
                db = load_serato_folder(p, drive_root=drive_root)
                _songs = unified_to_vdj_songs(db)
                _unified = db
                _version = ""
                _db_path = None
                _vdjfolders = {}
                _extra_files = {}
                _source = "serato"
                return jsonify({
                    "ok": True, "count": len(_songs), "playlists": len(db.playlists),
                    "path": str(p), "loadedVia": "path", "source": "serato",
                })
            raise ValueError("Folder nie zawiera biblioteki Serato (_Serato_/database V2)")
        if p.suffix.lower() == '.zip':
            db_content, vdjfiles, extra = _load_from_zip(p)
            _songs, _version = _load_from_content(db_content)
            _db_path = None
            _vdjfolders = vdjfiles
            _extra_files = extra
        else:
            _songs, _version = load_database(p)
            _db_path = p
            # Skanuj folder w poszukiwaniu .vdjfolder (gdy ładowanie z folderu, nie ZIP)
            base = p.parent
            scanned = scan_vdjfolders(base)
            _vdjfolders = {str(fp.relative_to(base)).replace("\\", "/"): content for fp, content in scanned.items()}
            _extra_files = {}
        _source = 'vdj'
        _unified = None
        return jsonify({
            'ok': True,
            'count': len(_songs),
            'version': _version,
            'path': str(p),
            'loadedVia': 'path',
            'source': 'vdj',
            'vdjfolders': len(_vdjfolders),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/load-file', methods=['POST'])
def api_load_file():
    """Ładuje database.xml i opcjonalnie pliki .vdjfolder z przesłanych plików. Obsługuje też ZIP (backup VDJ) – bez rozpakowywania."""
    global _db_path, _songs, _version, _vdjfolders, _extra_files, _source, _unified
    _clear_undo_stack()
    db_content = None
    vdjfiles = {}
    extra: dict[str, bytes] = {}
    zip_loaded = False
    for key in request.files:
        for f in request.files.getlist(key):
            fn = getattr(f, 'filename', None) or ''
            if not fn:
                continue
            content = f.read()
            basename = fn.split('/')[-1].split('\\')[-1].lower().strip()
            if basename.endswith('.zip'):
                try:
                    db_content, vdjfiles, extra = _load_from_zip(BytesIO(content))
                    zip_loaded = True
                    break
                except Exception as ex:
                    return jsonify({'error': f'Błąd odczytu ZIP: {ex}'}), 400
            elif basename.startswith('database') and basename.endswith('.xml'):
                db_content = content
            elif basename.endswith('.vdjfolder'):
                rel = fn
                vdjfiles[rel] = content.decode('utf-8', errors='replace')
        if zip_loaded:
            break
    if not db_content and request.data:
        db_content = request.data
    if not db_content:
        received = [getattr(f, 'filename', '?') for k in request.files for f in request.files.getlist(k)]
        err = 'Nie przesłano database.xml ani pliku ZIP'
        if received:
            err += f'. Otrzymano: {", ".join(received[:5])}{"…" if len(received) > 5 else ""}'
        return jsonify({'error': err}), 400
    try:
        _songs, _version = _load_from_content(db_content)
        _db_path = None
        _vdjfolders = vdjfiles
        _extra_files = extra if zip_loaded else {}
        _source = 'vdj'
        _unified = None
        return jsonify({
            'ok': True,
            'count': len(_songs),
            'version': _version,
            'vdjfolders': len(_vdjfolders),
            'loadedVia': 'file',
            'source': 'vdj',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/load-universal', methods=['POST'])
def api_load_universal():
    """
    Uniwersalny import – wykrywa format po rozszerzeniu i zawartości.
    Obsługuje: VDJ (ZIP, database.xml), Rekordbox (XML), DJXML, Engine DJ (m.db), Traktor (collection.nml).
    Jeden plik – jedna baza. Eksport na razie do VDJ (Pobierz database.xml). RB/DJXML/Engine/Traktor – eksport do tego samego formatu w planach.
    """
    global _db_path, _songs, _version, _vdjfolders, _extra_files, _source, _unified
    _clear_undo_stack()
    f = request.files.get("file") or request.files.get("universal")
    if not f or not getattr(f, "filename", ""):
        return jsonify({"error": "Nie wybrano pliku"}), 400
    content = f.read()
    fn = (getattr(f, "filename", "") or "").lower()
    ext = Path(fn).suffix.lower() if fn else ""
    try:
        if ext == ".njr" or fn.endswith(".njr"):
            # Zachowany postęp (format aplikacji – tylko tu można odczytać)
            import base64
            data = _decode_njr(content)
            _songs = data.get("songs", [])
            _vdjfolders = data.get("vdjfolders", {})
            _extra_files = {}
            for k, v in data.get("extra_files", {}).items():
                try:
                    _extra_files[k] = base64.b64decode(v) if isinstance(v, str) else bytes(v)
                except Exception:
                    pass
            _version = data.get("version", "")
            _source = data.get("source", "vdj")
            _db_path = None
            _unified = None
            return jsonify({
                "ok": True,
                "count": len(_songs),
                "source": _source,
                "vdjfolders": len(_vdjfolders),
                "message": "Załadowano zachowany postęp (.njr)",
            })
        if ext == ".zip" or "vdj" in fn:
            with zipfile.ZipFile(BytesIO(content), "r") as z:
                names = z.namelist()
            serato_db = next((n for n in names if "_serato_" in n.lower() and "database v2" in n.lower()), None)
            if serato_db:
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    with zipfile.ZipFile(BytesIO(content), "r") as z:
                        z.extractall(tmpdir)
                    drive_root = (request.form.get("driveRoot") or "").strip() or None
                    serato_folder = Path(tmpdir) / Path(serato_db).parent
                    db = load_serato_folder(serato_folder, drive_root=drive_root)
                    _songs = unified_to_vdj_songs(db)
                    _unified = db
                    _version = ""
                    _db_path = None
                    _vdjfolders = {}
                    _extra_files = {}
                    _source = "serato"
                    return jsonify({
                        "ok": True, "count": len(_songs), "playlists": len(db.playlists),
                        "source": "serato", "message": "Załadowano Serato DJ (ZIP z _Serato_)",
                    })
            db_content, vdjfiles, extra = _load_from_zip(BytesIO(content))
            _songs, _version = _load_from_content(db_content)
            _db_path = None
            _vdjfolders = vdjfiles
            _extra_files = extra
            _source = "vdj"
            _unified = None
            return jsonify({
                "ok": True, "count": len(_songs), "version": _version,
                "source": "vdj", "vdjfolders": len(_vdjfolders),
                "message": "Załadowano backup VDJ (ZIP)",
            })
        if ext == ".m.db" or fn.endswith("m.db"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".m.db", delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            try:
                library_base = (request.form.get("libraryBase") or "").strip() or None
                db = load_engine_db(tmp_path, library_base)
                _songs = unified_to_vdj_songs(db)
                _unified = db
                _version = ""
                _db_path = None
                _vdjfolders = {}
                _extra_files = {}
                _source = "engine"
                return jsonify({
                    "ok": True, "count": len(_songs), "playlists": len(db.playlists),
                    "source": "engine", "message": "Załadowano Engine DJ (m.db)",
                })
            finally:
                tmp_path.unlink(missing_ok=True)
        if ext == ".nml" or "collection" in fn:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".nml", delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            try:
                db = load_traktor_nml(tmp_path)
                _songs = unified_to_vdj_songs(db)
                _unified = db
                _version = ""
                _db_path = None
                _vdjfolders = {}
                _extra_files = {}
                _source = "traktor"
                return jsonify({
                    "ok": True, "count": len(_songs), "playlists": len(db.playlists),
                    "source": "traktor", "message": "Załadowano Traktor (collection.nml)",
                })
            finally:
                tmp_path.unlink(missing_ok=True)
        fn_lower = fn.lower().strip()
        if "database v2" in fn_lower or "databasev2" in fn_lower or fn_lower == "database v2":
            drive_root = (request.form.get("driveRoot") or "").strip() or None
            db = load_serato_database_v2(content, drive_root=drive_root)
            _songs = unified_to_vdj_songs(db)
            _unified = db
            _version = ""
            _db_path = None
            _vdjfolders = {}
            _extra_files = {}
            _source = "serato"
            return jsonify({
                "ok": True, "count": len(_songs), "playlists": len(db.playlists),
                "source": "serato", "message": "Załadowano Serato DJ (database V2)",
            })
        if ext == ".djxml":
            db = load_djxml(content)
            _songs = unified_to_vdj_songs(db)
            _db_path = None
            _vdjfolders = {}
            _extra_files = {}
            _source = "djxml"
            _unified = db
            _version = "1.0"
            return jsonify({
                "ok": True, "count": len(_songs), "playlists": len(db.playlists),
                "source": "djxml", "message": "Załadowano DJXML",
            })
        if ext == ".xml":
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            try:
                try:
                    db = load_rb_xml(tmp_path)
                    _songs = unified_to_vdj_songs(db)
                    _unified = db
                    _version = ""
                    _db_path = None
                    _vdjfolders = {}
                    _extra_files = {}
                    _source = "rb"
                    return jsonify({
                        "ok": True, "count": len(_songs), "playlists": len(db.playlists),
                        "source": "rb", "message": "Załadowano Rekordbox (XML)",
                    })
                except Exception:
                    pass
                _songs, _version = load_database(tmp_path)
                _db_path = None
                _vdjfolders = {}
                _extra_files = {}
                _source = "vdj"
                _unified = None
                return jsonify({
                    "ok": True, "count": len(_songs), "version": _version,
                    "source": "vdj", "message": "Załadowano VirtualDJ (database.xml)",
                })
            finally:
                tmp_path.unlink(missing_ok=True)
        if "database" in fn and ext == ".xml":
            _songs, _version = _load_from_content(content)
            _db_path = None
            _vdjfolders = {}
            _extra_files = {}
            _source = "vdj"
            _unified = None
            return jsonify({
                "ok": True, "count": len(_songs), "version": _version,
                "source": "vdj", "message": "Załadowano VirtualDJ (database.xml)",
            })
        return jsonify({
            "error": f"Nieznany format. Obsługiwane: .zip (VDJ), .xml (VDJ/RB), .djxml, .m.db (Engine), .nml (Traktor), database V2 (Serato). Otrzymano: {ext or fn[:30]}",
        }), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/load-djxml', methods=['POST'])
def api_load_djxml():
    """Ładuje plik DJXML (otwarty format – Mixo, djxml.com)."""
    global _db_path, _songs, _version, _vdjfolders, _source, _unified
    _clear_undo_stack()
    f = request.files.get('file') or request.files.get('djxml')
    if not f or not getattr(f, 'filename', ''):
        return jsonify({'error': 'Nie wybrano pliku DJXML'}), 400
    try:
        content = f.read()
        db = load_djxml(content)
        _songs = unified_to_vdj_songs(db)
        _db_path = None
        _vdjfolders = {}
        _extra_files = {}
        _source = 'djxml'
        _unified = db
        _version = '1.0'
        return jsonify({
            'ok': True,
            'count': len(_songs),
            'playlists': len(db.playlists),
            'loadedVia': 'file',
            'source': 'djxml',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/save', methods=['POST'])
def api_save():
    """Zapisuje zmiany do pliku (gdy jest ścieżka)."""
    global _db_path, _songs, _version
    _ensure_loaded()
    data = request.get_json() or {}
    path = data.get('path', '').strip() or (_db_path and str(_db_path))
    if not path:
        return jsonify({'error': 'Brak ścieżki. Załaduj przez wybór folderu – zapis przez pobranie pliku.'}), 400
    p = Path(path).expanduser().resolve()
    if p.exists():
        backup = p.with_suffix('.xml.bak')
        shutil.copy2(p, backup)
    try:
        save_database(p, _songs, _version)
        return jsonify({'ok': True, 'path': str(p)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download')
def api_download():
    """Pobiera database.xml lub ZIP (z vdjfolder) gdy są listy."""
    return _do_download(filename=None)


@app.route('/api/backup')
def api_backup():
    """Pobiera kopię zapasową (ZIP) z timestampem – do bezpiecznego przechowania przed edycją."""
    from datetime import datetime
    ts = datetime.now().strftime('%Y-%m-%d_%H%M')
    return _do_download(filename=f'vdj-backup-{ts}.zip')


@app.route('/api/save-progress', methods=['POST'])
def api_save_progress():
    """
    Zachowaj postęp – zapisuje bazę w formacie .njr (tylko aplikacja może odczytać).
    Nie wymaga licencji. Plik można otworzyć ponownie w aplikacji.
    Eksport do VDJ/Serato/RB wymaga licencji.
    """
    global _songs, _version, _vdjfolders, _extra_files, _source
    _ensure_loaded()
    import base64
    from datetime import datetime
    from flask import Response
    data = {
        'v': 1,
        'songs': _songs,
        'vdjfolders': _vdjfolders,
        'extra_files': {k: base64.b64encode(v).decode('ascii') for k, v in _extra_files.items()},
        'version': _version,
        'source': _source,
    }
    encoded = _encode_njr(data)
    ts = datetime.now().strftime('%Y-%m-%d_%H%M')
    fn = f'njr-postep-{ts}.njr'
    return Response(
        encoded,
        mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{fn}"'},
    )


def _do_download(filename=None):
    """Wspólna logika pobierania database.xml lub ZIP."""
    r = _require_export_license()
    if r:
        return r
    global _songs, _version, _vdjfolders, _extra_files
    _ensure_loaded()
    from io import BytesIO
    from flask import Response
    import zipfile

    if not _vdjfolders and not _extra_files and not filename:
        buf = BytesIO()
        save_database(buf, _songs, _version)
        data = buf.getvalue()
        return Response(
            data,
            mimetype='application/xml',
            headers={'Content-Disposition': 'attachment; filename="database.xml"'},
        )
    z = BytesIO()
    with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as zf:
        buf = BytesIO()
        save_database(buf, _songs, _version)
        zf.writestr('database.xml', buf.getvalue())
        for rel_path, content in _vdjfolders.items():
            zf.writestr(rel_path, content.encode('utf-8'))
        for rel_path, raw in _extra_files.items():
            zf.writestr(rel_path, raw)
    data = z.getvalue()
    fn = filename or 'vdj-backup.zip'
    return Response(
        data,
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{fn}"'},
    )


def _eval_filter_condition(cond: str, song: dict) -> bool:
    """Sprawdza pojedynczy warunek filtra VDJ (np. 'User 1 has tag X')."""
    import re
    cond = cond.strip().lower()
    if 'has tag' in cond:
        m = re.search(r'(?:user\s*1|user\s*2|genre)\s+has\s+tag\s+["\']?([^"\'\s]+)', cond, re.I)
        if m:
            tag = m.group(1).strip().lstrip('#')
            if 'user 1' in cond or 'user1' in cond.replace(' ', ''):
                tags = set(t.lstrip('#').lower() for t in parse_tags_value(song.get('Tags.User1', '')))
                return tag.lower() in tags
            if 'user 2' in cond or 'user2' in cond.replace(' ', ''):
                tags = set(t.lstrip('#').lower() for t in parse_tags_value(song.get('Tags.User2', '')))
                return tag.lower() in tags
            if 'genre' in cond:
                tags = set(t.lstrip('#').lower() for t in parse_tags_value(song.get('Tags.Genre', '')))
                return tag.lower() in tags
    if 'contains' in cond:
        m = re.search(r'(?:user\s*1|user\s*2|genre)\s+contains\s+["\']?([^"\']+)', cond, re.I)
        if m:
            val = m.group(1).strip().lstrip('#').lower()
            if 'user 1' in cond or 'user1' in cond.replace(' ', ''):
                return val in (song.get('Tags.User1', '') or '').lower()
            if 'user 2' in cond or 'user2' in cond.replace(' ', ''):
                return val in (song.get('Tags.User2', '') or '').lower()
            if 'genre' in cond:
                return val in (song.get('Tags.Genre', '') or '').lower()
    if 'genre is' in cond or 'genre=' in cond:
        m = re.search(r'genre\s+(?:is|=)\s*["\']?#?([^"\'\s]+)', cond, re.I)
        if m:
            tag = m.group(1).strip().lstrip('#').lower()
            tags = set(t.lstrip('#').lower() for t in parse_tags_value(song.get('Tags.Genre', '')))
            return tag in tags
    return False


def _song_matches_filter(filter_text: str, song: dict) -> bool:
    """Sprawdza czy utwór pasuje do filtra VDJ (or/and)."""
    if not filter_text or not filter_text.strip():
        return False
    import re
    parts = re.split(r'\s+or\s+', filter_text.strip(), flags=re.IGNORECASE)
    for part in parts:
        and_parts = re.split(r'\s+and\s+', part.strip(), flags=re.IGNORECASE)
        if all(_eval_filter_condition(ap, song) for ap in and_parts if ap.strip()):
            return True
    return False


def _enrich_songs_with_lists(songs: list[dict]):
    """Dodaje do każdego utworu listę list/playlist i filter list, do których należy."""
    global _vdjfolders
    from vdjfolder import normalize_path
    from vdj_streaming import is_tidal_path, extract_tidal_id
    if not _vdjfolders:
        for s in songs:
            s['listsDisplay'] = ''
            s['lists'] = []
        return
    path_to_playlists = {}
    filter_folders = []
    import xml.etree.ElementTree as ET
    import re
    for rel_path, content in _vdjfolders.items():
        if _is_my_library_path(rel_path):
            continue
        name = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
        if not name:
            continue
        try:
            root = ET.fromstring(content)
            filt = root.get("filter") or root.get("Filter") or ""
            if not filt and root.tag == "FilterFolder":
                child = root.find("VirtualFolder") or root.find("folder")
                if child is not None:
                    filt = child.get("filter") or child.get("Filter") or ""
            if filt:
                filter_folders.append((name, filt))
            elif root.tag in ("VirtualFolder", "FilterFolder"):
                for song_elem in root.findall("song"):
                    p = (song_elem.get("path") or "").strip()
                    if p:
                        np = normalize_path(p)
                        if np:
                            path_to_playlists.setdefault(np, []).append(name)
                            # Tidal: baza może mieć td123, vdjfolder netsearch://td123 – dodaj alias
                            if is_tidal_path(p):
                                tid = extract_tidal_id(p)
                                if tid:
                                    for alias in (f"td{tid}", f"netsearch://td{tid}"):
                                        if alias != np:
                                            path_to_playlists.setdefault(alias, []).append(name)
        except ET.ParseError:
            pass
    for s in songs:
        path = str(s.get("FilePath", "") or s.get("path", "") or "").strip()
        np = normalize_path(path) if path else ""
        lists_set = set(path_to_playlists.get(np, []))
        for fname, filt in filter_folders:
            if _song_matches_filter(filt, s):
                lists_set.add(fname)
        s["lists"] = sorted(lists_set)
        s["listsDisplay"] = ", ".join(s["lists"][:5]) + (" …" if len(s["lists"]) > 5 else "")


def _is_vdj_cache_path(path: str) -> bool:
    """Czy ścieżka to plik cache VDJ (.vdjcache) – nie można odtworzyć w aplikacji."""
    return bool(path and str(path).strip().lower().endswith('.vdjcache'))


def _enrich_song_for_display(s: dict, vdj_cache_path: Optional[str] = None, skip_path_check: bool = False) -> dict:
    """Dodaje pathDisplay, pathStatus, isStreaming i isCache do rekordu.
    skip_path_check=True – pomija Path.exists() (szybsze przy wielu utworach, np. remiksy)."""
    from vdj_streaming import format_path_display, get_path_status
    from file_analyzer import is_streaming
    path = str(s.get('FilePath', '') or s.get('path', '') or '').strip()
    is_cache = _is_vdj_cache_path(path)
    s['isStreaming'] = is_streaming(path) or is_cache
    s['isCache'] = is_cache
    status = get_path_status(path, vdj_cache_path) if path else None
    if not path:
        s['pathDisplay'] = ''
        s['pathStatus'] = None
        s['fileMissing'] = False
    elif is_streaming(path) or is_cache:
        s['pathDisplay'] = format_path_display(path, status)
        s['pathStatus'] = status
        s['fileMissing'] = False
    else:
        if skip_path_check:
            s['pathDisplay'] = path
            s['pathStatus'] = None
            s['fileMissing'] = False
        else:
            exists = _path_exists_timeout(path) if path else False
            s['pathDisplay'] = path + (' (brak)' if not exists else '')
            s['pathStatus'] = 'offline' if exists else 'brak'
            s['fileMissing'] = not exists
    return s


@app.route('/api/search', methods=['POST'])
def api_search():
    """
    Wyszukiwanie i filtrowanie.
    Body: { query, tagFilters: { User1: [...], User2: [...] }, groupBy, limit, offset, vdjCachePath? }
    """
    global _songs
    _ensure_loaded()
    data = request.get_json() or {}
    query = (data.get('query') or '').strip().lower()
    tag_filters = data.get('tagFilters') or {}
    group_by = data.get('groupBy') or ''
    limit = min(int(data.get('limit', 500)), 2000)
    offset = int(data.get('offset', 0))
    vdj_cache_path = (data.get('vdjCachePath') or '').strip() or None
    sort_by = (data.get('sortBy') or '').strip()
    sort_dir = (data.get('sortDir') or 'asc').strip().lower()
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'asc'

    def _str(v):
        return str(v or '').strip().lower()

    indexed = list(enumerate(_songs))
    if query:
        indexed = [
            (i, s) for i, s in indexed
            if query in _str(s.get('Tags.Author'))
            or query in _str(s.get('Tags.Title'))
            or query in _str(s.get('Tags.Genre'))
            or query in _str(s.get('Tags.User1'))
            or query in _str(s.get('Tags.User2'))
            or query in _str(s.get('Tags.Album'))
        ]
    for field, tags in tag_filters.items():
        if not tags:
            continue
        prefix = f'Tags.{field}'
        tags_set = set(t.strip() for t in tags if t.strip())
        indexed = [
            (i, s) for i, s in indexed
            if tags_set & set(parse_tags_value(str(s.get(prefix, '') or '')))
        ]
    total = len(indexed)

    col_to_key = {
        'title': ('Tags.Title', str),
        'author': ('Tags.Author', str),
        'length': ('Infos.SongLength', lambda x: int(x) if x and str(x).isdigit() else 0),
        'bpm': ('Tags.Bpm', lambda x: 60 / float(x) if x and float(x) != 0 else 0),
        'key': ('Tags.Key', str),
        'rating': ('Tags.Stars', lambda x: int(x) if x and str(x).isdigit() else 0),
        'genre': ('Tags.Genre', str),
        'user1': ('Tags.User1', str),
        'user2': ('Tags.User2', str),
        'playcount': ('Infos.PlayCount', lambda x: int(x) if x and str(x).isdigit() else 0),
        'path': ('FilePath', str),
    }
    if sort_by and sort_by in col_to_key:
        key_name, conv = col_to_key[sort_by]
        rev = sort_dir == 'desc'
        def _sort_key(p):
            raw = p[1].get(key_name)
            s = str(raw or '').strip()
            if conv != str:
                try:
                    return conv(s) if s else 0
                except (ValueError, TypeError, ZeroDivisionError):
                    return 0
            return s.lower()
        indexed.sort(key=_sort_key, reverse=rev)

    page_slice = indexed[offset:offset + limit]
    page = [{'idx': i, **s} for i, s in page_slice]
    for s in page:
        _enrich_song_for_display(s, vdj_cache_path)

    # Dodaj informację o listach i filter list dla każdego utworu
    _enrich_songs_with_lists(page)

    groups = {}
    if group_by:
        key = f'Tags.{group_by}'
        for s in page:
            val = str(s.get(key, '') or '(brak)').strip()
            for t in parse_tags_value(val) if group_by in ('User1', 'User2', 'Genre') else [val]:
                k = t if t else '(brak)'
                if k not in groups:
                    groups[k] = []
                groups[k].append(s)

    return jsonify({
        'songs': page,
        'total': total,
        'offset': offset,
        'limit': limit,
        'groups': groups if group_by else None,
    })


@app.route('/api/tags', methods=['GET'])
def api_tags():
    """Lista tagów z liczbą wystąpień dla User1, User2 lub Genre."""
    global _songs
    _ensure_loaded()
    field = request.args.get('field', 'User1')
    if field not in ('User1', 'User2', 'Genre'):
        field = 'User1'
    counts = get_all_tags(_songs, field)
    items = [{'tag': k, 'count': v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return jsonify({'tags': items})


@app.route('/api/tags-all', methods=['GET'])
def api_tags_all():
    """Lista tagów z Genre, User1 i User2 jednocześnie."""
    global _songs
    _ensure_loaded()
    result = {}
    for field in ('Genre', 'User1', 'User2'):
        counts = get_all_tags(_songs, field)
        result[field] = [{'tag': k, 'count': v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return jsonify(result)


def _escape_xml_attr(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _update_vdjfolders_merge(selections: list, new_tag: str, target_field: str):
    """Aktualizuje vdjfoldery po scaleniu tagów."""
    global _vdjfolders
    import re
    for path, content in list(_vdjfolders.items()):
        m = re.search(r'filter="([^"]*)"', content)
        if not m:
            continue
        filt = m.group(1).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
        new_filt = update_filter_merge(filt, selections, new_tag, target_field)
        if new_filt != filt:
            old_full = m.group(0)
            new_full = f'filter="{_escape_xml_attr(new_filt)}"'
            _vdjfolders[path] = content.replace(old_full, new_full, 1)


def _update_vdjfolders_remove(field: str, tags: list):
    """Aktualizuje vdjfoldery po usunięciu tagów."""
    global _vdjfolders
    import re
    for path, content in list(_vdjfolders.items()):
        m = re.search(r'filter="([^"]*)"', content)
        if not m:
            continue
        filt = m.group(1).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
        new_filt = update_filter_remove(filt, field, tags)
        if new_filt != filt:
            old_full = m.group(0)
            new_full = f'filter="{_escape_xml_attr(new_filt)}"'
            _vdjfolders[path] = content.replace(old_full, new_full, 1)


@app.route('/api/tracks-by-tags', methods=['POST'])
def api_tracks_by_tags():
    """
    Zwraca utwory zawierające dowolny z podanych tagów.
    Body: { selections: [{field, tag}, ...] } – utwory z tagiem w danym polu (OR między selekcjami).
    """
    global _songs
    _ensure_loaded()
    data = request.get_json() or {}
    selections = data.get('selections') or []
    if not selections:
        return jsonify({'songs': [], 'total': 0})
    limit = min(int(data.get('limit', 500)), 1000)
    matched = set()
    for sel in selections:
        field = (sel.get('field') or 'User1').strip()
        tag = (sel.get('tag') or '').strip()
        if not tag or field not in ('User1', 'User2', 'Genre'):
            continue
        prefix = f'Tags.{field}'
        for i, s in enumerate(_songs):
            if tag in parse_tags_value(s.get(prefix, '')):
                matched.add(i)
    indices = sorted(matched)[:limit]
    page = []
    for i in indices:
        s = dict(_songs[i])
        s['idx'] = i
        page.append(s)
    _enrich_songs_with_lists(page)
    return jsonify({'songs': page, 'total': len(matched)})


@app.route('/api/merge-tags', methods=['POST'])
def api_merge_tags():
    """
    Scalanie tagów. Dwa tryby:
    - Jedno pole: { field, oldTags, newTag }
    - Między polami: { selections: [{field, tag}], newTag, targetField }
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    selections = data.get('selections')
    target_field = (data.get('targetField') or '').strip()

    if selections and isinstance(selections, list) and len(selections) > 0:
        sel = [(s.get('field'), s.get('tag')) for s in selections if s.get('field') and s.get('tag')]
        new_tag = (data.get('newTag') or '').strip()
        if not sel or not new_tag or not target_field:
            return jsonify({'error': 'Podaj selections, newTag i targetField'}), 400
        if target_field not in ('User1', 'User2', 'Genre'):
            return jsonify({'error': 'targetField musi być User1, User2 lub Genre'}), 400
        modified = merge_tags_across_fields(_songs, sel, new_tag, target_field)
        _update_vdjfolders_merge(sel, new_tag, target_field)
        return jsonify({'ok': True, 'modified': modified})
    else:
        field = data.get('field', 'User1')
        old_tags = [t.strip() for t in (data.get('oldTags') or []) if t.strip()]
        new_tag = (data.get('newTag') or '').strip()
        if not old_tags or not new_tag:
            return jsonify({'error': 'Podaj oldTags i newTag'}), 400
        if field not in ('User1', 'User2', 'Genre'):
            return jsonify({'error': 'field musi być User1, User2 lub Genre'}), 400
        modified = merge_tags_in_songs(_songs, field, old_tags, new_tag)
        sel = [(field, t) for t in old_tags]
        _update_vdjfolders_merge(sel, new_tag, field)
        return jsonify({'ok': True, 'modified': modified})


@app.route('/api/update-tags-selected', methods=['POST'])
def api_update_tags_selected():
    """
    Zamiana lub usunięcie tagów tylko dla zaznaczonych utworów.
    Body: { indices: [1,2,3], field: 'User1'|'User2'|'Genre', oldTags: ['LATA20'], newTag: 'LATA10' }
    Jeśli newTag jest puste – usuwa oldTags. W przeciwnym razie zamienia oldTags na newTag.
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    indices = [int(x) for x in (data.get('indices') or []) if isinstance(x, (int, str)) and str(x).isdigit()]
    indices = [i for i in indices if 0 <= i < len(_songs)]
    if not indices:
        return jsonify({'error': 'Podaj indices (lista indeksów utworów)'}), 400
    field = (data.get('field') or 'User1').strip()
    if field not in ('User1', 'User2', 'Genre'):
        return jsonify({'error': 'field musi być User1, User2 lub Genre'}), 400
    old_tags = [t.strip() for t in (data.get('oldTags') or []) if t.strip()]
    new_tag = (data.get('newTag') or '').strip()
    idx_set = set(indices)
    if new_tag:
        if old_tags:
            modified = merge_tags_in_songs_by_indices(_songs, idx_set, field, old_tags, new_tag)
            sel = [(field, t) for t in old_tags]
            _update_vdjfolders_merge(sel, new_tag, field)
        else:
            modified = 0
            for i in idx_set:
                if i < len(_songs):
                    val = _songs[i].get(f'Tags.{field}', '')
                    tags = parse_tags_value(val)
                    if new_tag not in tags:
                        tags.append(new_tag)
                        _songs[i][f'Tags.{field}'] = join_tags(tags)
                        modified += 1
    else:
        if not old_tags:
            return jsonify({'error': 'Podaj oldTags (do usunięcia)'}), 400
        modified = remove_tags_in_songs_by_indices(_songs, idx_set, field, old_tags)
        _update_vdjfolders_remove(field, old_tags)
    return jsonify({'ok': True, 'modified': modified})


@app.route('/api/tags-for-indices', methods=['POST'])
def api_tags_for_indices():
    """Zwraca tagi (Genre, User1, User2) dla podanych indeksów utworów."""
    global _songs
    _ensure_loaded()
    data = request.get_json() or {}
    indices = [int(x) for x in (data.get('indices') or []) if isinstance(x, (int, str)) and str(x).isdigit()]
    indices = [i for i in indices if 0 <= i < len(_songs)]
    result = []
    for i in indices:
        s = _songs[i]
        result.append({
            'idx': i,
            'Tags.Genre': s.get('Tags.Genre', ''),
            'Tags.User1': s.get('Tags.User1', ''),
            'Tags.User2': s.get('Tags.User2', ''),
        })
    return jsonify({'songs': result})


@app.route('/api/set-tags-selected', methods=['POST'])
def api_set_tags_selected():
    """
    Ustawia tagi dla zaznaczonych utworów.
    Body: { indices: [1,2,3], tags: { Genre: ['#A','#B'], User1: [...], User2: [...] } }
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    indices = [int(x) for x in (data.get('indices') or []) if isinstance(x, (int, str)) and str(x).isdigit()]
    indices = [i for i in indices if 0 <= i < len(_songs)]
    if not indices:
        return jsonify({'error': 'Podaj indices (lista indeksów utworów)'}), 400
    tags_by_field = data.get('tags') or {}
    modified = 0
    for i in indices:
        if i >= len(_songs):
            continue
        changed = False
        for field in ('Genre', 'User1', 'User2'):
            tag_list = [t.strip() for t in (tags_by_field.get(field) or []) if t and str(t).strip()]
            old_val = _songs[i].get(f'Tags.{field}', '')
            new_val = join_tags(tag_list)
            if old_val != new_val:
                _songs[i][f'Tags.{field}'] = new_val
                changed = True
        if changed:
            modified += 1
    return jsonify({'ok': True, 'modified': modified})


@app.route('/api/remove-tags', methods=['POST'])
def api_remove_tags():
    """
    Usuwa tagi z utworów (utwory pozostają).
    Body: { field: 'User1'|'User2'|'Genre', tags: ['#A','#B'] }
    """
    global _songs
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    field = data.get('field', 'User1')
    tags = [t.strip() for t in (data.get('tags') or []) if t.strip()]
    if not tags:
        return jsonify({'error': 'Podaj tagi do usunięcia'}), 400
    if field not in ('User1', 'User2', 'Genre'):
        return jsonify({'error': 'field musi być User1, User2 lub Genre'}), 400
    modified = remove_tags_in_songs(_songs, field, tags)
    _update_vdjfolders_remove(field, tags)
    return jsonify({'ok': True, 'modified': modified})


@app.route('/api/update-song', methods=['POST'])
def api_update_song():
    """Aktualizuje pojedynczy utwór (po FilePath)."""
    global _songs
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    path = data.get('FilePath', '')
    updates = data.get('updates', {})
    if not path or not updates:
        return jsonify({'error': 'Brak FilePath lub updates'}), 400
    for s in _songs:
        if s.get('FilePath') == path:
            for k, v in updates.items():
                s[k] = v
            return jsonify({'ok': True})
    return jsonify({'error': 'Nie znaleziono utworu'}), 404


@app.route('/api/import-rb', methods=['POST'])
def api_import_rb():
    """
    Import z Rekordbox (rbxml.xml).
    Body: path (ścieżka) lub plik w FormData.
    """
    global _songs, _version, _db_path, _vdjfolders, _source, _unified
    _clear_undo_stack()
    rb_content = None
    if request.files:
        for key in request.files:
            for f in request.files.getlist(key):
                fn = getattr(f, 'filename', '') or ''
                if fn.lower().endswith('.xml') or 'rbxml' in fn.lower():
                    rb_content = f.read()
                    break
            if rb_content:
                break
    if not rb_content and request.get_json():
        data = request.get_json()
        path = (data.get('path') or '').strip()
        if path:
            p = Path(path).expanduser().resolve()
            if p.exists():
                rb_content = p.read_bytes()
    if not rb_content:
        return jsonify({'error': 'Brak pliku rbxml.xml – wybierz plik lub podaj ścieżkę'}), 400
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as f:
            f.write(rb_content)
            tmp = Path(f.name)
        try:
            db = load_rb_xml(tmp)
            _songs = unified_to_vdj_songs(db)
            _unified = db
            _version = ''
            _db_path = None
            _vdjfolders = {}
            _extra_files = {}
            _source = 'rb'
            return jsonify({
                'ok': True,
                'count': len(_songs),
                'playlists': len(db.playlists),
                'source': 'rb',
            })
        finally:
            tmp.unlink(missing_ok=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export-rb', methods=['GET'])
def api_export_rb():
    """
    Eksport do Rekordbox – pobranie pliku ZIP (RB czyta ZIP przy Restore).
    ZIP zawiera rekordbox.xml w formacie DJ_PLAYLISTS.
    Query: pathFrom, pathTo – zamiana prefixu ścieżki (np. gdy pliki na innym dysku).
    """
    r = _require_export_license()
    if r:
        return r
    global _songs, _unified, _vdjfolders, _source
    _ensure_loaded()
    try:
        db = vdj_songs_to_unified(_songs)
        if _unified and _unified.playlists:
            db.playlists = _unified.playlists
        elif _source == 'vdj' and _vdjfolders:
            valid = {normalize_path(s.get('FilePath')) for s in _songs if s.get('FilePath')}
            db.playlists = filter_lists_to_regular_playlists(_vdjfolders, _songs, valid)
        path_replace = None
        path_from = (request.args.get('pathFrom') or '').strip().rstrip('/')
        path_to = (request.args.get('pathTo') or '').strip().rstrip('/')
        if path_from and path_to and path_from != path_to:
            path_replace = {path_from: path_to}
        xml_bytes = generate_rb_xml(db, path_replace)
        from flask import Response
        return Response(
            xml_bytes,
            mimetype='application/xml',
            headers={'Content-Disposition': 'attachment; filename="rekordbox.xml"'},
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export-rb-playlists', methods=['POST'])
def api_export_rb_playlists():
    """
    Eksport samych playlist do RB – gdy utwory są już w kolekcji (dodane przez File → Add).
    Wymaga: VDJ załadowany + plik XML z eksportu RB (File → Export).
    POST: rbXml=plik XML (eksport RB po dodaniu folderu), pathFrom, pathTo opcjonalnie.
    Query: preview=1 – zwraca JSON ze statystykami (bez pobierania).
    """
    r = _require_export_license()
    if r:
        return r
    global _songs, _unified, _vdjfolders, _source
    _ensure_loaded()
    rb_content = None
    if request.files:
        for key in request.files:
            for f in request.files.getlist(key):
                fn = getattr(f, 'filename', '') or ''
                if fn.lower().endswith('.xml') or 'rb' in fn.lower():
                    rb_content = f.read()
                    break
            if rb_content:
                break
    if not rb_content:
        return jsonify({'error': 'Podaj plik XML z eksportu RB (File → Export). Najpierw dodaj folder do RB (File → Add), potem wyeksportuj.'}), 400
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as f:
            f.write(rb_content)
            tmp = Path(f.name)
        try:
            rb_db = load_rb_xml(tmp)
            path_to_rb_id = {}
            for t in rb_db.tracks:
                if t.source_id and t.path:
                    path_to_rb_id[normalize_path(t.path)] = t.source_id

            db = vdj_songs_to_unified(_songs)
            if _unified and _unified.playlists:
                playlists = _unified.playlists
            elif _source == 'vdj' and _vdjfolders:
                valid = {normalize_path(s.get('FilePath')) for s in _songs if s.get('FilePath')}
                playlists = filter_lists_to_regular_playlists(_vdjfolders, _songs, valid)
            else:
                playlists = db.playlists or []

            path_replace = None
            path_from = (request.form.get('pathFrom') or request.args.get('pathFrom') or '').strip().rstrip('/')
            path_to = (request.form.get('pathTo') or request.args.get('pathTo') or '').strip().rstrip('/')
            if path_from and path_to and path_from != path_to:
                path_replace = {path_from: path_to}

            # Statystyki dopasowania (do podglądu)
            from vdjfolder import normalize_path as _norm

            def vdj_to_rb_key(vdj_path: str) -> str:
                np = _norm(vdj_path)
                if path_replace:
                    for old_prefix, new_prefix in path_replace.items():
                        no = _norm(old_prefix)
                        if np.startswith(no):
                            np = _norm(new_prefix.rstrip("/") + np[len(no):])
                            break
                return np

            stats = {
                "rb_tracks": len(path_to_rb_id),
                "playlists_count": 0,
                "playlists": [],
                "warnings": [],
                "tidal_count": 0,
            }
            if not playlists:
                stats["warnings"].append(
                    "Brak playlist w backupie VDJ. Załaduj ZIP z plikami .vdjfolder (Filter Folders) lub folder z plikami .vdjfolder."
                )
            def count_playlists(pls: list) -> int:
                n = 0
                for pl in pls:
                    if pl.is_folder:
                        n += count_playlists(pl.children)
                    else:
                        n += 1
                return n

            def collect_stats(pls: list):
                for pl in pls:
                    if pl.is_folder:
                        collect_stats(pl.children)
                        continue
                    matched = 0
                    for path in pl.track_ids:
                        if path_to_rb_id.get(vdj_to_rb_key(path)):
                            matched += 1
                    stats["playlists"].append({"name": pl.name, "matched": matched, "total": len(pl.track_ids)})
                    if matched == 0 and len(pl.track_ids) > 0:
                        stats["warnings"].append(
                            f"Playlist „{pl.name}”: 0/{len(pl.track_ids)} dopasowanych – ścieżki VDJ ≠ RB. Spróbuj pathFrom/pathTo."
                        )

            stats["playlists_count"] = count_playlists(playlists)
            collect_stats(playlists)

            # RB wymaga COLLECTION z utworami – Key w playlistach odnosi się do TrackID
            track_by_id = {t.source_id: t for t in rb_db.tracks if t.source_id}
            path_to_track = {normalize_path(t.path): t for t in db.tracks}

            def collect_refs(pls):
                refs = set()
                for pl in pls:
                    if pl.is_folder:
                        refs |= collect_refs(pl.children)
                    else:
                        for path in pl.track_ids:
                            tid = path_to_rb_id.get(vdj_to_rb_key(path))
                            if tid:
                                refs.add(tid)
                return refs

            referenced_ids = collect_refs(playlists)
            tracks_for_collection = [track_by_id[tid] for tid in referenced_ids if tid in track_by_id]

            # Tidal – utwory z VDJ bez dopasowania w RB: dodaj do COLLECTION z konwersją td→tidal:tracks
            tidal_added = 0
            try:
                from vdj_streaming import is_tidal_path
                import dataclasses
                next_tidal_id = 500000000
                seen_tidal = set()
                for pl in playlists:
                    if pl.is_folder:
                        continue
                    for path in pl.track_ids:
                        key = vdj_to_rb_key(path)
                        if key in path_to_rb_id:
                            continue
                        if not is_tidal_path(path):
                            continue
                        if key in seen_tidal:
                            continue
                        seen_tidal.add(key)
                        t = path_to_track.get(normalize_path(path))
                        if not t:
                            continue
                        tid = str(next_tidal_id)
                        next_tidal_id += 1
                        path_to_rb_id[key] = tid
                        t_copy = dataclasses.replace(t, source_id=tid)
                        tracks_for_collection.append(t_copy)
                        tidal_added += 1
                stats["tidal_count"] = tidal_added
                if tidal_added:
                    stats["warnings"].append(
                        f"Dodano {tidal_added} utworów Tidal. W RB zaloguj się do Tidal (Media Browser), aby je odtworzyć."
                    )
            except ImportError:
                pass

            if request.args.get("preview") == "1":
                return jsonify(stats)

            xml_bytes = generate_rb_playlists_only_xml(
                playlists, path_to_rb_id, path_replace, tracks_for_collection=tracks_for_collection
            )
            from flask import Response
            resp = Response(
                xml_bytes,
                mimetype='application/xml',
                headers={'Content-Disposition': 'attachment; filename="rekordbox-playlists.xml"'},
            )
            # Nagłówek ze statystykami (frontend może wyświetlić)
            resp.headers["X-Playlists-Count"] = str(stats["playlists_count"])
            resp.headers["X-Matched-Summary"] = "; ".join(
                f"{p['name']}: {p['matched']}/{p['total']}" for p in stats["playlists"][:5]
            )
            return resp
        finally:
            tmp.unlink(missing_ok=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _common_dir_prefix(paths: list) -> str:
    """Wspólny prefiks katalogów – np. /Users/test/Music i /Users/test/Desktop → /Users/test/."""
    valid = []
    for p in paths:
        fp = (p or '').strip().replace('\\', '/')
        if not fp or fp.startswith(('td', 'netsearch:', 'soundcloud:', 'beatport:', 'deezer:')):
            continue
        if fp.lower().endswith('.vdjcache'):
            continue
        if '/' in fp:
            parent = fp.rsplit('/', 1)[0] + '/'
        else:
            continue
        valid.append(parent)
    if not valid:
        return ''
    common = valid[0]
    for p in valid[1:]:
        i = 0
        mn = min(len(common), len(p))
        while i < mn and common[i] == p[i]:
            i += 1
        common = common[:i]
        if common and not common.endswith('/'):
            common = common.rsplit('/', 1)[0] + '/'
    return common


@app.route('/api/serato-drive-root-suggestion', methods=['GET'])
def api_serato_drive_root_suggestion():
    """
    Sugeruje root dysku na podstawie ścieżek w bazie.
    Serato „main drive” na macOS = root / (gdy _Serato_ jest w ~/Music/).
    Zewnętrzny dysk = /Volumes/Nazwa/.
    """
    global _songs
    _ensure_loaded()
    paths = [(s.get('FilePath') or '').strip() for s in _songs]
    for fp in paths:
        if not fp:
            continue
        fp = fp.replace('\\', '/')
        if len(fp) >= 2 and fp[1] == ':':
            return jsonify({'path': fp[:2] + '/'})
        if fp.startswith('/Volumes/'):
            parts = fp.split('/')
            if len(parts) >= 4:
                return jsonify({'path': '/Volumes/' + parts[2] + '/'})
    # Ścieżki pod /Users/ = dysk główny Mac → Serato używa root "/" (ścieżki: Users/test/Music/...)
    for fp in paths:
        fp = (fp or '').replace('\\', '/')
        if fp.startswith('/Users/') or (fp.startswith('/') and not fp.startswith('/Volumes/')):
            return jsonify({'path': '/'})
    prefix = _common_dir_prefix(paths)
    return jsonify({'path': prefix if prefix else '/'})


@app.route('/api/export-serato', methods=['GET'])
def api_export_serato():
    """
    Eksport do Serato DJ – ZIP z _Serato_/database V2 i Subcrates/*.crate.
    Query: driveRoot – root dysku (np. C:\\, /Users/xyz/, /Volumes/Drive/).
    Serato wymaga ścieżek względnych – bez driveRoot może wystąpić błąd sync.
    """
    r = _require_export_license()
    if r:
        return r
    global _songs, _unified, _vdjfolders, _source
    _ensure_loaded()
    try:
        drive_root = (request.args.get('driveRoot') or request.args.get('pathFrom') or '').strip()
        db_content = save_serato_database_v2(_songs, drive_root or None)
        def _flat_playlists(pls, out=None):
            out = out or []
            for pl in pls:
                if pl.track_ids and not pl.is_folder:
                    out.append(pl)
                if pl.children:
                    _flat_playlists(pl.children, out)
            return out

        playlists = []
        if _unified and _unified.playlists:
            playlists = _flat_playlists(_unified.playlists)
        if _vdjfolders:
            valid = {normalize_path(s.get("FilePath")) for s in _songs if s.get("FilePath")}
            vdj_pls = filter_lists_to_regular_playlists(_vdjfolders, _songs, valid)
            seen = {pl.name.lower() for pl in playlists}
            for pl in vdj_pls:
                if pl.name.lower() not in seen:
                    playlists.append(pl)
                    seen.add(pl.name.lower())
        from io import BytesIO
        from flask import Response
        z = BytesIO()
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("_Serato_/database V2", db_content)
            for pl in playlists:
                if pl.track_ids:
                    crate_content = save_serato_crate(pl.track_ids, pl.name, drive_root or None)
                    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in pl.name)[:64]
                    zf.writestr(f"_Serato_/Subcrates/{safe_name}.crate", crate_content)
        return Response(
            z.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": 'attachment; filename="serato-export.zip"'},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/export-djxml', methods=['GET'])
def api_export_djxml():
    """
    Eksport do DJXML (otwarty format – Mixo, djxml.com).
    Query: pathFrom, pathTo – zamiana prefixu ścieżki.
    """
    r = _require_export_license()
    if r:
        return r
    global _songs, _unified, _vdjfolders, _source
    _ensure_loaded()
    try:
        db = vdj_songs_to_unified(_songs)
        if _unified and _unified.playlists:
            db.playlists = _unified.playlists
        elif _source == 'vdj' and _vdjfolders:
            valid = {normalize_path(s.get('FilePath')) for s in _songs if s.get('FilePath')}
            db.playlists = filter_lists_to_regular_playlists(_vdjfolders, _songs, valid)
        path_replace = None
        path_from = (request.args.get('pathFrom') or '').strip().rstrip('/')
        path_to = (request.args.get('pathTo') or '').strip().rstrip('/')
        if path_from and path_to and path_from != path_to:
            path_replace = {path_from: path_to}
        xml_bytes = generate_djxml(db, path_replace)
        from flask import Response
        return Response(
            xml_bytes,
            mimetype='application/xml',
            headers={'Content-Disposition': 'attachment; filename="vdj-export.djxml"'},
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export-rb-restore', methods=['GET', 'POST'])
def api_export_rb_restore():
    """
    Eksport do Rekordbox Restore Library – ZIP z master.db.
    Użycie: File → Library → Restore Library w RB.
    POST: template=plik (backup RB ZIP), pathFrom, pathTo – zamiana prefixu.
    GET: template=ścieżka (legacy), pathFrom, pathTo.
    """
    r = _require_export_license()
    if r:
        return r
    global _songs, _unified, _vdjfolders, _source
    _ensure_loaded()
    template_path = None
    tmp_template = None
    try:
        db = vdj_songs_to_unified(_songs)
        if _unified and _unified.playlists:
            db.playlists = _unified.playlists
        elif _source == 'vdj' and _vdjfolders:
            valid = {normalize_path(s.get('FilePath')) for s in _songs if s.get('FilePath')}
            db.playlists = filter_lists_to_regular_playlists(_vdjfolders, _songs, valid)
        path_replace = None
        use_template = True
        if request.method == 'POST':
            path_from = (request.form.get('pathFrom') or '').strip().rstrip('/')
            path_to = (request.form.get('pathTo') or '').strip().rstrip('/')
            use_template = request.form.get('useTemplate', '1') != '0'
            f = request.files.get('template')
            if use_template and f and f.filename:
                import tempfile
                ext = '.zip' if (f.filename or '').lower().endswith('.zip') else '.db'
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmp.write(f.read())
                tmp.close()
                tmp_template = Path(tmp.name)
                template_path = str(tmp_template)
            else:
                template_path = None
                if use_template:
                    raise ValueError('Wybierz plik backupu RB (Szablon RB: Przeglądaj)')
        else:
            path_from = (request.args.get('pathFrom') or '').strip().rstrip('/')
            path_to = (request.args.get('pathTo') or '').strip().rstrip('/')
            template_path = (request.args.get('template') or '').strip() or None
            use_template = request.args.get('useTemplate', '1') != '0'
        if path_from and path_to and path_from != path_to:
            path_replace = {path_from: path_to}

        # RB wyświetla metadane Z PLIKÓW (ID3), nie z bazy – zapis tagów PRZED Restore jest kluczowy
        def _resolve(t):
            p = t.path
            if path_replace:
                for old, new in path_replace.items():
                    if p.startswith(old):
                        return new + p[len(old):]
            return p
        written, _, _err, _ = write_tags_batch(db.tracks, path_resolver=_resolve)

        if use_template and not template_path:
            raise ValueError('Podaj szablon: wybierz plik (Przeglądaj). Lub odznacz „Użyj szablonu" aby generować od zera.')
        master_db_bytes = unified_to_master_db(db, path_replace, template_path=template_path if (use_template and template_path) else None)
        buf = BytesIO()
        template_is_zip = template_path and str(template_path).lower().endswith('.zip')
        if use_template and template_is_zip and Path(template_path).exists():
            # Zachowaj strukturę backupu RB (master.db, rekordbox3.settings, xml...) – RB może jej wymagać.
            # Pomijamy share/ (ANLZ) – analizy odnoszą się do starych ContentID, nasza baza ma nowe.
            with zipfile.ZipFile(template_path, 'r') as src:
                with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for name in src.namelist():
                        if name.startswith('share/'):
                            continue  # ANLZ – nie pasują do naszych ContentID
                        if name.endswith('master.db') or name.split('/')[-1] == 'master.db':
                            zf.writestr(name, master_db_bytes)
                        else:
                            zf.writestr(name, src.read(name))
        else:
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('master.db', master_db_bytes)
        buf.seek(0)
        from flask import Response
        fn = 'vdj-export-rekordbox-restore.zip'
        return Response(
            buf.getvalue(),
            mimetype='application/zip',
            headers={'Content-Disposition': f'attachment; filename="{fn}"'},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if tmp_template and tmp_template.exists():
            try:
                tmp_template.unlink()
            except Exception:
                pass


@app.route('/api/export-rb-sync', methods=['POST'])
def api_export_rb_sync():
    """
    Sync bezpośrednio do folderu Rekordbox (jak Lexicon).
    ZAMKNIJ Rekordbox przed sync! Zapisuje master.db do ~/Library/Pioneer/rekordbox (Mac).
    POST: template=plik, rbFolder=ścieżka (opcjonalnie), pathFrom, pathTo.
    """
    r = _require_export_license()
    if r:
        return r
    global _songs, _unified, _vdjfolders, _source
    _ensure_loaded()
    import platform
    import shutil
    from datetime import datetime

    rb_folder = (request.form.get('rbFolder') or '').strip()
    if not rb_folder:
        if platform.system() == 'Darwin':
            rb_folder = str(Path.home() / 'Library' / 'Pioneer' / 'rekordbox')
        else:
            rb_folder = str(Path.home() / 'AppData' / 'Roaming' / 'Pioneer' / 'rekordbox')

    rb_path = Path(rb_folder).expanduser().resolve()
    master_db = rb_path / 'master.db'
    if not rb_path.exists():
        return jsonify({
            'error': f'Folder RB nie istnieje: {rb_path}. Uruchom Rekordbox raz – folder tworzy się przy pierwszym uruchomieniu. Lub podaj ścieżkę w polu „Folder RB".'
        }), 400

    use_template = request.form.get('useTemplate', '1') != '0'
    f = request.files.get('template')
    if use_template and (not f or not f.filename):
        return jsonify({'error': 'Wybierz plik backupu RB (Szablon) lub odznacz „Użyj szablonu RB"'}), 400

    tmp_template = None
    try:
        if use_template and f and f.filename:
            import tempfile
            ext = '.zip' if f.filename.lower().endswith('.zip') else '.db'
            tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            tmp.write(f.read())
            tmp.close()
            tmp_template = Path(tmp.name)

        db = vdj_songs_to_unified(_songs)
        if _unified and _unified.playlists:
            db.playlists = _unified.playlists
        elif _source == 'vdj' and _vdjfolders:
            valid = {normalize_path(s.get('FilePath')) for s in _songs if s.get('FilePath')}
            db.playlists = filter_lists_to_regular_playlists(_vdjfolders, _songs, valid)

        path_from = (request.form.get('pathFrom') or '').strip().rstrip('/')
        path_to = (request.form.get('pathTo') or '').strip().rstrip('/')
        path_replace = {path_from: path_to} if path_from and path_to and path_from != path_to else None
        skip_missing = request.form.get('skipMissing') == '1'
        skip_my_tags = request.form.get('skipMyTags') == '1'

        def _resolve_path(p: str):
            if not path_replace:
                return p
            for old, new in path_replace.items():
                if p.startswith(old):
                    return new + p[len(old):]
            return p

        skipped = 0
        if skip_missing:
            valid_norm = {
                normalize_path(t.path)
                for t in db.tracks
                if Path(_resolve_path(t.path)).exists()
            }
            before = len(db.tracks)
            db.tracks = [t for t in db.tracks if normalize_path(t.path) in valid_norm]
            skipped = before - len(db.tracks)

            def _filter_playlist(pl):
                pl.track_ids = [tid for tid in pl.track_ids if normalize_path(tid) in valid_norm]
                for ch in pl.children:
                    _filter_playlist(ch)

            for pl in db.playlists:
                _filter_playlist(pl)

        # RB wyświetla metadane z plików (ID3) – zapis tagów przed sync
        def _resolve_sync(t):
            return _resolve_path(t.path)
        write_tags_batch(db.tracks, path_resolver=_resolve_sync)

        master_db_bytes = unified_to_master_db(
            db, path_replace,
            template_path=str(tmp_template) if tmp_template else None,
            skip_my_tags=skip_my_tags,
        )

        # Backup
        if master_db.exists():
            backup = rb_path / f'master.db.editor_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            shutil.copy2(master_db, backup)

        # Usuń pliki WAL SQLite – stare -wal/-shm powodują, że RB ładuje starą zawartość
        for suf in ('-wal', '-shm'):
            wal = rb_path / f'master.db{suf}'
            if wal.exists():
                try:
                    wal.unlink()
                except Exception:
                    pass

        # Usuń automatyczne backupy RB – RB przy starcie może „odtworzyć” starą bazę z backupu
        for suf in ('backup.db', 'backup1.db', 'backup2.db', 'backup3.db'):
            bkp = rb_path / f'master.{suf}'
            if bkp.exists():
                try:
                    bkp.unlink()
                except Exception:
                    pass

        # Usuń rekordbox.xml – RB może go używać jako cache
        for xml_name in ('rekordbox.xml', 'masterPlaylists6.xml'):
            xml_path = rb_path / xml_name
            if xml_path.exists():
                try:
                    xml_path.unlink()
                except Exception:
                    pass

        with open(master_db, 'wb') as f:
            f.write(master_db_bytes)
            f.flush()
            try:
                import os
                os.fsync(f.fileno())
            except Exception:
                pass

        # Weryfikacja na KOPII – nie otwieramy live master.db (blokowałoby Lexicon/RB)
        verify_count = None
        try:
            import tempfile
            from pyrekordbox.db6 import Rekordbox6Database
            from sqlalchemy import text
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
                tf.write(master_db_bytes)
                tmp_path = tf.name
            try:
                rb = Rekordbox6Database(tmp_path, unlock=True)
                r = rb.session.execute(text('SELECT COUNT(*) FROM djmdContent'))
                verify_count = r.scalar()
                rb.close()
                rb.engine.dispose()
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

        msg = f'Sync zapisany ({verify_count} utworów w bazie). Uruchom Rekordbox.'
        if verify_count is None:
            msg = 'Sync zapisany. Uruchom Rekordbox.'
        if skip_missing and skipped > 0:
            msg = f'Sync zapisany ({verify_count} utworów, pominięto {skipped} z brakującymi plikami). Uruchom Rekordbox.'
        elif verify_count is not None and verify_count != len(db.tracks) and not skip_missing:
            msg += f' Uwaga: baza ma {verify_count} utworów, VDJ ma {len(db.tracks)} – sprawdź po uruchomieniu RB.'
        return jsonify({'ok': True, 'path': str(master_db), 'message': msg, 'verifyCount': verify_count})
    except Exception as e:
        import traceback
        traceback.print_exc()
        err = str(e)
        hint = ""
        if "Permission" in err or "permission" in err or "being used" in err or "in use" in err or "locked" in err.lower():
            hint = " Zamknij Rekordbox całkowicie (także z paska zadań)."
        elif "Brak sqlcipher3" in err or "sqlcipher" in err.lower():
            hint = " Użyj szablonu RB (zaznacz 'Użyj szablonu RB' i wybierz backup)."
        elif "nie istnieje" in err.lower():
            hint = " Upewnij się, że Rekordbox był uruchamiany – folder tworzy się przy pierwszym uruchomieniu."
        return jsonify({'error': err + hint}), 500
    finally:
        if tmp_template and tmp_template.exists():
            try:
                tmp_template.unlink()
            except Exception:
                pass


@app.route('/api/write-tags', methods=['POST'])
def api_write_tags():
    """
    Zapisuje tagi (Title, Artist, Album, Genre) do plików audio (ID3).
    Zalecane gdy VDJ czyta z RB – VDJ bierze metadane z plików, nie z master.db.
    Body: { pathFrom?, pathTo? } – opcjonalna zamiana ścieżki (gdy pliki przeniesione).
    """
    r = _require_export_license()
    if r:
        return r
    global _songs
    _ensure_loaded()
    data = request.get_json() or {}
    path_from = (data.get('pathFrom') or '').strip().rstrip('/')
    path_to = (data.get('pathTo') or '').strip().rstrip('/')
    path_replace = {path_from: path_to} if path_from and path_to and path_from != path_to else None

    def resolve_path(track):
        p = track.path
        if path_replace:
            for old, new in path_replace.items():
                if p.startswith(old):
                    return new + p[len(old):]
        return p

    db = vdj_songs_to_unified(_songs)
    ok, skipped, err, errors = write_tags_batch(db.tracks, path_resolver=resolve_path if path_replace else None)
    # Grupuj błędy po typie (np. "Plik nie istnieje" vs "Format nieobsługiwany")
    error_summary = {}
    for e in errors:
        parts = e.split(': ', 2)  # "file.mp3: Komunikat: szczegóły"
        typ = parts[1] if len(parts) >= 2 else e
        error_summary[typ] = error_summary.get(typ, 0) + 1
    return jsonify({
        'ok': True,
        'written': ok,
        'skipped': skipped,
        'failed': err,
        'errors': errors[:50],
        'errorSummary': error_summary,
    })


def _get_problematic_missing(vdj_cache_path=None):
    """Zwraca listę brakujących plików (ścieżki w bazie, plik nie istnieje)."""
    global _songs
    from file_analyzer import is_streaming
    missing = []
    for i, s in enumerate(_songs):
        path = s.get('FilePath', '') or ''
        if not path or is_streaming(path):
            continue
        p = Path(path)
        if not p.exists():
            rec = {'idx': i, 'path': path, 'author': s.get('Tags.Author', ''), 'title': s.get('Tags.Title', '')}
            _enrich_song_for_display(rec, vdj_cache_path)
            missing.append(rec)
    return missing


def _is_my_library_path(rel_path: str) -> bool:
    """Czy rel_path należy do dodatku My Library (VDJ) – pomijamy jego zawartość."""
    if not rel_path:
        return False
    p = rel_path.replace("\\", "/").lower()
    return "my library" in p


def _is_folder_container(root) -> bool:
    """Czy vdjfolder to folder-kontener (taneczne, gatunki) – zawiera tylko podfoldery, nie listę utworów."""
    if root is None:
        return False
    if root.tag == "FilterFolder":
        return False  # FilterFolder to zawsze filter list
    return root.find("folder") is not None or root.find("VirtualFolder") is not None


def _get_problematic_empty_playlists():
    """Zwraca listę pustych list odtwarzania (vdjfolder bez utworów z bazy)."""
    global _songs, _vdjfolders
    from vdjfolder import normalize_path
    valid_paths = {normalize_path(s.get('FilePath')) for s in _songs if s.get('FilePath')}
    _EMPTY_SKIP_NAMES = frozenset({
        "database", "livelists", "artist", "album", "title", "key", "bpm", "genre", "hashtags",
        "year", "added", "rating", "popular", "played", "edits", "extras", "hawaje", "audio",
        "video", "karaoke", "my edits", "cu cache", "tools", "player", "my library",
        "energy", "gatunki", "kreatywne listy", "taneczne listy", "show", "roczniki", "treningi",
        "wesele 6.12.25", "wesela", "osiemanstki", "bridgerton", "stare listy", "sety", "sety stare",
        "sylwester", "święta", "biesiada", "ideas", "filters",
    })
    empty_playlists = []
    if _vdjfolders:
        import xml.etree.ElementTree as ET
        for rel_path, content in _vdjfolders.items():
            if _is_my_library_path(rel_path):
                continue
            name = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
            if not name:
                continue
            if name.lower() in _EMPTY_SKIP_NAMES:
                continue
            try:
                root = ET.fromstring(content)
                if root.tag != "VirtualFolder":
                    continue
                if root.get("filter"):
                    continue
                if root.find("folder") is not None or root.find("VirtualFolder") is not None:
                    continue
                count = 0
                for song in root.findall("song"):
                    p = (song.get("path") or "").strip()
                    if p and not p.startswith("netsearch:") and not (p.startswith("td") and ":" not in p):
                        if normalize_path(p) in valid_paths:
                            count += 1
                if count == 0:
                    empty_playlists.append(name)
            except ET.ParseError:
                pass
    return empty_playlists


def _parse_bitrate_from_db(val):
    """Parsuje bitrate (kbps) ze stringa z bazy: '128', '128.0', '128.0kbps', '128kbps'."""
    if not val or not isinstance(val, str):
        return None
    m = re.search(r'(\d+(?:\.\d+)?)', val.strip())
    if m:
        try:
            return int(float(m.group(1)))
        except (TypeError, ValueError):
            pass
    return None


def _get_problematic_low_bitrate(bitrate_max, vdj_cache_path=None):
    """Zwraca listę utworów z bitrate poniżej progu."""
    global _songs
    from file_analyzer import is_streaming, _get_bitrate
    low_bitrate = []
    for i, s in enumerate(_songs):
        path = s.get('FilePath', '') or ''
        if not path or is_streaming(path):
            continue
        p = Path(path)
        br = _get_bitrate(path) if p.exists() else None
        if br is None:
            br = _parse_bitrate_from_db(s.get('Infos.Bitrate') or s.get('Tags.Bitrate') or '')
        if br is not None and br < bitrate_max:
            rec = {'idx': i, 'path': path, 'author': s.get('Tags.Author', ''), 'title': s.get('Tags.Title', ''), 'bitrate': br}
            _enrich_song_for_display(rec, vdj_cache_path)
            low_bitrate.append(rec)
    return low_bitrate


@app.route('/api/relocate-scan', methods=['POST'])
def api_relocate_scan():
    """
    Skanuje foldery w poszukiwaniu brakujących plików.
    POST body: { searchPaths: ["/path/to/folder1", "/path/to/folder2", ...] }
    Dla każdego brakującego rekordu szuka pliku o tej samej nazwie (stem+ext) w searchPaths.
    Zwraca: { candidates: [{ idx, oldPath, newPath, author, title }, ...], notFound: [...] }
    """
    global _songs
    _ensure_loaded()
    from file_analyzer import is_streaming
    data = request.get_json() or {}
    search_paths = [p.strip() for p in data.get('searchPaths', []) if isinstance(p, str) and p.strip()]
    if not search_paths:
        return jsonify({'error': 'Podaj co najmniej jedną ścieżkę do przeszukania'}), 400

    missing = _get_problematic_missing(None)
    if not missing:
        return jsonify({'candidates': [], 'notFound': [], 'message': 'Brak brakujących plików'})

    # Zbuduj indeks plików: stem_lower -> [full_path, ...]
    from collections import defaultdict
    file_index = defaultdict(list)
    for sp in search_paths:
        p = Path(sp)
        if not p.is_dir():
            continue
        for f in p.rglob('*'):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
                stem = f.stem.lower()
                file_index[stem].append(str(f.resolve()))

    candidates = []
    not_found = []
    for m in missing:
        idx = m.get('idx')
        old_path = m.get('path', '') or m.get('FilePath', '')
        if not old_path or idx is None:
            continue
        old_p = Path(old_path)
        stem = old_p.stem.lower()
        ext = old_p.suffix.lower()
        found_paths = file_index.get(stem, [])
        # Preferuj dokładne dopasowanie rozszerzenia
        matches = [fp for fp in found_paths if Path(fp).suffix.lower() == ext]
        if not matches:
            matches = found_paths
        if matches:
            candidates.append({
                'idx': idx,
                'oldPath': old_path,
                'newPath': matches[0],
                'author': _songs[idx].get('Tags.Author', ''),
                'title': _songs[idx].get('Tags.Title', ''),
                'alternatives': matches[1:5],
            })
        else:
            not_found.append({'idx': idx, 'oldPath': old_path, 'author': m.get('author', ''), 'title': m.get('title', '')})

    return jsonify({'candidates': candidates, 'notFound': not_found})


@app.route('/api/relocate-apply', methods=['POST'])
def api_relocate_apply():
    """
    Aktualizuje ścieżki w bazie i vdjfolderach.
    POST body: { updates: [{ idx: 5, newPath: "/new/path/song.mp3" }, ...] }
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    from vdjfolder import normalize_path
    data = request.get_json() or {}
    updates = data.get('updates', [])
    if not updates:
        return jsonify({'error': 'Brak aktualizacji'}), 400

    path_map = {}  # np_old -> new_path
    for u in updates:
        idx = u.get('idx')
        new_path = (u.get('newPath') or '').strip()
        if idx is None or not new_path:
            continue
        if not (0 <= idx < len(_songs)):
            continue
        old_path = _songs[idx].get('FilePath', '') or ''
        if not old_path:
            continue
        np_old = normalize_path(old_path)
        np_new = normalize_path(new_path)
        if np_old != np_new:
            path_map[np_old] = new_path
            _songs[idx]['FilePath'] = new_path

    if _vdjfolders and path_map:
        import xml.etree.ElementTree as ET
        new_vdjfolders = {}
        for rel_path, content in _vdjfolders.items():
            try:
                root = ET.fromstring(content)
                if root.tag != "VirtualFolder":
                    new_vdjfolders[rel_path] = content
                    continue
                changed = False
                for song in root.findall("song"):
                    p = song.get("path", "")
                    np = normalize_path(p)
                    if np in path_map:
                        song.set("path", path_map[np])
                        changed = True
                if changed:
                    out = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
                    new_vdjfolders[rel_path] = out
                else:
                    new_vdjfolders[rel_path] = content
            except ET.ParseError:
                new_vdjfolders[rel_path] = content
        _vdjfolders = new_vdjfolders

    return jsonify({'ok': True, 'updated': len(path_map), 'count': len(_songs)})


@app.route('/api/problematic-missing', methods=['GET'])
def api_problematic_missing():
    """Brakujące pliki – rekordy w bazie, plik nie istnieje na dysku."""
    global _songs, _source
    _ensure_loaded()
    vdj_cache_path = (request.args.get('vdjCachePath') or '').strip() or None
    missing = _get_problematic_missing(vdj_cache_path)
    return jsonify({'missing': missing, 'summary': {'missing_count': len(missing)}})


@app.route('/api/problematic-empty-playlists', methods=['GET'])
def api_problematic_empty_playlists():
    """Puste listy – vdjfolder bez utworów z bazy."""
    global _vdjfolders, _source
    _ensure_loaded()
    empty_playlists = _get_problematic_empty_playlists()
    return jsonify({'empty_playlists': empty_playlists, 'summary': {'empty_playlists_count': len(empty_playlists)}})


@app.route('/api/playlists', methods=['GET'])
def api_playlists():
    """Lista playlist i filter list (vdjfolder). Pomija My Library, folder-kontenery (taneczne, gatunki)."""
    global _vdjfolders
    _ensure_loaded()
    items = []
    if _vdjfolders:
        import xml.etree.ElementTree as ET
        for rel_path, content in _vdjfolders.items():
            if _is_my_library_path(rel_path):
                continue
            name = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
            if not name:
                continue
            try:
                root = ET.fromstring(content)
                if _is_folder_container(root):
                    continue
                filt = root.get("filter") or root.get("Filter") or ""
                if not filt and root.tag == "FilterFolder":
                    child = root.find("VirtualFolder") or root.find("folder")
                    if child is not None:
                        filt = child.get("filter") or child.get("Filter") or ""
                items.append({
                    "name": name,
                    "relPath": rel_path,
                    "type": "filter" if filt else "playlist",
                })
            except ET.ParseError:
                pass
    return jsonify({'playlists': sorted(items, key=lambda x: x['name'].lower())})


@app.route('/api/playlist-tracks', methods=['GET'])
def api_playlist_tracks():
    """Utwory w danej playliście lub filter liście."""
    global _songs, _vdjfolders
    _ensure_loaded()
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Podaj name'}), 400
    from vdjfolder import normalize_path
    from vdj_streaming import is_tidal_path, extract_tidal_id
    path_to_idx = {}
    for i, s in enumerate(_songs):
        p = s.get('FilePath', '') or ''
        if p:
            np = normalize_path(p)
            path_to_idx[np] = i
            # Tidal: vdjfolder może mieć td123 lub netsearch://td123 – dodaj oba warianty
            if is_tidal_path(p):
                tid = extract_tidal_id(p)
                if tid:
                    for alias in (f"td{tid}", f"netsearch://td{tid}"):
                        if alias not in path_to_idx:
                            path_to_idx[alias] = i
    tracks = []
    rel_path_found = None
    is_filter_list = False
    if _vdjfolders:
        import xml.etree.ElementTree as ET
        for rel_path, content in _vdjfolders.items():
            n = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
            if n != name:
                continue
            rel_path_found = rel_path
            try:
                root = ET.fromstring(content)
                filt = root.get("filter") or root.get("Filter") or ""
                if not filt and root.tag == "FilterFolder":
                    child = root.find("VirtualFolder") or root.find("folder")
                    if child is not None:
                        filt = child.get("filter") or child.get("Filter") or ""
                is_filter_list = bool(filt)
                if filt:
                    for i, s in enumerate(_songs):
                        if _song_matches_filter(filt, s):
                            rec = {'idx': i, **s}
                            _enrich_song_for_display(rec, None)
                            _enrich_songs_with_lists([rec])
                            tracks.append(rec)
                else:
                    for song_elem in root.findall("song"):
                        p = (song_elem.get("path") or "").strip()
                        if p:
                            np = normalize_path(p)
                            idx = path_to_idx.get(np)
                            if idx is not None:
                                s = _songs[idx]
                                rec = {'idx': idx, **s}
                                _enrich_song_for_display(rec, None)
                                _enrich_songs_with_lists([rec])
                                tracks.append(rec)
            except ET.ParseError:
                pass
            break
    if rel_path_found is None:
        return jsonify({'error': 'Nie znaleziono playlisty', 'tracks': []}), 404
    return jsonify({'name': name, 'relPath': rel_path_found, 'tracks': tracks, 'filter': is_filter_list})


def _extract_filter_tags(filter_text: str) -> list[tuple[str, str]]:
    """Wyciąga (field, tag) z filtra, np. 'User 1 has tag X' -> [('User1','X')]."""
    import re
    out = []
    for field, pattern in [
        ('User1', r'user\s*1\s+has\s+tag\s+["\']?([^"\'\s]+)'),
        ('User2', r'user\s*2\s+has\s+tag\s+["\']?([^"\'\s]+)'),
        ('Genre', r'genre\s+has\s+tag\s+["\']?([^"\'\s]+)'),
        ('Genre', r'genre\s+is\s+["\']?#?([^"\'\s]+)'),
    ]:
        for m in re.finditer(pattern, filter_text, re.I):
            tag = m.group(1).strip().lstrip('#')
            if (field, tag) not in out:
                out.append((field, tag))
    return out


@app.route('/api/playlist-remove-from', methods=['POST'])
def api_playlist_remove_from():
    """
    Usuwa utwór z playlisty (nie z bazy, nie z dysku).
    - Dla playlisty (VirtualFolder): usuwa element <song> z vdjfolder.
    - Dla filter listy: usuwa tag z utworu (utwór przestaje pasować do filtra).
    Body: { playlistName, indices: [1,2,3] }
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    name = (data.get('playlistName') or data.get('playlist') or '').strip()
    indices = [int(x) for x in (data.get('indices') or []) if isinstance(x, (int, str)) and str(x).isdigit()]
    if not name or not indices:
        return jsonify({'error': 'Podaj playlistName i indices'}), 400
    from vdjfolder import normalize_path
    rel_path_found = None
    content = None
    for rel_path, c in _vdjfolders.items():
        n = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
        if n == name:
            rel_path_found = rel_path
            content = c
            break
    if not rel_path_found:
        return jsonify({'error': 'Nie znaleziono playlisty'}), 404
    import xml.etree.ElementTree as ET
    import re
    root = ET.fromstring(content)
    filt = root.get("filter") or root.get("Filter") or ""
    modified = 0
    if filt:
        filter_tags = _extract_filter_tags(filt)
        if not filter_tags:
            return jsonify({'error': 'Nie można usunąć z filter listy (brak tagów w filtrze)'}), 400
        for idx in indices:
            if 0 <= idx < len(_songs):
                s = _songs[idx]
                for field, tag in filter_tags:
                    tags = parse_tags_value(s.get(f'Tags.{field}', ''))
                    tags_normalized = [t.lstrip('#').lower() for t in tags]
                    if tag.lower() in tags_normalized:
                        to_remove = [t for t in tags if t.lstrip('#').lower() == tag.lower()]
                        if to_remove:
                            remove_tags_in_songs_by_indices(_songs, {idx}, field, to_remove)
                            _update_vdjfolders_remove(field, to_remove)
                            modified += 1
                        break
    else:
        paths_to_remove = set()
        for idx in indices:
            if 0 <= idx < len(_songs):
                p = _songs[idx].get('FilePath', '') or ''
                if p:
                    paths_to_remove.add(normalize_path(p))
        if not paths_to_remove:
            return jsonify({'ok': True, 'modified': 0})
        root = ET.fromstring(content)
        for song_elem in root.findall("song"):
            p = (song_elem.get("path") or "").strip()
            if p and normalize_path(p) in paths_to_remove:
                root.remove(song_elem)
                modified += 1
        new_content = ET.tostring(root, encoding='unicode', default_namespace='')
        _vdjfolders[rel_path_found] = new_content
    return jsonify({'ok': True, 'modified': modified})


@app.route('/api/playlist-replace-tidal', methods=['POST'])
def api_playlist_replace_tidal():
    """
    Zamienia utwory Tidal na lokalne w playliście (tylko zwykłe listy, nie filter).
    Body: { playlistName, relPath, replacements: [{ tidalPath, acceptedIdx }] }
    tidalPath: ścieżka Tidal (td123, netsearch://td123), acceptedIdx: indeks w _songs pliku lokalnego.
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    name = (data.get('playlistName') or data.get('playlist') or '').strip()
    rel_path = (data.get('relPath') or '').strip()
    replacements = data.get('replacements') or []
    if not name or not replacements:
        return jsonify({'error': 'Podaj playlistName i replacements'}), 400
    from vdjfolder import normalize_path
    content = None
    for rp, c in _vdjfolders.items():
        n = rp.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
        if n == name:
            content = c
            if not rel_path:
                rel_path = rp
            break
    if not content:
        return jsonify({'error': 'Nie znaleziono playlisty'}), 404
    import xml.etree.ElementTree as ET
    root = ET.fromstring(content)
    if root.get("filter") or root.get("Filter"):
        return jsonify({'error': 'Zamiana Tidal→lokalne działa tylko dla zwykłych list (nie filter)'}), 400
    # tidal_path -> [local_path, ...] – jeden Tidal może być zamieniony na wiele plików
    from file_analyzer import is_streaming
    path_map = {}  # normalized tidal path -> list of local paths
    for r in replacements:
        tidal_path = (r.get('tidalPath') or '').strip()
        if not tidal_path:
            continue
        indices = r.get('acceptedIndices') or []
        if r.get('acceptedIdx') is not None:
            indices = [r.get('acceptedIdx')]
        valid_paths = []
        for ai in indices:
            try:
                ai = int(ai)
            except (TypeError, ValueError):
                continue
            if 0 <= ai < len(_songs):
                lp = _songs[ai].get('FilePath', '') or ''
                if lp and not is_streaming(lp):
                    valid_paths.append(lp)
        if valid_paths:
            path_map[normalize_path(tidal_path)] = valid_paths
            path_map[tidal_path] = valid_paths
            if tidal_path.startswith("netsearch://td"):
                path_map[normalize_path("td" + tidal_path[len("netsearch://td"):])] = valid_paths
            elif tidal_path.startswith("td") and ":" not in tidal_path:
                path_map[normalize_path("netsearch://" + tidal_path)] = valid_paths
    if not path_map:
        return jsonify({'ok': True, 'modified': 0})
    modified = 0
    songs = list(root.findall("song"))
    for song_elem in songs:
        p = (song_elem.get("path") or "").strip()
        if not p:
            continue
        np = normalize_path(p)
        local_paths = path_map.get(np) or path_map.get(p)
        if not local_paths:
            continue
        if len(local_paths) == 1:
            song_elem.set("path", local_paths[0])
            modified += 1
        else:
            idx = list(root).index(song_elem)
            root.remove(song_elem)
            for lp in local_paths:
                new_elem = ET.Element("song", path=lp)
                root.insert(idx, new_elem)
                idx += 1
            modified += len(local_paths)
    out = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode', default_namespace='')
    _vdjfolders[rel_path] = out
    return jsonify({'ok': True, 'modified': modified})


@app.route('/api/playlist-offline-to-tidal-substitutes', methods=['POST'])
def api_playlist_offline_to_tidal_substitutes():
    """
    Dla utworów lokalnych w playliście wyszukuje zamienniki na Tidal (Offline → Online).
    Body: { playlistName }
    Zwraca: { matches: [{ trackIdx, idx, author, title, tidalCandidates: [{ id, title, artist }] }], error?: string }
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    data = request.get_json() or {}
    name = (data.get('playlistName') or data.get('playlist') or '').strip()
    if not name:
        return jsonify({'error': 'Podaj playlistName', 'matches': []}), 400
    from file_analyzer import is_streaming
    from vdjfolder import normalize_path
    import xml.etree.ElementTree as ET
    path_to_idx = {}
    for i, s in enumerate(_songs):
        p = s.get('FilePath', '') or ''
        if p:
            np = normalize_path(p)
            path_to_idx[np] = i
    local_tracks = []  # (order_in_playlist, idx, author, title)
    rel_path_found = None
    if _vdjfolders:
        for rel_path, content in _vdjfolders.items():
            n = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
            if n != name:
                continue
            rel_path_found = rel_path
            try:
                root = ET.fromstring(content)
                if root.get("filter") or root.get("Filter"):
                    return jsonify({'error': 'Działa tylko dla zwykłych list (nie filter)', 'matches': []}), 400
                for pos, song_elem in enumerate(root.findall("song")):
                    p = (song_elem.get("path") or "").strip()
                    if not p:
                        continue
                    np = normalize_path(p)
                    idx = path_to_idx.get(np)
                    if idx is None and p.startswith("td") and ":" not in p:
                        idx = path_to_idx.get("netsearch://" + p)
                    if idx is None:
                        continue
                    s = _songs[idx]
                    if is_streaming(s.get('FilePath', '') or ''):
                        continue
                    author = (s.get('Tags.Author') or s.get('Tags.Artist') or '').strip()
                    title = (s.get('Tags.Title') or '').strip()
                    local_tracks.append((pos, idx, author, title))
            except ET.ParseError:
                pass
            break
    if rel_path_found is None:
        return jsonify({'error': 'Nie znaleziono playlisty', 'matches': []}), 404
    matches = []
    for pos, idx, author, title in local_tracks:
        query = f"{author} {title}".strip() or " "
        tidal_list, err = _tidal_search_tracks(query, limit=5)
        matches.append({
            'trackIdx': pos,
            'idx': idx,
            'author': author,
            'title': title,
            'tidalCandidates': tidal_list,
            'searchError': err,
        })
    return jsonify({'matches': matches})


@app.route('/api/playlist-create-from-tidal', methods=['POST'])
def api_playlist_create_from_tidal():
    """
    Tworzy nową playlistę z utworów Tidal (lista online). Offline → Online.
    Body: { name, items: [{ trackIdx, tidalId }] } lub { name, tidalIds: ["123","456"] }
    Kolejność: items według trackIdx, lub tidalIds w podanej kolejności.
    """
    global _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    name = (data.get('name') or '').strip() or 'Offline na Online'
    items = data.get('items') or []
    tidal_ids = data.get('tidalIds') or []
    if tidal_ids:
        paths = [f"netsearch://td{tid}" for tid in tidal_ids if tid and str(tid).strip().isdigit()]
    else:
        sorted_items = sorted([x for x in items if x.get('tidalId')], key=lambda x: int(x.get('trackIdx', 0)))
        paths = [f"netsearch://td{str(x.get('tidalId')).strip()}" for x in sorted_items if str(x.get('tidalId', '')).strip().isdigit()]
    if not paths:
        return jsonify({'error': 'Brak poprawnych tidalId', 'name': None}), 400
    from vdjfolder import create_vdjfolder_playlist
    rel_path = _vdjfolders_create_new_path(name)
    content = create_vdjfolder_playlist(paths, name)
    _vdjfolders[rel_path] = content
    return jsonify({'name': name, 'relPath': rel_path, 'count': len(paths)})


@app.route('/api/delete-files', methods=['POST'])
def api_delete_files():
    """
    Usuwa pliki fizycznie z dysku. Tylko dla plików lokalnych (nie Tidal/streaming).
    Ścieżka musi być w katalogu nadrzędnym plików z załadowanej bazy (ochrona path traversal).
    Body: { paths: ["/path/to/file.mp3", ...] }
    """
    global _songs
    _ensure_loaded()
    from file_analyzer import is_streaming
    data = request.get_json() or {}
    paths = [p for p in (data.get('paths') or []) if isinstance(p, str) and p.strip()]
    deleted = 0
    errors = []
    for path in paths:
        if is_streaming(path):
            errors.append(f"Pomijam (streaming): {path[:60]}…")
            continue
        p = Path(path)
        if not _is_path_safe(p):
            errors.append(f"Ścieżka niedozwolona (poza katalogami bazy): {path[:50]}…")
            continue
        if p.exists():
            try:
                p.unlink()
                deleted += 1
            except Exception as e:
                errors.append(f"Błąd {path[:50]}…: {e}")
        else:
            errors.append(f"Nie istnieje: {path[:50]}…")
    return jsonify({'ok': True, 'deleted': deleted, 'errors': errors})


@app.route('/api/problematic-low-bitrate', methods=['GET'])
def api_problematic_low_bitrate():
    """Niski bitrate – utwory poniżej progu kbps. GET ?bitrateMax=128"""
    global _songs, _source
    _ensure_loaded()
    bitrate_max = int(request.args.get('bitrateMax', 128))
    vdj_cache_path = (request.args.get('vdjCachePath') or '').strip() or None
    low_bitrate = _get_problematic_low_bitrate(bitrate_max, vdj_cache_path)
    return jsonify({'low_bitrate': low_bitrate, 'summary': {'low_bitrate_count': len(low_bitrate)}})


def _todo_collect():
    """Zbiera listy utworów: cache VDJ i z brakującym plikiem. Zwraca (cache_list, missing_list)."""
    global _songs
    from file_analyzer import is_streaming
    cache_list = []
    missing_list = []
    for i, s in enumerate(_songs):
        path = (s.get('FilePath') or s.get('path') or '').strip()
        if not path:
            continue
        author = (s.get('Tags.Author') or s.get('Tags.Artist') or '').strip()
        title = (s.get('Tags.Title') or '').strip()
        rec = {'idx': i, 'author': author, 'title': title, 'path': path}
        if _is_vdj_cache_path(path):
            cache_list.append(rec)
            continue
        if is_streaming(path):
            continue
        if not _path_exists_timeout(path):
            missing_list.append(rec)
    return cache_list, missing_list


@app.route('/api/todo', methods=['GET'])
def api_todo():
    """
    Lista rzeczy do zrobienia: liczba utworów z cache VDJ (.vdjcache) i utworów z brakującym plikiem.
    Zwraca: { cacheCount, missingCount }.
    """
    global _songs
    _ensure_loaded()
    cache_list, missing_list = _todo_collect()
    return jsonify({'cacheCount': len(cache_list), 'missingCount': len(missing_list)})


@app.route('/api/todo-save', methods=['POST'])
def api_todo_save():
    """
    Zapisuje listę rzeczy do zrobienia do pliku Markdown w podanym katalogu.
    POST body: { "directory": "ścieżka/do/katalogu" } – jeśli puste, używany jest katalog nadrzędny edytora (VoteBattle).
    Plik: RZECZY_DO_ZROBIENIA.md
    """
    global _songs
    _ensure_loaded()
    data = request.get_json() or {}
    directory = (data.get('directory') or '').strip()
    if not directory:
        directory = str(Path(__file__).resolve().parent.parent)
    try:
        dir_path = Path(directory).expanduser().resolve()
        if not dir_path.is_dir():
            return jsonify({'error': 'Podana ścieżka nie jest katalogiem', 'path': directory}), 400
        home = Path.home()
        app_parent = Path(__file__).resolve().parent.parent
        try:
            dir_path.relative_to(home)
        except ValueError:
            try:
                dir_path.relative_to(app_parent)
            except ValueError:
                return jsonify({'error': 'Ścieżka musi być w katalogu domowym lub w katalogu projektu', 'path': directory}), 403
        cache_list, missing_list = _todo_collect()
        lines = [
            '# Rzeczy do zrobienia',
            '',
            'Wygenerowano przez Edytor bazy VDJ.',
            '',
            '## Utwory z cache VDJ (.vdjcache)',
            '',
            f'Liczba: {len(cache_list)}',
            '',
        ]
        for r in cache_list:
            lines.append(f"- **{r['author']} – {r['title']}** (idx: {r['idx']})")
            lines.append(f"  - `{r['path']}`")
            lines.append('')
        lines.extend([
            '## Utwory z brakującym plikiem',
            '',
            f'Liczba: {len(missing_list)}',
            '',
        ])
        for r in missing_list:
            lines.append(f"- **{r['author']} – {r['title']}** (idx: {r['idx']})")
            lines.append(f"  - `{r['path']}`")
            lines.append('')
        out_path = dir_path / 'RZECZY_DO_ZROBIENIA.md'
        out_path.write_text('\n'.join(lines), encoding='utf-8')
        return jsonify({'ok': True, 'path': str(out_path), 'cacheCount': len(cache_list), 'missingCount': len(missing_list)})
    except OSError as e:
        return jsonify({'error': f'Nie można zapisać pliku: {e}', 'path': directory}), 500


@app.route('/api/play-count-list', methods=['GET'])
def api_play_count_list():
    """
    Lista utworów posortowana po Play Count (od najczęściej do najrzadziej granego).
    GET ?filter=all|never|lessThan&lessThan=10&limit=2000&offset=0&tagFilters=...&sortBy=...&sortDir=asc|desc
    tagFilters: JSON np. {"Genre":["tag1"],"User1":[]} – utwór musi mieć którykolwiek z tagów w danym polu.
    sortBy: title|author|length|bpm|key|rating|genre|user1|user2|playcount|path (domyślnie playcount).
    """
    global _songs
    _ensure_loaded()
    filter_type = (request.args.get('filter') or 'all').strip().lower()
    if filter_type not in ('all', 'never', 'lessthan'):
        filter_type = 'all'
    try:
        less_than = max(0, int(request.args.get('lessThan', 1)))
    except (ValueError, TypeError):
        less_than = 1
    limit = min(int(request.args.get('limit', 2000)), 5000)
    offset = int(request.args.get('offset', 0))
    vdj_cache_path = (request.args.get('vdjCachePath') or '').strip() or None
    tag_filters = {}
    try:
        tf_raw = request.args.get('tagFilters') or '{}'
        if tf_raw:
            tag_filters = json.loads(tf_raw)
    except (ValueError, TypeError):
        pass
    sort_by = (request.args.get('sortBy') or 'playcount').strip().lower()
    sort_dir = (request.args.get('sortDir') or 'desc').strip().lower()
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'

    def _play_count_val(s):
        raw = s.get('Infos.PlayCount') or s.get('PlayCount') or ''
        try:
            return int(raw) if raw and str(raw).strip().isdigit() else 0
        except (ValueError, TypeError):
            return 0

    indexed = [(i, s, _play_count_val(s)) for i, s in enumerate(_songs)]
    if filter_type == 'never':
        indexed = [(i, s, pc) for i, s, pc in indexed if pc == 0]
    elif filter_type == 'lessthan':
        indexed = [(i, s, pc) for i, s, pc in indexed if pc < less_than]
    for field, tags in tag_filters.items():
        if not tags or field not in ('Genre', 'User1', 'User2'):
            continue
        key = f'Tags.{field}'
        tags_set = set(t.strip().lower().lstrip('#') for t in tags if t and str(t).strip())
        if not tags_set:
            continue
        indexed = [(i, s, pc) for i, s, pc in indexed if tags_set & set(t.lower().lstrip('#') for t in parse_tags_value(str(s.get(key, '') or '')))]
    col_to_key = {
        'title': ('Tags.Title', str),
        'author': ('Tags.Author', str),
        'length': ('Infos.SongLength', lambda x: int(x) if x and str(x).isdigit() else 0),
        'bpm': ('Tags.Bpm', lambda x: 60 / float(x) if x and float(x) != 0 else 0),
        'key': ('Tags.Key', str),
        'rating': ('Tags.Stars', lambda x: int(x) if x and str(x).isdigit() else 0),
        'genre': ('Tags.Genre', str),
        'user1': ('Tags.User1', str),
        'user2': ('Tags.User2', str),
        'playcount': ('Infos.PlayCount', lambda x: int(x) if x and str(x).isdigit() else 0),
        'path': ('FilePath', str),
    }
    if sort_by in col_to_key:
        key_name, conv = col_to_key[sort_by]
        rev = sort_dir == 'desc'
        def _sort_key(item):
            i, s, pc = item
            raw = s.get(key_name)
            s_val = str(raw or '').strip()
            if conv != str:
                try:
                    return conv(s_val) if s_val else (0 if key_name != 'Tags.Bpm' else 0)
                except (ValueError, TypeError, ZeroDivisionError):
                    return 0
            return s_val.lower()
        indexed.sort(key=_sort_key, reverse=rev)
    else:
        indexed.sort(key=lambda x: (x[2], -x[0]), reverse=True)
    total = len(indexed)
    page_slice = indexed[offset:offset + limit]
    page = [{**dict(s), 'idx': i} for i, s, _ in page_slice]
    for s in page:
        _enrich_song_for_display(s, vdj_cache_path)
    _enrich_songs_with_lists(page)
    return jsonify({'songs': page, 'total': total, 'offset': offset, 'limit': limit})


TIDAL_HEADERS = {
    "User-Agent": "VirtualDJ-Editor/1.0",
    "x-tidal-token": "gsFXkJqGrUNoYMQPZe4k3WKwijnrp8iGSwn3bApe",
}


def _check_tidal_track_available(track_id: str) -> bool:
    """
    Sprawdza, czy utwór o danym ID jest nadal dostępny na Tidal.
    Używa nieoficjalnego API – może wymagać dostępu/limitów.
    Zwraca True jeśli dostępny (200), False jeśli niedostępny (404) lub błąd.
    """
    if not track_id or not track_id.isdigit():
        return False
    try:
        import urllib.request
        import urllib.error
        url = f"https://api.tidal.com/v1/tracks/{track_id}?countryCode=PL"
        req = urllib.request.Request(url, headers=TIDAL_HEADERS)
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return e.code != 404  # 404 = niedostępny; 401/500 = zakładamy dostępny (unika fałszywych alarmów)
    except Exception:
        return False


def _tidal_search_tracks(query: str, limit: int = 5) -> tuple[list, Optional[str]]:
    """
    Szuka utworów na Tidal po zapytaniu (artist + title).
    Zwraca (listę {id, title, artist}, błąd lub None).
    """
    if not query or not query.strip():
        return [], None
    try:
        import urllib.request
        import urllib.error
        import urllib.parse
        q = urllib.parse.quote(query.strip())
        url = f"https://api.tidal.com/v1/search/tracks?query={q}&limit={limit}&countryCode=PL"
        req = urllib.request.Request(url, headers=TIDAL_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        items = data.get("items") or []
        out = []
        for t in items:
            aid = t.get("id")
            if not aid:
                continue
            artist = ""
            if "artist" in t:
                artist = t["artist"].get("name", "") if isinstance(t["artist"], dict) else str(t["artist"])
            out.append({"id": str(aid), "title": t.get("title", ""), "artist": artist})
        return out, None
    except urllib.error.HTTPError as e:
        return [], f"Tidal API HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return [], f"Brak połączenia z Tidal: {e.reason}"
    except Exception as e:
        return [], f"Tidal API: {type(e).__name__}: {e}"


@app.route('/api/tidal-search', methods=['GET'])
def api_tidal_search():
    """
    Szuka utworów na Tidal. GET ?q=artist+title
    Zwraca: { tracks: [...], error?: string }
    """
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"tracks": []})
    tracks, err = _tidal_search_tracks(q, limit=5)
    out = {"tracks": tracks}
    if err:
        out["error"] = err
    return jsonify(out)


@app.route('/api/replace-with-tidal', methods=['POST'])
def api_replace_with_tidal():
    """
    Zastępuje ścieżkę utworu wersją Tidal.
    POST body: { idx: 123, tidalId: "252147049" }
    """
    global _songs
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    idx = data.get("idx")
    tidal_id = (data.get("tidalId") or "").strip()
    if idx is None or not tidal_id or not tidal_id.isdigit():
        return jsonify({"error": "Wymagane idx i tidalId"}), 400
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return jsonify({"error": "Nieprawidłowy idx"}), 400
    if idx < 0 or idx >= len(_songs):
        return jsonify({"error": "Indeks poza zakresem"}), 404
    new_path = f"td{tidal_id}"
    _songs[idx]["FilePath"] = new_path
    return jsonify({"ok": True, "idx": idx, "newPath": new_path})


@app.route('/api/remove-songs', methods=['POST'])
def api_remove_songs():
    """
    Usuwa utwory z bazy. POST body: { indices: [1, 2, 3] }
    Również usuwa wpisy tych ścieżek z wszystkich plików .vdjfolder (playlisty/filtry),
    żeby po zapisie backupu VDJ nie pokazywał setek „brakujących plików” z list.
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    indices = sorted(set(int(i) for i in (data.get("indices") or []) if isinstance(i, (int, str)) and str(i).isdigit()), reverse=True)
    from vdjfolder import normalize_path, remove_paths_from_vdjfolder_content
    paths_to_remove = set()
    for i in indices:
        if 0 <= i < len(_songs):
            p = (_songs[i].get("FilePath") or "").strip()
            if p:
                paths_to_remove.add(normalize_path(p))
    removed = 0
    for i in indices:
        if 0 <= i < len(_songs):
            _songs.pop(i)
            removed += 1
    vdjfolders_refs_removed = 0
    if _vdjfolders and paths_to_remove:
        new_vdjfolders = {}
        for rel_path, content in _vdjfolders.items():
            new_content, n = remove_paths_from_vdjfolder_content(content, paths_to_remove)
            if n:
                vdjfolders_refs_removed += n
                new_vdjfolders[rel_path] = new_content
            else:
                new_vdjfolders[rel_path] = content
        _vdjfolders.clear()
        _vdjfolders.update(new_vdjfolders)
    return jsonify({"ok": True, "removed": removed, "count": len(_songs), "vdjfolders_refs_removed": vdjfolders_refs_removed})


@app.route('/api/tidal-track-list', methods=['GET'])
def api_tidal_track_list():
    """
    Zwraca listę utworów Tidal w bazie (bez sprawdzania dostępności).
    GET – zwraca { tracks: [{ idx, tidalId, author, title }, ...] }.
    """
    global _songs
    _ensure_loaded()
    from vdj_streaming import is_tidal_path, extract_tidal_id

    tracks = []
    for i, s in enumerate(_songs):
        path = s.get('FilePath', '') or ''
        if not is_tidal_path(path):
            continue
        tid = extract_tidal_id(path)
        if not tid:
            continue
        tracks.append({
            'idx': i,
            'tidalId': tid,
            'author': s.get('Tags.Author', ''),
            'title': s.get('Tags.Title', ''),
        })
    return jsonify({'tracks': tracks, 'count': len(tracks)})


@app.route('/api/tidal-check-one', methods=['GET'])
def api_tidal_check_one():
    """
    Sprawdza dostępność jednego utworu Tidal.
    GET ?tidalId=123 – zwraca { available: true|false }.
    """
    tidal_id = (request.args.get('tidalId') or '').strip()
    if not tidal_id or not tidal_id.isdigit():
        return jsonify({'error': 'Wymagany tidalId', 'available': None}), 400
    available = _check_tidal_track_available(tidal_id)
    return jsonify({'tidalId': tidal_id, 'available': available})


@app.route('/api/tidal-unavailable', methods=['GET'])
def api_tidal_unavailable():
    """
    Sprawdza, które utwory Tidal w bazie są niedostępne (usunięte ze streamingu).
    GET – zwraca listę { idx, path, author, title, tidalId }.
    Uwaga: wymaga połączenia z internetem, sprawdza każdy utwór osobno.
    Dla wielu utworów lepiej użyć tidal-track-list + tidal-check-one (inkrementalnie).
    """
    global _songs
    _ensure_loaded()
    from vdj_streaming import is_tidal_path, extract_tidal_id

    unavailable = []
    tidal_count = 0
    for i, s in enumerate(_songs):
        path = s.get('FilePath', '') or ''
        if not is_tidal_path(path):
            continue
        tidal_count += 1
        tid = extract_tidal_id(path)
        if not tid:
            continue
        if not _check_tidal_track_available(tid):
            unavailable.append({
                'idx': i,
                'path': path,
                'author': s.get('Tags.Author', ''),
                'title': s.get('Tags.Title', ''),
                'tidalId': tid,
            })
    return jsonify({
        'unavailable': unavailable,
        'tidal_count': tidal_count,
        'unavailable_count': len(unavailable),
    })


@app.route('/api/tidal-auth-status', methods=['GET'])
def api_tidal_auth_status():
    """Zwraca czy użytkownik jest połączony z Tidal (OAuth)."""
    try:
        from tidal_auth import get_access_token
        token = get_access_token()
        return jsonify({'connected': bool(token)})
    except ImportError:
        return jsonify({'connected': False})


@app.route('/api/tidal-credentials-info', methods=['GET'])
def api_tidal_credentials_info():
    """Zwraca info o konfiguracji kluczy Tidal (do wyświetlenia w UI)."""
    try:
        from tidal_auth import has_tidal_credentials
        has = has_tidal_credentials()
        cred_path = str(Path.home() / ".config" / "njr" / "tidal-credentials.json")
        return jsonify({
            'configured': has,
            'hint': 'Utwórz aplikację na developer.tidal.com, pobierz client_id i client_secret, zapisz w ' + cred_path + ' jako {"client_id":"...","client_secret":"..."}',
        })
    except ImportError:
        return jsonify({'configured': False, 'hint': 'Moduł tidal_auth niedostępny'})


# Tidal OAuth – stan oczekujących autoryzacji (state -> code_verifier)
_tidal_pending_auth: dict[str, str] = {}


@app.route('/api/tidal-auth-url', methods=['GET'])
def api_tidal_auth_url():
    """
    Zwraca URL do logowania Tidal (Authorization Code + PKCE).
    User otwiera URL w przeglądarce, loguje się, callback zapisze token.
    """
    try:
        from tidal_auth import get_authorize_url
        base = request.url_root.rstrip('/')
        redirect_uri = base + '/tidal-callback'
        url, state, verifier, err = get_authorize_url(redirect_uri)
        if err:
            return jsonify({'error': err}), 400
        _tidal_pending_auth[state] = verifier
        return jsonify({'url': url, 'state': state})
    except ImportError:
        return jsonify({'error': 'Moduł tidal_auth niedostępny'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/tidal-callback')
def tidal_callback():
    """
    Callback OAuth – Tidal przekierowuje tutaj po logowaniu.
    Wymienia code na token i przekierowuje do aplikacji.
    """
    code = request.args.get('code', '').strip()
    state = request.args.get('state', '').strip()
    error = request.args.get('error', '').strip()
    if error:
        return f'<html><body style="font-family:sans-serif;padding:20px;"><h2>Błąd Tidal</h2><p>{error}</p><p><a href="/">Wróć do aplikacji</a></p></body></html>', 400
    if not code or not state:
        return '<html><body style="font-family:sans-serif;padding:20px;"><h2>Brak kodu</h2><p>Nie otrzymano kodu autoryzacji.</p><p><a href="/">Wróć do aplikacji</a></p></body></html>', 400
    verifier = _tidal_pending_auth.pop(state, None)
    if not verifier:
        return '<html><body style="font-family:sans-serif;padding:20px;"><h2>Nieznany state</h2><p>Sesja wygasła. Kliknij „Połącz z Tidal” ponownie.</p><p><a href="/">Wróć do aplikacji</a></p></body></html>', 400
    try:
        from tidal_auth import exchange_code_for_token
        base = request.url_root.rstrip('/')
        redirect_uri = base + '/tidal-callback'
        ok, err = exchange_code_for_token(code, verifier, redirect_uri)
        if ok:
            return '''<html><body style="font-family:sans-serif;padding:20px;background:#0c0c0e;color:#e4e4e7;text-align:center;">
<h2 style="color:#22c55e;">Połączono z Tidal</h2>
<p>To okno zamknie się automatycznie. Wróć do głównego okna aplikacji.</p>
<script>
  if (window.opener) { window.opener.focus(); }
  setTimeout(function() { window.close(); }, 1500);
</script>
<p style="font-size:12px;color:#71717a;">Jeśli okno się nie zamknie, zamknij je ręcznie.</p>
</body></html>'''
        return f'<html><body style="font-family:sans-serif;padding:20px;"><h2>Błąd</h2><p>{err}</p><p><a href="/">Wróć do aplikacji</a></p></body></html>', 400
    except Exception as e:
        return f'<html><body style="font-family:sans-serif;padding:20px;"><h2>Błąd</h2><p>{e}</p><p><a href="/">Wróć do aplikacji</a></p></body></html>', 500


@app.route('/api/online-playlist-parse', methods=['POST'])
def api_online_playlist_parse():
    """
    Parsuje URL playlisty (Tidal) lub ręczną listę (Artist - Title).
    POST body: { url: string }
    Zwraca: { tracks: [{ artist, title, duration, source, externalId }], source, error? }
    """
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    try:
        from online_playlist_parser import parse_playlist_url
        tracks, err, source = parse_playlist_url(url)
        if err:
            return jsonify({'tracks': [], 'source': source, 'error': err})
        return jsonify({'tracks': tracks, 'source': source})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'tracks': [], 'error': str(e)}), 400


def _artist_words(s: str) -> set:
    """Słowa z artysty (bez feat/ft/, itp. do porównań)."""
    s = str(s or '').strip().lower()
    for sep in (' feat.', ' ft.', ' feat ', ' ft ', ',', ' x ', ' & '):
        s = s.replace(sep, ' ')
    return set(w for w in s.split() if len(w) > 1)


def _title_core(t: str) -> str:
    """Tytuł bez remix/version w nawiasach – do porównań."""
    t = str(t or '').strip().lower()
    import re
    t = re.sub(r'\s*\([^)]*(?:remix|mix|edit|version|radio|acoustic)[^)]*\)\s*', ' ', t, flags=re.I)
    return ' '.join(t.split())


def _title_core_for_remix(t: str) -> str:
    """Tytuł bez zawartości w nawiasach – do grupowania remiksów/wersji (ten sam utwór, różni wykonawcy)."""
    t = str(t or '').strip().lower()
    import re
    t = re.sub(r'\s*\([^)]*\)\s*', ' ', t)
    return ' '.join(t.split())


def _online_match_score(online: dict, candidate: dict) -> tuple[float, str]:
    """
    Score 0-100 + confidence: 'high'|'low'|'reject'.
    Wymagane: zgodność wykonawcy i tytułu. Odrzucamy słabe dopasowania.
    """
    def _norm(s):
        return str(s or '').strip().lower()
    oa = _norm(online.get('artist', ''))
    ot = _norm(online.get('title', ''))
    ca = _norm(candidate.get('Tags.Author', '') or candidate.get('Tags.Artist', ''))
    ct = _norm(candidate.get('Tags.Title', ''))
    oa_words = _artist_words(oa)
    ca_words = _artist_words(ca)
    ot_core = _title_core(ot)
    ct_core = _title_core(ct)

    # Odrzuć: brak wspólnych słów w wykonawcy (chyba że online to główny artysta w feat/,)
    artist_overlap = bool(oa_words & ca_words)
    main_match = False  # np. "Majki" vs "Majki – Kizo, Bletka" – Majki jest główny
    if oa and ca:
        oa_first = oa.split(',')[0].split(' feat')[0].split(' ft')[0].strip().lower()
        ca_first = ca.split(',')[0].split(' feat')[0].split(' ft')[0].strip().lower()
        if oa_first and (oa_first == ca_first or oa_first in ca_first or ca_first in oa_first):
            main_match = True
        if oa_words and ca_words and not artist_overlap and not main_match:
            return 0, 'reject'

    # Odrzuć: tytuł zupełnie inny (brak wspólnych słów)
    ot_words = set(ot_core.split())
    ct_words = set(ct_core.split())
    title_overlap = bool(ot_words & ct_words) or (ot_core in ct_core or ct_core in ot_core)
    if ot and ct and not title_overlap:
        return 0, 'reject'

    # Odrzuć: ten sam tytuł ale wykonawca kompletnie inny (np. Loona vs Bajorson)
    if title_overlap and oa_words and ca_words and not artist_overlap and not main_match:
        return 0, 'reject'

    score = 0.0
    if oa and ca:
        if oa == ca or main_match:
            score += 45
        elif artist_overlap:
            score += 30
        elif oa in ca or ca in oa:
            score += 25
    if ot and ct:
        if ot == ct or ot_core == ct_core:
            score += 45
        elif ot in ct or ct in ot:
            score += 25
        elif title_overlap:
            score += 15
    od = float(online.get('duration') or 0)
    cd = float(candidate.get('Infos.SongLength') or candidate.get('Infos.Duration') or 0)
    if od and cd and cd > 0:
        diff = abs(od - cd)
        if diff < 2:
            score += 3
        elif diff < 10:
            score += 1
    score = min(100, score)
    confidence = 'high' if (score >= 70 and artist_overlap or main_match) and title_overlap else ('low' if score >= 25 else 'reject')
    return score, confidence


@app.route('/api/online-match', methods=['POST'])
def api_online_match():
    """
    Dopasowuje utwory online do bazy. Zwraca propozycje (do 5 na utwór).
    POST body: { onlineTracks: [{ artist, title, duration, source, externalId }] }
    Zwraca: { matches: [{ onlineIdx, candidates: [{ idx, author, title, duration, bpm, rating, key, playlists, score }] }] }
    """
    global _songs
    _ensure_loaded()
    data = request.get_json() or {}
    online_tracks = data.get('onlineTracks') or []
    if not online_tracks:
        return jsonify({'matches': []})

    from vdjfolder import normalize_path
    path_to_playlists = {}
    if _vdjfolders:
        import xml.etree.ElementTree as ET
        for rel_path, content in _vdjfolders.items():
            name = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
            if not name:
                continue
            try:
                root = ET.fromstring(content)
                if root.tag != "VirtualFolder":
                    continue
                for song in root.findall("song"):
                        p = (song.get("path") or "").strip()
                        if p and not p.startswith("netsearch:"):
                            np = normalize_path(p)
                            if np:
                                path_to_playlists.setdefault(np, []).append(name)
            except ET.ParseError:
                pass

    def _candidate_rec(i: int) -> dict:
        s = _songs[i]
        path = s.get('FilePath', '') or ''
        np = normalize_path(path) if path else ''
        playlists = list(dict.fromkeys(path_to_playlists.get(np, [])))
        duration = s.get('Infos.SongLength') or s.get('Infos.Duration') or ''
        bpm = s.get('Tags.Bpm', '')
        if bpm:
            try:
                b = float(bpm)
                if 0.2 <= b <= 2:
                    bpm = f"{60/b:.1f}"
            except (TypeError, ValueError):
                pass
        return {
            'idx': i,
            'author': s.get('Tags.Author', '') or s.get('Tags.Artist', ''),
            'title': s.get('Tags.Title', ''),
            'duration': duration,
            'bpm': bpm,
            'rating': s.get('Tags.Stars') or s.get('Infos.Rating') or '',
            'key': s.get('Tags.Key', ''),
            'playlists': playlists,
            'pathSource': _path_source(path),
        }

    from vdjfolder import normalize_path as _norm_path
    matches = []
    for oi, ot in enumerate(online_tracks):
        scored = []
        seen_paths = set()
        for i, s in enumerate(_songs):
            from file_analyzer import is_streaming
            path = s.get('FilePath', '') or ''
            if is_streaming(path) or _is_vdj_cache_path(path):
                continue
            score, confidence = _online_match_score(ot, s)
            if confidence == 'reject' or score < 15:
                continue
            np = _norm_path(path) if path else ''
            if np and np in seen_paths:
                continue  # jedna propozycja na plik (bez duplikatów)
            seen_paths.add(np)
            rec = _candidate_rec(i)
            rec['score'] = round(score, 1)
            rec['confidence'] = confidence
            scored.append(rec)
        scored.sort(key=lambda x: (-x['score'], -len(x.get('playlists') or [])))
        best = scored[0] if scored else None
        certain = best and best.get('confidence') == 'high'
        one_to_one = len(scored) == 1 and certain
        no_matches = len(scored) == 0
        matches.append({
            'onlineIdx': oi,
            'candidates': scored[:5],
            'certain': certain,
            'oneToOne': one_to_one,
            'noMatches': no_matches,
        })
    return jsonify({'matches': matches})


def _online_playlist_resolve_paths(mappings: list, online_tracks: list) -> list:
    """Z mappings i online_tracks buduje listę ścieżek (zachowując kolejność).
    mappings: [{ onlineIdx, acceptedIdx }] lub [{ onlineIdx, acceptedIds: [idx|null] }].
    acceptedIds: null = streaming, int = ścieżka z bazy. Można wiele (multi-select).
    """
    return [e["path"] for e in _online_playlist_resolve_entries(mappings, online_tracks)]


def _online_playlist_resolve_entries(mappings: list, online_tracks: list) -> list:
    """Buduje listę wpisów {path, artist, title, size, songlength, bpm, key, remix} dla vdjfolder VDJ."""
    import re
    global _songs
    mapping_by_oi = {int(m.get('onlineIdx')): m for m in mappings if m.get('onlineIdx') is not None}
    entries = []
    n = len(online_tracks or [])
    for oi in range(n):
        m = mapping_by_oi.get(oi)
        ids = m.get('acceptedIds') if m else None
        if ids is None:
            if m:
                ai = m.get('acceptedIdx')
                ids = [ai] if ai is not None else [None]
            else:
                ids = [None]
        if not ids:
            ids = [None]
        ot = (online_tracks or [])[oi] if oi < len(online_tracks or []) else {}
        for ai in ids:
            if ai is None:
                if ot.get('source') == 'tidal' and ot.get('externalId'):
                    dur = ot.get("duration") or 0
                    try:
                        dur = float(dur) if dur else 0
                    except (ValueError, TypeError):
                        dur = 0
                    tid = str(ot["externalId"])
                    entries.append({
                        "path": "netsearch://td" + tid,
                        "artist": ot.get("artist") or ot.get("author") or "",
                        "title": ot.get("title") or "",
                        "songlength": dur,
                    })
            else:
                try:
                    ai = int(ai)
                except (TypeError, ValueError):
                    continue
                if 0 <= ai < len(_songs):
                    s = _songs[ai]
                    p = s.get('FilePath', '') or ''
                    if p:
                        if re.match(r"^td\d+$", p.strip(), re.I):
                            p = "netsearch://" + p.strip()
                        entries.append({
                            "path": p,
                            "artist": s.get("Tags.Author") or s.get("Tags.Artist") or "",
                            "title": s.get("Tags.Title") or "",
                            "size": s.get("Infos.FileSize") or s.get("FileSize") or 0,
                            "songlength": s.get("Infos.SongLength") or s.get("Infos.Duration") or 0,
                            "bpm": s.get("Tags.Bpm") or "",
                            "key": s.get("Tags.Key") or "",
                            "remix": s.get("Tags.Remix") or "",
                        })
    return entries


@app.route('/api/online-playlist-create', methods=['POST'])
def api_online_playlist_create():
    """
    Tworzy playlistę z zaakceptowanych dopasowań.
    POST body: { name: string, mappings: [{ onlineIdx, acceptedIdx }], onlineTracks?: [...] }
    acceptedIdx: indeks w bazie lub null (zostaw oryginalny streaming)
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    name = (data.get('name') or '').strip() or 'Online na Offline'
    mappings = data.get('mappings') or []
    online_tracks = data.get('onlineTracks') or []

    paths = _online_playlist_resolve_paths(mappings, online_tracks)
    entries = _online_playlist_resolve_entries(mappings, online_tracks)

    from vdjfolder import create_vdjfolder_playlist
    rel_path = _vdjfolders_create_new_path(name)
    content = create_vdjfolder_playlist(paths, name, entries=entries)
    _vdjfolders[rel_path] = content
    return jsonify({'name': name, 'relPath': rel_path, 'count': len(paths)})


@app.route('/api/online-playlist-download', methods=['POST'])
def api_online_playlist_download():
    """
    Pobiera playlistę jako plik.
    POST body: { name: string, mappings: [...], onlineTracks?: [...], format?: 'm3u'|'vdjfolder' }
    format: m3u (domyślnie) – uniwersalny, VDJ/Rekordbox/Serato; vdjfolder – VirtualDJ.
    Pomija utwory ze streamingu (td..., spotify:) – tylko pliki offline.
    """
    global _songs
    _ensure_loaded()
    data = request.get_json() or {}
    name = (data.get('name') or '').strip() or 'Online na Offline'
    mappings = data.get('mappings') or []
    online_tracks = data.get('onlineTracks') or []
    fmt = (data.get('format') or 'm3u').lower()

    paths = _online_playlist_resolve_paths(mappings, online_tracks)
    entries = _online_playlist_resolve_entries(mappings, online_tracks)

    from vdjfolder import create_vdjfolder_playlist, create_m3u_playlist, _is_exportable_path, _is_offline_path
    from flask import Response

    safe_name = (name or 'playlist').replace('/', '_').replace('\\', '_').strip() or 'playlist'

    if fmt == 'vdjfolder':
        content = create_vdjfolder_playlist(paths, name, entries=entries)
        filename = f"{safe_name}.vdjfolder"
        mimetype = 'application/xml'
        exportable = [p for p in paths if _is_exportable_path(p)]
    else:
        content = create_m3u_playlist(paths, name, extended=True, offline_only=True)
        filename = f"{safe_name}.m3u"
        mimetype = 'audio/x-mpegurl'
        exportable = [p for p in paths if _is_offline_path(p)]
    skipped = len(paths) - len(exportable)

    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'X-Export-Count': str(len(exportable)),
        'X-Skipped-Count': str(skipped),
    }
    return Response(content, mimetype=mimetype, headers=headers)


@app.route('/api/online-playlist-download-backup', methods=['POST'])
def api_online_playlist_download_backup():
    """
    Pobiera backup VDJ (ZIP) z playlistą – database.xml + Folders/nazwa.vdjfolder.
    VDJ wymaga backupu (nie pojedynczego pliku), aby poprawnie załadować playlistę.
    POST body: { name, mappings, onlineTracks } – jak online-playlist-download.
    """
    global _songs, _version, _vdjfolders
    _ensure_loaded()
    data = request.get_json() or {}
    name = (data.get('name') or '').strip() or 'Online na Offline'
    mappings = data.get('mappings') or []
    online_tracks = data.get('onlineTracks') or []

    paths = _online_playlist_resolve_paths(mappings, online_tracks)
    entries = _online_playlist_resolve_entries(mappings, online_tracks)

    from vdjfolder import create_vdjfolder_playlist, _is_exportable_path
    from flask import Response
    from io import BytesIO
    import zipfile

    safe_name = (name or 'playlist').replace('/', '_').replace('\\', '_').strip() or 'playlist'
    vdjfolder_content = create_vdjfolder_playlist(paths, name, entries=entries)
    vdjfolder_rel = f"Folders/{safe_name}.vdjfolder"

    z = BytesIO()
    with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as zf:
        buf = BytesIO()
        save_database(buf, _songs, _version)
        zf.writestr('database.xml', buf.getvalue())
        zf.writestr(vdjfolder_rel, vdjfolder_content.encode('utf-8'))
    data_out = z.getvalue()
    fn = f"{safe_name}-backup.zip"
    return Response(data_out, mimetype='application/zip', headers={
        'Content-Disposition': f'attachment; filename="{fn}"',
    })


def _get_vdj_folders_path() -> Path:
    """Ścieżka do folderu VDJ Folders (gdzie vdjfolder musi być, żeby VDJ go rozpoznał)."""
    import platform
    home = Path.home()
    if platform.system() == 'Darwin':  # macOS
        return home / "Library" / "Application Support" / "VirtualDJ" / "Folders"
    if platform.system() == 'Windows':
        local = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
        return local / "VirtualDJ" / "Folders"
    return home / ".virtualdj" / "Folders"


def _get_vdj_base_path() -> Path:
    """Ścieżka do folderu VirtualDJ (nadrzędny względem Folders)."""
    return _get_vdj_folders_path().parent


def _get_vdj_cache_path() -> Path:
    """Standardowa ścieżka folderu cache VDJ (pliki .vdjcache). Nie jest zapisana w database.xml – VDJ trzyma ją w ustawieniach; tu zwracamy typową lokalizację."""
    return _get_vdj_base_path() / "Cache"


@app.route('/api/vdj-folders-path', methods=['GET'])
def api_vdj_folders_path():
    """Zwraca ścieżkę do folderu VDJ Folders (gdzie vdjfolder musi być)."""
    return jsonify({'path': str(_get_vdj_folders_path())})


@app.route('/api/vdj-cache-path', methods=['GET'])
def api_vdj_cache_path():
    """Zwraca standardową ścieżkę folderu cache VDJ (Cache). Nie pochodzi z bazy – to typowa lokalizacja na tym komputerze."""
    return jsonify({'path': str(_get_vdj_cache_path())})


@app.route('/api/online-playlist-save-to-vdj', methods=['POST'])
def api_online_playlist_save_to_vdj():
    """
    Zapisuje playlistę bezpośrednio do folderu VDJ (Folders/) – żeby VDJ rozpoznał plik.
    POST body: { name, mappings, onlineTracks, format: 'vdjfolder'|'vdjbackup' }
    """
    global _songs, _version, _vdjfolders
    _ensure_loaded()
    data = request.get_json() or {}
    name = (data.get('name') or '').strip() or 'Online na Offline'
    mappings = data.get('mappings') or []
    online_tracks = data.get('onlineTracks') or []
    fmt = (data.get('format') or 'vdjfolder').lower()

    paths = _online_playlist_resolve_paths(mappings, online_tracks)
    entries = _online_playlist_resolve_entries(mappings, online_tracks)

    from vdjfolder import create_vdjfolder_playlist
    from io import BytesIO
    import zipfile

    safe_name = (name or 'playlist').replace('/', '_').replace('\\', '_').strip() or 'playlist'
    vdj_path = _get_vdj_folders_path()

    try:
        vdj_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return jsonify({'error': f'Nie można utworzyć folderu VDJ: {e}', 'path': str(vdj_path)}), 500

    if fmt == 'vdjbackup':
        vdjfolder_content = create_vdjfolder_playlist(paths, name, entries=entries)
        zip_path = _get_vdj_base_path() / f"{safe_name}-backup.zip"
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                buf = BytesIO()
                save_database(buf, _songs, _version)
                zf.writestr('database.xml', buf.getvalue())
                zf.writestr(f"Folders/{safe_name}.vdjfolder", vdjfolder_content.encode('utf-8'))
            return jsonify({'ok': True, 'path': str(zip_path), 'msg': f'Zapisano backup. W VDJ: File → Restore, wybierz {zip_path.name}'})
        except OSError as e:
            return jsonify({'error': f'Nie można zapisać: {e}', 'path': str(zip_path)}), 500

    vdjfolder_content = create_vdjfolder_playlist(paths, name, entries=entries)
    out_path = vdj_path / f"{safe_name}.vdjfolder"
    try:
        out_path.write_text(vdjfolder_content, encoding='utf-8')
        return jsonify({'ok': True, 'path': str(out_path), 'msg': 'Zapisano. Uruchom VDJ lub odśwież listę (F5).'})
    except OSError as e:
        return jsonify({'error': f'Nie można zapisać: {e}', 'path': str(out_path)}), 500


def _vdjfolders_create_new_path(name: str) -> str:
    """Tworzy unikalną ścieżkę dla nowego vdjfolder."""
    global _vdjfolders
    base = name.replace('/', '_').replace('\\', '_').strip() or 'playlist'
    rel = f"{base}.vdjfolder"
    if rel not in _vdjfolders:
        return rel
    for i in range(1, 1000):
        rel = f"{base}_{i}.vdjfolder"
        if rel not in _vdjfolders:
            return rel
    return f"{base}_new.vdjfolder"


def _resolve_audio_path(path: str, vdj_cache_path: Optional[str] = None) -> Optional[Path]:
    """Rozwiązuje ścieżkę do pliku. Dla netsearch://tdX / tdX + vdj_cache_path szuka pliku w cache (tdX.vdjcache / X.vdjcache)."""
    import unicodedata
    path = (path or "").strip()
    if not path:
        return None
    # Pełna ścieżka do pliku (np. C:\VDJ Cache\td123.vdjcache) – próbuj NFC/NFD
    for norm in ("NFC", "NFD"):
        p = Path(unicodedata.normalize(norm, path))
        if p.exists() and p.is_file():
            return p
    # Ścieżka Tidal/cache (netsearch://td123, td123) – szukaj pliku .vdjcache w folderze cache (jak imprezja quiz)
    if vdj_cache_path:
        from vdj_streaming import extract_tidal_id
        tid = extract_tidal_id(path)
        if tid:
            cache_dir = Path(vdj_cache_path)
            if cache_dir.is_dir():
                for name in (f"td{tid}.vdjcache", f"{tid}.vdjcache"):
                    candidate = cache_dir / name
                    if candidate.is_file():
                        return candidate
    return None


def _stream_vdjsample_as_ogg(p: Path):
    """
    Plik .vdjsample ma nagłówek VDJ (128 bajtów), potem Ogg Opus.
    Streamuje od bajtu 128 jako audio/ogg.
    """
    from flask import Response
    try:
        size = p.stat().st_size
        if size <= VDJSAMPLE_HEADER_SIZE:
            return jsonify({'error': 'Plik .vdjsample za krótki'}), 400
        content_length = size - VDJSAMPLE_HEADER_SIZE

        def generate():
            with open(p, 'rb') as f:
                f.seek(VDJSAMPLE_HEADER_SIZE)
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk

        return Response(
            generate(),
            mimetype='audio/ogg',
            direct_passthrough=True,
            headers={'Content-Length': str(content_length)}
        )
    except OSError as e:
        return jsonify({'error': f'Nie można odczytać pliku: {e}'}), 500


@app.route('/api/audio')
def api_audio():
    """
    Streamuje plik audio do odsłuchu.
    GET ?idx=123 – indeks utworu w _songs. HEAD – tylko nagłówki (bez streamu).
    Bezpieczeństwo: tylko pliki z załadowanej bazy.
    """
    try:
        global _songs
        try:
            _ensure_loaded()
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        idx = request.args.get('idx')
        if idx is None:
            return jsonify({'error': 'Brak parametru idx'}), 400
        try:
            idx = int(idx)
        except ValueError:
            return jsonify({'error': 'Nieprawidłowy idx'}), 400
        if idx < 0 or idx >= len(_songs):
            return jsonify({'error': 'Indeks poza zakresem'}), 404
        path = _songs[idx].get('FilePath', '') or ''
        if not path:
            return jsonify({'error': 'Brak ścieżki'}), 404
        vdj_cache_path = (request.args.get('vdjCachePath') or '').strip() or None
        if not vdj_cache_path and (_is_vdj_cache_path(path) or (path or '').strip().startswith(('netsearch:', 'td'))):
            try:
                cp = _get_vdj_cache_path()
                if cp.is_dir():
                    vdj_cache_path = str(cp)
            except Exception:
                pass
        p = _resolve_audio_path(path, vdj_cache_path)
        if p is None:
            from file_analyzer import is_streaming
            if is_streaming(path) or _is_vdj_cache_path(path):
                return jsonify({'error': 'Utwór streamingowy lub cache – ustaw ścieżkę folderu cache (VDJ) i spróbuj ponownie'}), 400
            return jsonify({'error': 'Plik nie istnieje'}), 404
        ext = p.suffix.lower()
        if ext not in ('.mp3', '.m4a', '.mp4', '.wav', '.flac', '.ogg', '.aac', '.vdjsample', '.vdjcache'):
            return jsonify({'error': 'Format nieobsługiwany do odtwarzania'}), 400
        if request.method == 'HEAD':
            if ext in ('.vdjsample', '.vdjcache'):
                size = p.stat().st_size
                oggs_offset = _find_oggs_offset(p)
                content_length = max(0, size - oggs_offset)
                from flask import Response
                return Response(status=200, headers={
                    'Content-Type': 'audio/ogg; codecs=opus',
                    'Content-Length': str(content_length),
                    'Accept-Ranges': 'bytes',
                })
            from flask import Response
            cl = p.stat().st_size
            mime = 'audio/mpeg' if ext == '.mp3' else ('audio/flac' if ext == '.flac' else 'application/octet-stream')
            return Response(status=200, headers={'Content-Type': mime, 'Content-Length': str(cl)})
        if ext in ('.vdjsample', '.vdjcache'):
            return _stream_vdj_as_ogg(p)
        mime = 'audio/mpeg' if ext == '.mp3' else ('audio/flac' if ext == '.flac' else None)
        return send_file(str(p), mimetype=mime, as_attachment=False)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400


@app.route('/api/duplicates', methods=['GET'])
def api_duplicates():
    """
    Wykrywa duplikaty w bazie.
    GET ?method=path|similar
    - path: ten sam plik (ścieżka znormalizowana)
    - similar: ten sam Author + Title (lowercase, strip)
    Zwraca: { groups: [[{idx, path, author, title}, ...], ...], totalDuplicates }
    """
    try:
        return _api_duplicates_impl()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


def _dup_rec(songs: list, i: int) -> dict:
    """Tworzy rekord duplikatu z pełnymi danymi do porównania (czas, BPM, rating, bitrate, playcount)."""
    s = songs[i]
    return {
        'idx': i,
        'path': s.get('FilePath', ''),
        'author': s.get('Tags.Author', ''),
        'title': s.get('Tags.Title', ''),
        'duration': s.get('Infos.SongLength') or s.get('Infos.Duration') or '',
        'bpm': s.get('Tags.Bpm', ''),
        'rating': s.get('Tags.Stars') or s.get('Infos.Rating') or '',
        'bitrate': s.get('Infos.Bitrate') or s.get('Tags.Bitrate') or '',
        'key': s.get('Tags.Key', ''),
        'genre': s.get('Tags.Genre', ''),
        'playcount': s.get('Infos.PlayCount') or s.get('PlayCount') or '',
    }


def _api_duplicates_impl():
    global _songs
    _ensure_loaded()
    method = (request.args.get('method') or 'path').lower()
    if method not in ('path', 'similar', 'tidal'):
        method = 'path'
    scope = (request.args.get('scope') or 'all').lower()
    if scope not in ('all', 'files', 'tidal', 'cache'):
        scope = 'all'

    from collections import defaultdict
    from vdjfolder import normalize_path
    from vdj_streaming import extract_tidal_id, is_tidal_path
    from file_analyzer import is_streaming

    def _norm(s):
        try:
            return str(s or '').strip().lower()
        except (TypeError, ValueError):
            return ''

    def _matches_scope(path: str) -> bool:
        if scope == 'all':
            return True
        is_cache = _is_vdj_cache_path(path)
        is_stream = is_streaming(path)
        if scope == 'files':
            return not is_stream and not is_cache
        if scope == 'tidal':
            return is_tidal_path(path) or is_cache
        if scope == 'cache':
            return is_cache
        return True

    groups = []
    if method == 'tidal':
        by_tidal_id = defaultdict(list)
        for i, s in enumerate(_songs):
            path = s.get('FilePath', '') or ''
            tid = extract_tidal_id(path)
            if tid:
                by_tidal_id[tid].append(i)
        for tid, indices in by_tidal_id.items():
            if len(indices) > 1:
                groups.append([_dup_rec(_songs, i) for i in indices])
    elif method == 'path':
        by_path = defaultdict(list)
        for i, s in enumerate(_songs):
            p = normalize_path(s.get('FilePath', '') or '')
            if p:
                by_path[p].append(i)
        for path, indices in by_path.items():
            if len(indices) > 1:
                groups.append([
                    _dup_rec(_songs, i) for i in indices
                ])
    else:  # similar
        by_key = defaultdict(list)
        for i, s in enumerate(_songs):
            author = _norm(s.get('Tags.Author', ''))
            title = _norm(s.get('Tags.Title', ''))
            if author or title:
                key = (author, title)
                by_key[key].append(i)
        for key, indices in by_key.items():
            if len(indices) > 1:
                groups.append([_dup_rec(_songs, i) for i in indices])

    # Filtruj grupy według scope – zostaw tylko rekordy pasujące do zakresu
    if scope != 'all':
        filtered_groups = []
        for group in groups:
            kept = [rec for rec in group if _matches_scope(rec.get('path', '') or rec.get('FilePath', ''))]
            if len(kept) > 1:
                filtered_groups.append(kept)
        groups = filtered_groups

    total = sum(len(g) - 1 for g in groups)  # ile można usunąć (zostawiamy 1 per grupa)

    # path → lista nazw playlist (w ilu listach jest utwór)
    path_to_playlists = {}
    if _vdjfolders:
        import xml.etree.ElementTree as ET
        for rel_path, content in _vdjfolders.items():
            name = rel_path.split("/")[-1].split("\\")[-1].replace(".vdjfolder", "").strip()
            if not name:
                continue
            try:
                root = ET.fromstring(content)
                if root.tag != "VirtualFolder":
                    continue
                for song in root.findall("song"):
                    p = (song.get("path") or "").strip()
                    if p and not p.startswith("netsearch:"):
                        np = normalize_path(p)
                        if np:
                            path_to_playlists.setdefault(np, []).append(name)
            except ET.ParseError:
                pass

    vdj_cache_path = (request.args.get('vdjCachePath') or '').strip() or None
    for group in groups:
        for rec in group:
            try:
                path_val = rec.get('path', '') or rec.get('FilePath', '')
                if isinstance(path_val, str):
                    np = normalize_path(path_val)
                else:
                    np = ''
                rec['playlists'] = list(dict.fromkeys(path_to_playlists.get(np, [])))
                rec['playlists_count'] = len(rec['playlists'])
                rec['FilePath'] = path_val if isinstance(path_val, str) else ''
                rec['pathSource'] = _path_source(path_val or '')
                rec['isOnDisk'] = rec['pathSource'] == 'dysk'
                _enrich_song_for_display(rec, vdj_cache_path)
            except Exception:
                rec['pathDisplay'] = str(rec.get('path', ''))[:80]
                rec['pathStatus'] = None
                rec['playlists'] = []
                rec['playlists_count'] = 0
                rec['pathSource'] = 'dysk'
                rec['isOnDisk'] = False

    return jsonify({'groups': groups, 'totalDuplicates': total, 'method': method})


@app.route('/api/remove-duplicates', methods=['POST'])
def api_remove_duplicates():
    """
    Usuwa zaznaczone duplikaty z bazy.
    POST body: { indicesToRemove: [5, 10, 15, ...] }
    Indeksy do usunięcia – usuwa w kolejności malejącej, żeby nie przesuwać indeksów.
    """
    global _songs
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    indices = sorted(set(data.get('indicesToRemove', [])), reverse=True)
    removed = 0
    for i in indices:
        if 0 <= i < len(_songs):
            _songs.pop(i)
            removed += 1
    return jsonify({'ok': True, 'removed': removed, 'count': len(_songs)})


@app.route('/api/merge-duplicate', methods=['POST'])
def api_merge_duplicate():
    """
    Scal duplikat: usuń rekord removeIdx, w playlistach zamień jego ścieżkę na ścieżkę z keepIdx.
    POST body: { removeIdx: 5, keepIdx: 10 }
    - removeIdx: indeks rekordu do usunięcia (jego ścieżka zostanie zastąpiona)
    - keepIdx: indeks rekordu do zachowania (jego ścieżka będzie używana)
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    remove_idx = data.get('removeIdx')
    keep_idx = data.get('keepIdx')
    if remove_idx is None or keep_idx is None:
        return jsonify({'error': 'Wymagane removeIdx i keepIdx'}), 400
    try:
        remove_idx = int(remove_idx)
        keep_idx = int(keep_idx)
    except (TypeError, ValueError):
        return jsonify({'error': 'Nieprawidłowe indeksy'}), 400
    if remove_idx == keep_idx:
        return jsonify({'error': 'removeIdx i keepIdx muszą być różne'}), 400
    if remove_idx < 0 or remove_idx >= len(_songs) or keep_idx < 0 or keep_idx >= len(_songs):
        return jsonify({'error': 'Indeks poza zakresem'}), 404

    path_remove = _songs[remove_idx].get('FilePath', '') or ''
    path_keep = _songs[keep_idx].get('FilePath', '') or ''
    if not path_remove or not path_keep:
        return jsonify({'error': 'Brak ścieżki w rekordzie'}), 400

    from vdjfolder import normalize_path
    np_remove = normalize_path(path_remove)
    np_keep = normalize_path(path_keep)
    if np_remove == np_keep:
        return jsonify({'error': 'Ta sama ścieżka – nie ma co scalać'}), 400

    # W vdjfolder: zamień path_remove na path_keep
    updated_folders = 0
    if _vdjfolders:
        import xml.etree.ElementTree as ET
        new_vdjfolders = {}
        for rel_path, content in _vdjfolders.items():
            try:
                root = ET.fromstring(content)
                if root.tag != "VirtualFolder":
                    new_vdjfolders[rel_path] = content
                    continue
                changed = False
                for song in root.findall("song"):
                    p = song.get("path", "")
                    if normalize_path(p) == np_remove:
                        song.set("path", path_keep)
                        changed = True
                if changed:
                    out = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
                    new_vdjfolders[rel_path] = out
                    updated_folders += 1
                else:
                    new_vdjfolders[rel_path] = content
            except ET.ParseError:
                new_vdjfolders[rel_path] = content
        _vdjfolders.clear()
        _vdjfolders.update(new_vdjfolders)

    # Usuń rekord removeIdx
    _songs.pop(remove_idx)
    new_keep_idx = keep_idx if keep_idx < remove_idx else keep_idx - 1

    return jsonify({
        'ok': True,
        'removed_idx': remove_idx,
        'kept_idx': new_keep_idx,
        'playlists_updated': updated_folders,
        'count': len(_songs),
    })


@app.route('/api/merge-duplicate-group', methods=['POST'])
def api_merge_duplicate_group():
    """
    Scal grupę duplikatów: zostaw keepIdx, usuń pozostałe (removeIndices), w playlistach zamień ich ścieżki na ścieżkę keepIdx.
    POST body: { keepIdx: 5, removeIndices: [10, 15, 20] }
    """
    global _songs, _vdjfolders
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    keep_idx = data.get('keepIdx')
    remove_indices = data.get('removeIndices', [])
    if keep_idx is None:
        return jsonify({'error': 'Wymagane keepIdx'}), 400
    try:
        keep_idx = int(keep_idx)
        remove_indices = [int(x) for x in remove_indices if x is not None]
    except (TypeError, ValueError):
        return jsonify({'error': 'Nieprawidłowe indeksy'}), 400
    remove_indices = [i for i in remove_indices if i != keep_idx and 0 <= i < len(_songs)]
    if not remove_indices:
        return jsonify({'error': 'Brak indeksów do usunięcia (różnych od keepIdx)'}), 400

    path_keep = _songs[keep_idx].get('FilePath', '') or ''
    if not path_keep:
        return jsonify({'error': 'Brak ścieżki w rekordzie do zachowania'}), 400

    from vdjfolder import normalize_path
    np_keep = normalize_path(path_keep)
    total_updated = 0
    actually_removed = 0

    # Sortuj malejąco, żeby przy usuwaniu nie przesuwać indeksów
    for remove_idx in sorted(set(remove_indices), reverse=True):
        if remove_idx == keep_idx or remove_idx < 0 or remove_idx >= len(_songs):
            continue
        path_remove = _songs[remove_idx].get('FilePath', '') or ''
        if not path_remove:
            _songs.pop(remove_idx)
            actually_removed += 1
            continue
        np_remove = normalize_path(path_remove)
        if np_remove == np_keep:
            _songs.pop(remove_idx)
            actually_removed += 1
            continue

        # Zamień w vdjfolder
        if _vdjfolders:
            import xml.etree.ElementTree as ET
            new_vdjfolders = {}
            for rel_path, content in _vdjfolders.items():
                try:
                    root = ET.fromstring(content)
                    if root.tag != "VirtualFolder":
                        new_vdjfolders[rel_path] = content
                        continue
                    changed = False
                    for song in root.findall("song"):
                        p = song.get("path", "")
                        if normalize_path(p) == np_remove:
                            song.set("path", path_keep)
                            changed = True
                    if changed:
                        out = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
                        new_vdjfolders[rel_path] = out
                        total_updated += 1
                    else:
                        new_vdjfolders[rel_path] = content
                except ET.ParseError:
                    new_vdjfolders[rel_path] = content
            _vdjfolders.clear()
            _vdjfolders.update(new_vdjfolders)

        _songs.pop(remove_idx)
        actually_removed += 1
        if keep_idx > remove_idx:
            keep_idx -= 1

    return jsonify({
        'ok': True,
        'removed': actually_removed,
        'playlists_updated': total_updated,
        'count': len(_songs),
    })


# Typowe sekwencje mojibake (UTF-8 odczytany jako Latin-1/CP1252) → poprawne znaki
# Kolejność: dłuższe sekwencje przed krótszymi (np. Ã³ przed Ã)
# ¿ (U+00BF) – ż w ISO-8859-2 odczytane jako Latin-1 (np. "już" → "ju¿")
_MOJIBAKE_REPLACEMENTS = [
    ('Ã³', 'ó'), ('Å‚', 'ł'), ('Ã¡', 'á'), ('Ã©', 'é'), ('Ã­', 'í'), ('Ãº', 'ú'),
    ('Ã±', 'ñ'), ('Ã§', 'ç'), ('Ã„', 'Ä'), ('Ã–', 'Ö'), ('Ãœ', 'Ü'),
    ('Ã¤', 'ä'), ('Ã¶', 'ö'), ('Ã¼', 'ü'), ('Ã¨', 'è'), ('Ã¬', 'ì'), ('Ã²', 'ò'),
    ('Ã¹', 'ù'), ('Ã¢', 'â'), ('Ãª', 'ê'), ('Ã®', 'î'), ('Ã´', 'ô'), ('Ã»', 'û'),
    ('Å¡', 'š'), ('Å¾', 'ž'), ('Å¥', 'ť'), ('Ä¾', 'ľ'), ('Ä›', 'ě'), ('Å™', 'ř'),
    ('Å¯', 'ů'), ('Ä‡', 'ć'), ('Å„', 'ń'), ('Å›', 'ś'), ('Åº', 'ź'), ('Å»', 'ż'),
    ('Ä…', 'ą'), ('Ä™', 'ę'), ('Ã°', 'ð'), ('Ã¾', 'þ'), ('ÃŸ', 'ß'),
    ('¿', 'ż'),   # ż (CP1250/ISO-8859-2: 0xBF) odczytane jako Latin-1 → U+00BF ¿
    ('³', 'ł'),   # ł (CP1250/ISO-8859-2: 0xB3) odczytane jako Latin-1 → U+00B3 ³ (np. żłobie, leży)
]

# Znaki podejrzane – typowe w mojibake (UTF-8 jako Latin-1), rzadko w poprawnym polskim tekście
_SUSPICIOUS_CHARS = frozenset('ÃÅÄÂÍ' + '\ufffd')  # Ã, Å, Ä, Â, Í, � (replacement)

# Dozwolone znaki w polskim tekście – odrzucamy „poprawki” wprowadzające Cyrillic itp.
def _is_valid_polish_text(s: str) -> bool:
    """Odrzuca teksty z Cyrillic itp. – unika błędnych poprawek (np. ł→ӣ)."""
    if not s:
        return True
    for c in s:
        o = ord(c)
        if 0x0400 <= o <= 0x04FF or o == 0xFFFD:
            return False
    return True


def _fix_mojibake(s: str) -> Optional[str]:
    """
    Naprawia mojibake w polskich polach (Author, Title).
    - Próbuje: UTF-8 odczytany jako Latin-1, CP1252, CP1250
    - Zastępuje typowe sekwencje (Ã³→ó, Å‚→ł itd.)
    - Wykrywa podejrzane znaki (Ã, Å, �) – próbuje naprawić
    Zwraca poprawioną wartość jeśli się zmieniła, inaczej None.
    """
    if not s or not isinstance(s, str):
        return None

    # 1. Próba pełnej konwersji (encode jako błędne kodowanie → decode UTF-8)
    for wrong_enc in ('latin-1', 'cp1252', 'cp1250'):
        try:
            fixed = s.encode(wrong_enc).decode('utf-8')
            if fixed != s and _is_valid_polish_text(fixed):
                return fixed
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

    # 2. Zastąpienie typowych sekwencji mojibake
    result = s
    for bad, good in _MOJIBAKE_REPLACEMENTS:
        if bad in result:
            result = result.replace(bad, good)
    if result != s and _is_valid_polish_text(result):
        return result

    # 3. Znak zastępczy � (U+FFFD) – zawsze błędny
    if '\ufffd' in s:
        return None  # Nie da się automatycznie naprawić – użytkownik musi sprawdzić źródło

    return None


@app.route('/api/encoding-fixes', methods=['GET'])
def api_encoding_fixes():
    """
    Wykrywa problemy kodowania (mojibake) w polach Author i Title.
    GET ?field=author|title|both&includeSuspicious=1 (opcjonalnie: także rekordy z podejrzanymi znakami)
    Zwraca: { items: [{ idx, field, before, after, needsReview? }, ...] }
    """
    global _songs
    _ensure_loaded()
    field = (request.args.get('field') or 'both').lower()
    if field not in ('author', 'title', 'both', 'all'):
        field = 'both'
    include_suspicious = request.args.get('includeSuspicious', '').lower() in ('1', 'true', 'yes')

    tag_map = {
        'author': 'Tags.Author', 'title': 'Tags.Title',
        'genre': 'Tags.Genre', 'user1': 'Tags.User1', 'user2': 'Tags.User2',
    }
    if field == 'both':
        check_tags = [('author', 'Tags.Author'), ('title', 'Tags.Title')]
    elif field == 'all':
        check_tags = list(tag_map.items())
    else:
        check_tags = [(field, tag_map[field])]
    items = []
    seen = set()  # (idx, field) – unikamy duplikatów
    for i, s in enumerate(_songs):
        for fk, tag_key in check_tags:
            val = s.get(tag_key, '') or ''
            if not val:
                continue
            fixed = _fix_mojibake(val)
            if fixed:
                items.append({'idx': i, 'field': fk, 'before': val, 'after': fixed})
                seen.add((i, fk))
            elif include_suspicious and (i, fk) not in seen:
                # Podejrzane znaki (Ã, Å, �) – nie umiemy naprawić, ale warto pokazać
                if any(c in _SUSPICIOUS_CHARS for c in val) or '\ufffd' in val:
                    items.append({
                        'idx': i, 'field': fk, 'before': val, 'after': val,
                        'needsReview': True,
                    })
    return jsonify({'items': items, 'count': len(items)})


@app.route('/api/apply-encoding-fixes', methods=['POST'])
def api_apply_encoding_fixes():
    """
    Stosuje poprawki kodowania.
    POST body: { changes: [{ idx, field, newValue }, ...] }
    field: 'author' | 'title' | 'genre' | 'user1' | 'user2'
    """
    global _songs
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    changes = data.get('changes', [])
    tag_map = {'author': 'Tags.Author', 'title': 'Tags.Title', 'genre': 'Tags.Genre', 'user1': 'Tags.User1', 'user2': 'Tags.User2'}
    applied = 0
    for c in changes:
        idx = c.get('idx')
        field = c.get('field')
        new_val = c.get('newValue', '')
        if idx is None or field not in tag_map or idx < 0 or idx >= len(_songs):
            continue
        key = tag_map[field]
        _songs[idx][key] = str(new_val)
        applied += 1
    return jsonify({'ok': True, 'applied': applied, 'count': len(_songs)})


def _same_after_normalize(a: str, b: str) -> bool:
    """Czy dwa stringi są identyczne po złączeniu wielokrotnych spacji."""
    return ' '.join((a or '').split()) == ' '.join((b or '').split())


def _clean_title(value: str, pattern: str) -> str:
    """
    Czyści tytuł z linków, nawiasów, znaczników.
    pattern: 'urls' | 'brackets' | 'remix' | 'all'
    """
    import re
    s = (value or '').strip()
    if not s:
        return s

    if pattern in ('urls', 'all'):
        # Linki: http://, https://, www.
        s = re.sub(r'https?://[^\s]+', '', s, flags=re.IGNORECASE)
        s = re.sub(r'www\.[^\s]+', '', s, flags=re.IGNORECASE)
        # E-mail
        s = re.sub(r'[\w.-]+@[\w.-]+\.\w+', '', s)

    if pattern in ('brackets', 'all'):
        # Nawiasy okrągłe: (Official Video), (HD), (Video), (Lyrics), (Audio), [HD], [4K], itd.
        s = re.sub(r'\([^)]*official[^)]*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\([^)]*video[^)]*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\([^)]*audio[^)]*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\([^)]*lyric[s]?[^)]*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\([^)]*hd[^)]*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\([^)]*4k[^)]*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\[[^\]]*hd[^\]]*\]', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\[[^\]]*4k[^\]]*\]', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\[[^\]]*official[^\]]*\]', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*explicit\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*clean\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*sped\s+up\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*slowed[^)]*\)', '', s, flags=re.IGNORECASE)

    if pattern in ('remix', 'all'):
        # Wersje w nawiasach – usuń. NIE usuwać "Song Club Mix" / "Song Remix" (bez nawiasów – prawidłowe opisy).
        # (Radio Edit), (Club Mix), (Tiesto Remix) itd. – tylko gdy w (nawiasach)
        s = re.sub(r'\(\s*radio\s*edit\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*radio\s*remix\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*radio\s*mix\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*club\s*mix\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*dub\s*mix\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*original\s*mix\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*extended\s*mix\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*instrumental\s*mix\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*vocal\s*mix\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*album\s*version\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*single\s*version\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*radio\s*version\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*club\s*version\s*\)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\(\s*edit\s*\)', '', s, flags=re.IGNORECASE)
        # (Remix), (Tiesto Remix), (David Guetta Remix) – \s* pozwala na brak spacji przed remix
        s = re.sub(r'\(\s*[^)]*remix[^)]*\)', '', s, flags=re.IGNORECASE)

    # Usuń puste nawiasy, wielokrotne spacje, trim
    s = re.sub(r'\[\s*\]', '', s)
    s = re.sub(r'\(\s*\)', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'^[\s\-–—,;:]+|[\s\-–—,;:]+$', '', s)
    return s


def _extract_removed_phrases(before: str, after: str) -> list[str]:
    """
    Zwraca listę fraz usuniętych z before (zawartość nawiasów okrągłych/kwadratowych,
    która była w before a zniknęła w after).
    """
    import re
    before = (before or '').strip()
    after = (after or '').strip()
    if not before or before == after:
        return []
    before_lower = before.lower()
    after_lower = after.lower()
    removed = []
    for m in re.finditer(r'[(\[]([^)\]]+)[)\]]', before):
        content = m.group(1).strip()
        if content and content.lower() in before_lower and content.lower() not in after_lower:
            removed.append(content)
    return removed


def _should_skip_by_ignore(before: str, after: str, ignore_phrases: list[str]) -> bool:
    """
    True jeśli usunięta fraza (zawartość nawiasów) dokładnie pasuje do którejś
    z fraz do zostawienia. Dopasowanie dokładne (case-insensitive) – unika
    nadmiernego filtrowania przy substring (np. „Mix” nie wyklucza „Original Mix”).
    """
    removed = _extract_removed_phrases(before, after)
    ignore_set = {p.strip().lower() for p in (ignore_phrases or []) if p and p.strip()}
    for r in removed:
        if r.lower() in ignore_set:
            return True
    return False


@app.route('/api/clean-title-suggestions', methods=['GET'])
def api_clean_title_suggestions():
    """
    Wykrywa tytuły/artystów do czyszczenia (linki, nawiasy, wersje).
    GET ?pattern=urls|brackets|remix|all&field=title|author|both&ignore=phrase1\\nphrase2
    ignore: frazy do zostawienia (po nowej linii lub przecinku)
    Zwraca: { items: [{ idx, field, before, after }, ...] }
    """
    global _songs
    _ensure_loaded()
    pattern = (request.args.get('pattern') or 'all').lower()
    if pattern not in ('urls', 'brackets', 'remix', 'all'):
        pattern = 'all'
    field = (request.args.get('field') or 'title').lower()
    if field not in ('title', 'author', 'both'):
        field = 'title'
    ignore_raw = request.args.get('ignore') or ''
    ignore_phrases = [p.strip() for p in ignore_raw.replace(',', '\n').splitlines() if p.strip()]

    items = []
    key_title = 'Tags.Title'
    key_author = 'Tags.Author'
    key_artist = 'Tags.Artist'  # fallback (VDJ/Rekordbox)
    for i, s in enumerate(_songs):
        if field in ('title', 'both'):
            val = str(s.get(key_title, '') or '').strip()
            cleaned = _clean_title(val, pattern)
            if cleaned and cleaned.strip() and not _same_after_normalize(cleaned, val):
                if not _should_skip_by_ignore(val, cleaned, ignore_phrases):
                    items.append({'idx': i, 'field': 'title', 'before': val, 'after': cleaned})
        if field in ('author', 'both'):
            val = str(s.get(key_author, '') or s.get(key_artist, '') or '').strip()
            cleaned = _clean_title(val, pattern)
            if cleaned and cleaned.strip() and not _same_after_normalize(cleaned, val):
                if not _should_skip_by_ignore(val, cleaned, ignore_phrases):
                    items.append({'idx': i, 'field': 'author', 'before': val, 'after': cleaned})
    return jsonify({'items': items, 'count': len(items), 'pattern': pattern, 'field': field})


@app.route('/api/apply-clean-title', methods=['POST'])
def api_apply_clean_title():
    """
    Stosuje czyszczenie tytułów i/lub artystów.
    POST body: { changes: [{ idx, field, newValue }, ...] }
    field: 'title' | 'author'
    """
    global _songs
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    changes = data.get('changes', [])
    applied = 0
    key_map = {'title': 'Tags.Title', 'author': 'Tags.Author'}
    for c in changes:
        idx = c.get('idx')
        f = c.get('field', 'title')
        new_val = c.get('newValue', '')
        key = key_map.get(f, 'Tags.Title')
        if idx is not None and 0 <= idx < len(_songs):
            _songs[idx][key] = str(new_val)
            if f == 'author':
                _songs[idx]['Tags.Artist'] = str(new_val)  # sync (VDJ używa Author/Artist)
            applied += 1
    return jsonify({'ok': True, 'applied': applied, 'count': len(_songs)})


def _normalize_value(value: str, pattern: str) -> str:
    """
    Ujednolica wielkość liter.
    pattern: 'titlecase' | 'uppercase' | 'lowercase'
    """
    s = (value or '').strip()
    if not s:
        return s
    if pattern == 'titlecase':
        return s.title()
    if pattern == 'uppercase':
        return s.upper()
    if pattern == 'lowercase':
        return s.lower()
    return s


# Mapowanie polskich znaków na ASCII (dla klucza grupowania – wykrywa Gasowski vs Gąsowski)
_POLISH_TO_ASCII = str.maketrans(
    'ąęćłńóśźżĄĆĘŁŃÓŚŹŻ',
    'aeclnoszzACELNOSZZ'
)


def _normalize_for_grouping(s: str, strip_diacritics: bool = True) -> str:
    """
    Klucz do grupowania podobnych nazw.
    Abba, ABBA, AbBa → abba. AC-DC, AC - DC, AC/DC, ACDC → acdc.
    Wojciech Gąsowski, Wojciech Gasowski → wojciechgasowski (strip_diacritics).
    """
    import re
    s = str(s or '').strip().lower()
    s = re.sub(r'[\s\-_/]+', '', s)
    if strip_diacritics:
        s = s.translate(_POLISH_TO_ASCII)
    return s


def _levenshtein(a: str, b: str) -> int:
    """Odległość edycyjna Levenshteina."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,
                curr[j] + 1,
                prev[j] + (0 if ca == cb else 1)
            ))
        prev = curr
    return prev[-1]


def _path_source(path: str) -> str:
    """Zwraca: 'tidal' | 'cache' | 'dysk'."""
    if not path:
        return 'dysk'
    p = str(path).strip().lower()
    if p.endswith('.vdjcache'):
        return 'cache'
    from file_analyzer import is_streaming
    if is_streaming(path):
        return 'tidal'
    return 'dysk'


def _has_polish_diacritics(s: str) -> bool:
    """Czy string zawiera polskie znaki diakrytyczne."""
    return any(c in 'ąęćłńóśźżĄĆĘŁŃÓŚŹŻ' for c in s)


def _pick_suggested(variants: list) -> str:
    """
    Preferuje wariant z polskimi znakami; jeśli brak – najdłuższy.
    """
    with_diacritics = [v for v in variants if _has_polish_diacritics(v)]
    if with_diacritics:
        return max(with_diacritics, key=len)
    return max(variants, key=len)


@app.route('/api/normalize-suggestions', methods=['GET'])
def api_normalize_suggestions():
    """
    Wykrywa grupy podobnych nazw (Abba/ABBA/AbBa, AC-DC/AC/DC/ACDC).
    Grupuje po znormalizowanym kluczu (bez spacji, myślników, slashów, polskich znaków).
    Wojciech Gąsowski / Wojciech Gasowski / Wojceich Gasowski (fuzzy=1) → jedna grupa.
    GET ?field=author|title|both&fuzzy=0|1
    Zwraca: { groups: [{ key, variants, suggested, items: [{idx, field, before, pathSource, author, title}], ... }] }
    """
    global _songs
    _ensure_loaded()
    import re
    field = (request.args.get('field') or 'both').lower()
    if field not in ('author', 'title', 'both'):
        field = 'both'
    fuzzy = request.args.get('fuzzy', '0') == '1'

    tag_map = {'author': 'Tags.Author', 'title': 'Tags.Title'}
    by_group = {}  # key -> { variants: set, items: [(idx, field, before, ...)] }

    def _get_val(s, fk):
        key = tag_map.get(fk, 'Tags.Title')
        return str(s.get(key, '') or (s.get('Tags.Artist', '') if fk == 'author' else '') or '').strip()

    for i, s in enumerate(_songs):
        for fk, tag_key in tag_map.items():
            if field != 'both' and field != fk:
                continue
            val = _get_val(s, fk)
            if not val:
                continue
            key = _normalize_for_grouping(val)
            if not key:
                continue
            if key not in by_group:
                by_group[key] = {'variants': set(), 'items': []}
            by_group[key]['variants'].add(val)
            path = s.get('FilePath', '') or ''
            author = _get_val(s, 'author')
            title = _get_val(s, 'title')
            is_streaming = False
            is_cache = False
            if path:
                from file_analyzer import is_streaming as _is_stream
                is_streaming = _is_stream(path) or _is_vdj_cache_path(path)
                is_cache = _is_vdj_cache_path(path)
            by_group[key]['items'].append({
                'idx': i, 'field': fk, 'before': val,
                'pathSource': _path_source(path),
                'author': author, 'title': title,
                'isStreaming': is_streaming, 'isCache': is_cache,
            })

    # Opcjonalne łączenie grup po podobieństwie kluczy (Levenshtein ≤ 2, różnica długości ≤ 2)
    if fuzzy and len(by_group) > 1:
        keys = list(by_group.keys())
        parent = {k: k for k in keys}

        def _find(x):
            if parent[x] != x:
                parent[x] = _find(parent[x])
            return parent[x]

        def _union(x, y):
            px, py = _find(x), _find(y)
            if px != py:
                parent[py] = px

        for i, k1 in enumerate(keys):
            for k2 in keys[i + 1:]:
                if abs(len(k1) - len(k2)) <= 2 and _levenshtein(k1, k2) <= 2:
                    _union(k1, k2)

        merged = {}
        for k in keys:
            root = _find(k)
            if root not in merged:
                merged[root] = {'variants': set(), 'items': []}
            merged[root]['variants'] |= by_group[k]['variants']
            merged[root]['items'].extend(by_group[k]['items'])
        by_group = merged

    groups = []
    for key, data in by_group.items():
        variants = list(data['variants'])
        if len(variants) < 2:
            continue
        items = data['items']
        fk = items[0]['field']
        # Grupy title z różnymi wykonawcami = remiksy/wersje (np. Sweets For My Sweet – The Drifters, C.J. Lewis, ChrisS)
        # Tytuł jest prawidłowy, różnica to wykonawca – nie pokazuj w ujednoliceniu
        if fk == 'title':
            unique_authors = set((it.get('author') or '').strip() for it in items if (it.get('author') or '').strip())
            if len(unique_authors) >= 2:
                continue  # pomiń – to różne wersje tego samego utworu, nie tytuły do poprawy
        suggested = _pick_suggested(variants)
        variant_details = []
        for v in sorted(variants):
            matching = [it for it in items if it['before'] == v]
            if fk == 'title':
                extras = list(dict.fromkeys(it['author'] for it in matching if it.get('author')))[:3]
            else:
                extras = list(dict.fromkeys(it['title'] for it in matching if it.get('title')))[:3]
            variant_details.append({'variant': v, 'extras': extras})
        groups.append({
            'key': key,
            'variants': sorted(variants),
            'variantDetails': variant_details,
            'suggested': suggested,
            'items': items,
        })

    total_items = sum(len(g['items']) for g in groups)
    return jsonify({'groups': groups, 'count': total_items})


@app.route('/api/remixes', methods=['GET'])
def api_remixes():
    """
    Grupy utworów z tym samym tytułem, różnymi wykonawcami (remiksy, covery, wersje).
    Np. Sweets For My Sweet – The Drifters, C.J. Lewis, ChrisS.
    Zwraca: { groups: [{ title, authors, items: [{idx, author, title, pathSource, playCount, playlists, FilePath, pathDisplay, isStreaming}] }] }
    """
    try:
        return _api_remixes_impl()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'groups': [], 'count': 0}), 500


def _api_remixes_impl():
    """Implementacja api_remixes – wzór jak api_duplicates."""
    global _songs
    _ensure_loaded()
    exclude_tidal = request.args.get('excludeTidal', '0') in ('1', 'true', 'yes')
    groups = _get_remix_groups()
    if exclude_tidal:
        for grp in groups:
            grp['items'] = [it for it in grp['items'] if it.get('pathSource') == 'dysk']
        groups = [g for g in groups if len(g['items']) >= 2 and len(set(it.get('author') or '(brak)' for it in g['items'])) >= 2]
    for grp in groups:
        grp['authors'] = sorted(set(it['author'] or '(brak)' for it in grp['items']))
        grp['titleNorm'] = _normalize_for_grouping(_title_core_for_remix(grp['title']))
        for it in grp['items']:
            s = _songs[it['idx']]
            it['FilePath'] = s.get('FilePath', '') or ''
            it['playCount'] = s.get('Infos.PlayCount') or s.get('PlayCount') or ''
            it['duration'] = s.get('Infos.SongLength') or s.get('Infos.Duration') or ''
            it['bpm'] = s.get('Tags.Bpm', '')
            it['key'] = s.get('Tags.Key', '')
            it['rating'] = s.get('Tags.Stars') or s.get('Infos.Rating') or ''
            it['duration'] = s.get('Infos.SongLength') or s.get('Infos.Duration') or ''
            it['bpm'] = s.get('Tags.Bpm', '')
            it['key'] = s.get('Tags.Key', '')
            it['rating'] = s.get('Tags.Stars') or s.get('Infos.Rating') or ''

    vdj_cache_path = (request.args.get('vdjCachePath') or '').strip() or None
    # Optymalizacja: enrich listy RAZ dla wszystkich unikalnych utworów (jak duplikaty)
    unique_songs = []
    seen_idx = set()
    for grp in groups:
        for it in grp['items']:
            idx = it['idx']
            if idx not in seen_idx:
                seen_idx.add(idx)
                unique_songs.append(_songs[idx])
    if unique_songs:
        _enrich_songs_with_lists(unique_songs)
    for grp in groups:
        for it in grp['items']:
            try:
                idx = it['idx']
                s = _songs[idx]
                it['playlists'] = s.get('lists', [])
                it['playlists_count'] = len(it['playlists'])
                it['listsDisplay'] = s.get('listsDisplay', '')
                _enrich_song_for_display(it, vdj_cache_path, skip_path_check=True)
            except Exception:
                it['playlists'] = it.get('playlists', [])
                it['playlists_count'] = len(it['playlists'])
                it['listsDisplay'] = it.get('listsDisplay', '')
                it['pathDisplay'] = str(it.get('FilePath', ''))[:80]
                it['pathStatus'] = None
                it['isStreaming'] = False
                it['isCache'] = False

    total = sum(len(g['items']) for g in groups)
    return jsonify({'groups': groups, 'count': total})


def _get_remix_groups():
    """Buduje grupy remiksów (ten sam tytuł, różni wykonawcy). Zwraca listę grup z items zawierającymi idx, pathSource."""
    global _songs
    tag_author = 'Tags.Author'
    tag_title = 'Tags.Title'
    by_title = {}
    for i, s in enumerate(_songs):
        author = str(s.get(tag_author, '') or s.get('Tags.Artist', '') or '').strip()
        title = str(s.get(tag_title, '') or '').strip()
        if not title:
            continue
        title_core = _title_core_for_remix(title)
        key = _normalize_for_grouping(title_core) if title_core else _normalize_for_grouping(title)
        if not key:
            continue
        path = s.get('FilePath', '') or ''
        if key not in by_title:
            by_title[key] = {'titleOrig': title, 'authors': set(), 'items': []}
        by_title[key]['authors'].add(author or '(brak)')
        by_title[key]['items'].append({
            'idx': i, 'author': author, 'title': title,
            'pathSource': _path_source(path),
        })
    groups = []
    for key, data in by_title.items():
        if len(data['authors']) < 2:
            continue
        groups.append({
            'title': data['titleOrig'],
            'authors': sorted(data['authors']),
            'items': data['items'],
        })
    return groups


@app.route('/api/remixes-skip-tidal', methods=['POST'])
def api_remixes_skip_tidal():
    """
    Usuwa z bazy remiksy/wersje z Tidal w grupach, gdzie istnieje wersja z dysku.
    Zostawia tylko wersje z dysku.
    """
    global _songs
    _ensure_loaded()
    _push_undo_state()
    groups = _get_remix_groups()
    to_remove = []
    for grp in groups:
        has_disk = any(it['pathSource'] == 'dysk' for it in grp['items'])
        if not has_disk:
            continue
        for it in grp['items']:
            if it['pathSource'] in ('tidal', 'cache'):
                to_remove.append(it['idx'])
    to_remove = sorted(set(to_remove), reverse=True)
    removed = 0
    for i in to_remove:
        if 0 <= i < len(_songs):
            _songs.pop(i)
            removed += 1
    return jsonify({'ok': True, 'removed': removed, 'count': len(_songs)})


@app.route('/api/normalize-suggestions-legacy', methods=['GET'])
def api_normalize_suggestions_legacy():
    """
    Stary format (pojedyncze pozycje) – dla kompatybilności.
    """
    global _songs
    _ensure_loaded()
    field = (request.args.get('field') or 'both').lower()
    pattern = (request.args.get('pattern') or 'titlecase').lower()
    if field not in ('author', 'title', 'both'):
        field = 'both'
    if pattern not in ('titlecase', 'uppercase', 'lowercase'):
        pattern = 'titlecase'
    tag_map = {'author': 'Tags.Author', 'title': 'Tags.Title'}
    items = []
    for i, s in enumerate(_songs):
        for fk, tag_key in tag_map.items():
            if field != 'both' and field != fk:
                continue
            val = str(s.get(tag_key, '') or s.get('Tags.Artist' if fk == 'author' else '', '') or '').strip()
            normalized = _normalize_value(val, pattern)
            if normalized and not _same_after_normalize(normalized, val):
                items.append({'idx': i, 'field': fk, 'before': val, 'after': normalized})
    return jsonify({'items': items, 'count': len(items), 'pattern': pattern})


@app.route('/api/apply-normalize', methods=['POST'])
def api_apply_normalize():
    """
    Stosuje ujednolicenie nazw (Author/Title).
    POST body: { changes: [{ idx, field, newValue }, ...] }
    """
    global _songs
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    changes = data.get('changes', [])
    tag_map = {'author': 'Tags.Author', 'title': 'Tags.Title'}
    applied = 0
    for c in changes:
        idx = c.get('idx')
        field = c.get('field')
        new_val = c.get('newValue', '')
        if idx is None or field not in tag_map or idx < 0 or idx >= len(_songs):
            continue
        key = tag_map[field]
        _songs[idx][key] = str(new_val)
        if field == 'author':
            _songs[idx]['Tags.Artist'] = str(new_val)
        applied += 1
    return jsonify({'ok': True, 'applied': applied, 'count': len(_songs)})


def _split_artist_title(s: str):
    """
    Dzieli string po separatorze - lub – lub — (wymaga spacji przed i po).
    Wyjątek: lewa część kończąca się na -s (possessive, np. Pandora-s Box) – nie dziel.
    Wymaganie spacji zapobiega błędnemu podziałowi "Pandora-s Box (Radio Edit)".
    Zwraca (left, right) jeśli znaleziono, inaczej None.
    """
    import re
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    if not t or len(t) < 4:
        return None
    # Wymagaj spacji przed i po myślniku – "Pandora-s Box" nie ma spacji przed "-", więc nie dzielimy
    m = re.match(r'^(.+?)\s+[-–—]\s+(.+)$', t)
    if m:
        left, right = m.group(1).strip(), m.group(2).strip()
        if left and right:
            if re.search(r'\w+-s$', left):
                return None
            return (left, right)
    return None


@app.route('/api/split-author-title-suggestions', methods=['GET'])
def api_split_author_title_suggestions():
    """
    Wykrywa utwory gdzie Title lub Author zawiera separator - (Artist - Title).
    Domyślnie: lewa → Author, prawa → Title.
    Zwraca: { items: [{ idx, source, left, right, newAuthor, newTitle, currentAuthor, currentTitle }, ...] }
    """
    global _songs
    _ensure_loaded()

    items = []
    for i, s in enumerate(_songs):
        author = (s.get('Tags.Author', '') or s.get('Tags.Artist', '') or '').strip()
        title = (s.get('Tags.Title', '') or '').strip()

        for source, val in [('title', title), ('author', author)]:
            if not val or len(val) < 4:
                continue
            # Nie proponuj rozdzielania Title na Artist+Title, gdy Artist jest już wypełniony
            if source == 'title' and author:
                continue
            split_r = _split_artist_title(val)
            if split_r:
                left, right = split_r
                items.append({
                    'idx': i, 'source': source,
                    'left': left, 'right': right,
                    'newAuthor': left, 'newTitle': right,
                    'currentAuthor': author, 'currentTitle': title,
                })
                break
    return jsonify({'items': items, 'count': len(items)})


@app.route('/api/apply-split-author-title', methods=['POST'])
def api_apply_split_author_title():
    """
    Stosuje podział Artist/Title.
    POST body: { changes: [{ idx, newAuthor, newTitle }, ...] }
    """
    global _songs
    _ensure_loaded()
    _push_undo_state()
    data = request.get_json() or {}
    changes = data.get('changes', [])
    applied = 0
    for c in changes:
        idx = c.get('idx')
        new_author = c.get('newAuthor', '')
        new_title = c.get('newTitle', '')
        if idx is not None and 0 <= idx < len(_songs):
            _songs[idx]['Tags.Author'] = str(new_author)
            _songs[idx]['Tags.Title'] = str(new_title)
            _songs[idx]['Tags.Artist'] = str(new_author)
            applied += 1
    return jsonify({'ok': True, 'applied': applied, 'count': len(_songs)})


AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.mp4', '.wav', '.flac', '.ogg', '.aac', '.vdjsample', '.vdjcache'}
VDJSAMPLE_HEADER_SIZE = 128  # VDJ nagłówek, potem Ogg Opus
VDJ_OGGS_SEARCH_LIMIT = 512  # Szukaj sygnatury OggS w pierwszych N bajtach (jak imprezja quiz)


def _find_oggs_offset(p: Path) -> int:
    """Szuka sygnatury OggS w pierwszych bajtach pliku (vdjsample/vdjcache). Zwraca offset lub 128."""
    try:
        with open(p, 'rb') as f:
            buf = f.read(VDJ_OGGS_SEARCH_LIMIT)
        idx = buf.find(b'OggS')
        return idx if idx >= 0 else VDJSAMPLE_HEADER_SIZE
    except OSError:
        return VDJSAMPLE_HEADER_SIZE


def _stream_vdj_as_ogg(p: Path):
    """Streamuje plik .vdjsample lub .vdjcache jako Ogg (nagłówek VDJ, potem Ogg Opus). Jak imprezja quiz: OggS w pierwszych 512 B, obsługa Range."""
    from flask import Response, request
    try:
        size = p.stat().st_size
        oggs_offset = _find_oggs_offset(p)
        if size <= oggs_offset:
            return jsonify({'error': 'Plik za krótki (brak danych Ogg)'}), 400
        content_length = size - oggs_offset
        mimetype = 'audio/ogg; codecs=opus'
        range_header = request.headers.get('Range') if request else None
        if range_header and range_header.strip().startswith('bytes='):
            parts = range_header.replace('bytes=', '').strip().split('-')
            try:
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if len(parts) > 1 and parts[1] else content_length - 1
            except (ValueError, TypeError):
                start, end = 0, content_length - 1
            req_start = max(0, min(start, content_length - 1))
            req_end = min(content_length - 1, max(req_start, end))
            if req_start <= req_end:
                chunk_size = req_end - req_start + 1
                def generate_range():
                    with open(p, 'rb') as f:
                        f.seek(oggs_offset + req_start)
                        remaining = chunk_size
                        while remaining > 0:
                            chunk = f.read(min(65536, remaining))
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk
                resp = Response(
                    generate_range(),
                    status=206,
                    mimetype=mimetype,
                    direct_passthrough=True,
                    headers={
                        'Content-Length': str(chunk_size),
                        'Content-Range': f'bytes {req_start}-{req_end}/{content_length}',
                        'Accept-Ranges': 'bytes',
                    }
                )
                return resp
        def generate():
            with open(p, 'rb') as f:
                f.seek(oggs_offset)
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        return Response(
            generate(),
            mimetype=mimetype,
            direct_passthrough=True,
            headers={'Content-Length': str(content_length), 'Accept-Ranges': 'bytes'}
        )
    except OSError as e:
        return jsonify({'error': f'Nie można odczytać pliku: {e}'}), 500


def _pick_folder_native() -> Optional[str]:
    """Otwiera natywne okno wyboru folderu. Zwraca ścieżkę lub None."""
    try:
        sys_name = platform.system()
        if sys_name == 'Darwin':
            r = subprocess.run(
                ['osascript', '-e', 'return POSIX path of (choose folder with prompt "Wybierz folder z muzyką")'],
                capture_output=True, text=True, timeout=60
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            return None  # Nie używaj tkinter na macOS – crashuje w kontekście serwera Flask
        elif sys_name == 'Windows':
            r = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 'Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.FolderBrowserDialog; $f.Description = "Wybierz folder z muzyką"; if ($f.ShowDialog() -eq "OK") { $f.SelectedPath }'],
                capture_output=True, text=True, timeout=60
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            return None
        else:
            for cmd in [['zenity', '--file-selection', '--directory', '--title=Wybierz folder z muzyką'],
                        ['kdialog', '--getexistingdirectory', str(Path.home())]]:
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    if r.returncode == 0 and r.stdout.strip():
                        return r.stdout.strip()
                except FileNotFoundError:
                    continue
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                path = filedialog.askdirectory(title='Wybierz folder z muzyką')
                root.destroy()
                return path if path else None
            except Exception:
                pass
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    return None


@app.route('/api/pick-folder', methods=['GET'])
def api_pick_folder():
    """
    Otwiera natywne okno wyboru folderu. Zwraca { path: "..." } lub { error: "..." }.
    """
    path = _pick_folder_native()
    if path:
        return jsonify({'path': path})
    return jsonify({'error': 'Nie wybrano folderu lub brak obsługi okna dialogowego'}), 400


@app.route('/api/database-folders', methods=['GET'])
def api_database_folders():
    """
    Zwraca unikalne foldery, w których znajdują się pliki z bazy (katalog nadrzędny każdej ścieżki).
    Tylko foldery istniejące na dysku, ze ścieżkami bezwzględnymi.
    Zwraca: { folders: ["/path/to/folder", ...], count }
    """
    global _songs
    _ensure_loaded()
    folders = set()
    for s in _songs:
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
    """Skanuje folder, zwraca listę plików sierot."""
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
    """Wzbogaca rekord sieroty o metadane z pliku (artist, title, length, bpm, key, rating)."""
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


@app.route('/api/scan-orphan-files', methods=['POST'])
def api_scan_orphan_files():
    """
    Skanuje folder(y) w poszukiwaniu plików muzycznych, które nie są w bazie.
    POST body: { folderPath: "/path" } lub { folderPaths: ["/path1", "/path2"] }
    Zwraca: { files: [{ path, name }], count }
    """
    global _songs
    _ensure_loaded()
    data = request.get_json() or {}
    folders = []
    if data.get('folderPaths'):
        folders = [str(f).strip() for f in data['folderPaths'] if str(f).strip()]
    if not folders and (data.get('folderPath') or '').strip():
        folders = [(data.get('folderPath') or '').strip()]
    if not folders:
        return jsonify({'error': 'Podaj ścieżkę folderu lub foldery'}), 400

    db_paths = set()
    for s in _songs:
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


@app.route('/api/audio-file', methods=['GET'])
def api_audio_file():
    """
    Odtwarza plik audio po ścieżce (dla plików sierot).
    GET ?path=... (URL-encoded), opcjonalnie &vdjCachePath=... dla odsłuchu cache (netsearch/td...).
    """
    try:
        path = request.args.get('path', '')
        if not path:
            return jsonify({'error': 'Brak ścieżki'}), 400
        vdj_cache_path = (request.args.get('vdjCachePath') or '').strip() or None
        p = _resolve_audio_path(path, vdj_cache_path)
        if p is None:
            return jsonify({'error': 'Plik nie istnieje'}), 404
        ext = p.suffix.lower()
        if ext not in AUDIO_EXTENSIONS:
            return jsonify({'error': 'Format nieobsługiwany'}), 400
        if ext in ('.vdjsample', '.vdjcache'):
            return _stream_vdj_as_ogg(p)
        mime = 'audio/mpeg' if ext == '.mp3' else ('audio/flac' if ext == '.flac' else None)
        return send_file(str(p), mimetype=mime, as_attachment=False)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 400


@app.route('/api/open-folder', methods=['POST'])
def api_open_folder():
    """
    Otwiera folder w systemowym menedżerze plików (Finder na macOS, Explorer na Windows).
    POST body: { path: "/path/to/file/or/folder" } – otwiera katalog nadrzędny jeśli to plik.
    """
    data = request.get_json() or {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'error': 'Brak ścieżki'}), 400
    try:
        p = Path(path)
        if p.is_file():
            folder = str(p.parent)
        elif p.is_dir():
            folder = str(p)
        else:
            folder = str(p.parent) if p.parent else str(p)
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


@app.route('/api/orphan-file', methods=['DELETE'])
def api_delete_orphan_file():
    """
    Usuwa plik po ścieżce (dla plików sierot).
    Ścieżka musi być w katalogu nadrzędnym plików z bazy (ochrona path traversal).
    Body: { path: "..." }
    """
    global _songs
    _ensure_loaded()
    data = request.get_json() or {}
    path = (data.get('path') or '').strip()
    if not path:
        return jsonify({'error': 'Brak ścieżki'}), 400
    p = Path(path)
    if not _is_path_safe(p, must_be_file=True):
        return jsonify({'error': 'Ścieżka niedozwolona (poza katalogami bazy)'}), 403
    if not p.exists():
        return jsonify({'error': 'Plik nie istnieje'}), 404
    if not p.is_file():
        return jsonify({'error': 'Nie jest plikiem'}), 400
    if p.suffix.lower() not in AUDIO_EXTENSIONS:
        return jsonify({'error': 'Nieprawidłowy typ pliku'}), 400
    try:
        p.unlink()
    except PermissionError:
        return jsonify({'error': 'Brak uprawnień do usunięcia'}), 403
    except OSError as e:
        return jsonify({'error': 'Błąd usuwania: ' + str(e)}), 500
    return jsonify({'ok': True})


@app.route('/api/license/status', methods=['GET'])
def api_license_status():
    """Status licencji – czy eksport jest dozwolony."""
    lic = check_export_license()
    return jsonify({
        'canExport': lic.get('allowed', False),
        'machineId': lic.get('machineId', get_machine_id()),
        'reason': lic.get('reason') if not lic.get('allowed') else None,
    })


@app.route('/api/license/machine-id', methods=['GET'])
def api_license_machine_id():
    """Machine ID – do zamówienia licencji."""
    return jsonify({'machineId': get_machine_id()})


@app.route('/api/license/activate', methods=['POST'])
def api_license_activate():
    """Aktywacja licencji – body: { "key": "IMPREZJA-RSA-..." }."""
    data = request.get_json() or {}
    key = (data.get('key') or '').strip()
    if not key:
        return jsonify({'error': 'Brak klucza licencji'}), 400
    if save_license_key(key):
        return jsonify({'ok': True, 'message': 'Licencja aktywowana'})
    lic = check_export_license()
    return jsonify({'error': lic.get('reason', 'Nieprawidłowy klucz')}), 400


@app.route('/api/undo-available', methods=['GET'])
def api_undo_available():
    """Sprawdza, czy można cofnąć ostatnią operację."""
    return jsonify({'available': len(_undo_stack) > 0, 'count': len(_undo_stack)})


@app.route('/api/undo', methods=['POST'])
def api_undo():
    """Cofa ostatnią operację – przywraca poprzedni stan bazy."""
    global _songs, _vdjfolders, _extra_files, _version, _source, _db_path
    if not _undo_stack:
        return jsonify({'error': 'Brak operacji do cofnięcia'}), 400
    state = _undo_stack.pop()
    _songs = state['songs']
    _vdjfolders = state['vdjfolders']
    _extra_files = state.get('extra_files', {})
    _version = state['version']
    _source = state['source']
    _db_path = Path(state['db_path']) if state.get('db_path') else None
    return jsonify({'ok': True, 'count': len(_songs), 'undoRemaining': len(_undo_stack)})


@app.route('/api/status', methods=['GET'])
def api_status():
    """Status załadowanej bazy."""
    return jsonify({
        'loaded': len(_songs) > 0,
        'count': len(_songs),
        'version': _version,
        'path': str(_db_path) if _db_path else None,
        'loadedVia': 'path' if _db_path else ('file' if _songs else None),
        'source': _source,
        'undoAvailable': len(_undo_stack) > 0,
        'undoCount': len(_undo_stack),
    })


if __name__ == '__main__':
    import os
    use_reloader = os.environ.get('VDJ_NO_RELOAD') != '1'
    app.run(host='127.0.0.1', port=5050, debug=True, use_reloader=use_reloader)
