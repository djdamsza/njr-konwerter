from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from flask import Blueprint, jsonify, request

import app_state as st
from constants import AUDIO_EXTENSIONS
from native_dialogs import pick_folder_native, pick_open_path_native
from vdjfolder import normalize_path

bp = Blueprint('files', __name__)


@bp.route('/api/pick-folder', methods=['GET'])
def api_pick_folder():
    path = pick_folder_native()
    if path:
        return jsonify({'path': path})
    return jsonify({'error': 'Nie wybrano folderu lub brak obsługi okna dialogowego'}), 400


@bp.route('/api/pick-open', methods=['GET'])
def api_pick_open():
    path = pick_open_path_native()
    if path:
        return jsonify({'path': path})
    return jsonify({'error': 'Nie wybrano pliku'}), 400


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


_SKIP_DIR_NAMES = {
    "Library", "Applications", "System", "node_modules", ".git", ".Trash",
    "Caches", "Cache", "__pycache__", ".npm", ".cache", "venv", ".venv",
    "site-packages", "DerivedData", ".cursor", "Pods", "Volumes",
    "Backups.backupdb",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "$Recycle.Bin", "System Volume Information", "Recovery", "AppData",
}


def _db_audio_paths() -> set:
    db_paths = set()
    for song in st.songs:
        fp = song.get("FilePath", "") or ""
        if fp and not fp.strip().startswith(("td", "netsearch:", "soundcloud:", "beatport:", "deezer:")):
            if not fp.lower().endswith(".vdjcache"):
                np = normalize_path(fp)
                if np:
                    db_paths.add(np)
    return db_paths


def _disk_roots() -> list[Path]:
    if platform.system() == "Windows":
        from platform_paths import windows_drives
        drives = [Path(item["path"]) for item in windows_drives()]
        return drives or [Path.home()]
    home = Path.home()
    roots = [home]
    volumes = Path("/Volumes")
    if not volumes.is_dir():
        return roots
    try:
        home_dev = home.stat().st_dev
    except OSError:
        home_dev = None
    try:
        entries = list(volumes.iterdir())
    except OSError:
        return roots
    for vol in entries:
        try:
            if not vol.is_dir() or vol.name.startswith("."):
                continue
            low = vol.name.lower()
            if "time machine" in low or low.startswith("com.apple"):
                continue
            if home_dev is not None and vol.stat().st_dev == home_dev:
                continue
            roots.append(vol)
        except OSError:
            continue
    return roots


def _pick_volumes() -> list[dict]:
    """Dyski do wyboru. Na Windowsie litera i etykieta, na Macu katalog domowy i woluminy."""
    if platform.system() == "Windows":
        from platform_paths import windows_drives
        drives = windows_drives()
        if drives:
            return drives
        return [{"name": "Dysk tego komputera", "path": str(Path.home())}]
    found = [{"name": "Dysk tego Maca", "path": str(Path.home())}]
    seen = {str(Path.home())}
    for vol in _disk_roots():
        path = str(vol)
        if path in seen:
            continue
        seen.add(path)
        found.append({"name": vol.name, "path": path})
    return found


def _user_audio_allowed(path: Path) -> bool:
    """Plik audio w katalogu domowym albo na podłączonym dysku. Nie Library i nie system."""
    if st.is_path_safe(path, must_be_file=True):
        return True
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    if not resolved.is_file() or resolved.suffix.lower() not in AUDIO_EXTENSIONS:
        return False
    if resolved.suffix.lower() == ".vdjcache":
        return False
    homes = [Path.home().resolve()]
    volumes = Path("/Volumes")
    allowed_roots = homes
    if volumes.is_dir():
        allowed_roots.append(volumes.resolve())
    for root in allowed_roots:
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in _SKIP_DIR_NAMES:
            return False
        return True
    return False


def iter_orphan_audio(roots: list[Path], db_paths: set, limit: int = 800) -> tuple[list[dict], bool, list[str]]:
    """Pliki muzyczne spoza bazy. Pomija system, Library i cache."""
    found = []
    errors = []
    capped = False
    seen = set()

    def on_error(err: OSError) -> None:
        errors.append(str(err))

    for root in roots:
        if capped:
            break
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=on_error):
            dirnames[:] = sorted(
                name for name in dirnames
                if name not in _SKIP_DIR_NAMES and not name.startswith(".")
                and "time machine" not in name.lower()
            )
            for name in filenames:
                suffix = Path(name).suffix.lower()
                if suffix not in AUDIO_EXTENSIONS or suffix == ".vdjcache":
                    continue
                full = Path(dirpath) / name
                try:
                    np = normalize_path(str(full.resolve()))
                except OSError as exc:
                    errors.append(str(exc))
                    continue
                if not np or np in db_paths or np in seen:
                    continue
                seen.add(np)
                found.append({"path": np, "name": name})
                if len(found) >= limit:
                    capped = True
                    break
            if capped:
                break
    return found, capped, errors


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

    db_paths = _db_audio_paths()

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


@bp.route('/api/volumes', methods=['GET'])
def api_volumes():
    return jsonify({"volumes": _pick_volumes()})


@bp.route('/api/scan-orphan-disk', methods=['POST'])
def api_scan_orphan_disk():
    """Muzyka w katalogu domowym i na podłączonych dyskach, której nie ma w bazie."""
    st.ensure_loaded()
    data = request.get_json() or {}
    chosen = (data.get("root") or "").strip()
    if chosen:
        root = Path(chosen)
        if not root.is_dir():
            return jsonify({"error": "Tego dysku nie ma"}), 400
        roots = [root]
    else:
        roots = _disk_roots()
    found, capped, errors = iter_orphan_audio(roots, _db_audio_paths())
    files = [_enrich_orphan_with_metadata(row) for row in found]
    return jsonify({
        'files': files,
        'count': len(files),
        'capped': capped,
        'roots': [str(root) for root in roots],
        'errors': errors[:8] if errors else None,
    })


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
            if not (p.is_file() and _user_audio_allowed(p)):
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
    if not _user_audio_allowed(p):
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
