# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec – NJR konwerter
# Build: pyinstaller njr.spec

import os
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

_version = '0.0.0'
try:
    _version = Path('../VERSION').read_text(encoding='utf-8').strip()
except OSError:
    pass

_engine_bin = []
for _cand in [
    Path('engine_bridge/build/njr-engine-export'),
    Path('engine_bridge/build/Release/njr-engine-export.exe'),
    Path('engine_bridge/build/njr-engine-export.exe'),
]:
    if _cand.is_file():
        _engine_bin.append((str(_cand), '.'))
        break

# Moduły wymagane przez NJR (hiddenimports)
# Uwaga: importy wewnątrz funkcji w app.py (Tidal, playlisty online, Rekordbox DB)
# muszą być tu jawnie – inaczej onefile kończy się ImportError w runtime.
hidden_imports = [
    'flask',
    'flask_cors',
    'werkzeug',
    'jinja2',
    'vdj_parser',
    'vdjfolder',
    'vdj_adapter',
    'rb_parser',
    'rb_generator',
    'rb_masterdb_generator',
    'serato_parser',
    'engine_parser',
    'engine_generator',
    'engine_libdjinterop',
    'traktor_parser',
    'djxml_parser',
    'djxml_generator',
    'unified_model',
    'tag_writer',
    'file_analyzer',
    'vdj_streaming',
    'license_njr',
    'version_info',
    'updater',
    'app_state',
    'constants',
    'native_dialogs',
    'ssl_utils',
    'routes',
    'routes.meta',
    'routes.session',
    'routes.license',
    'routes.files',
    'routes.rb_beta',
    'folder_library',
    'mutagen',
    'cryptography',
    'pyrekordbox',
    'pyrekordbox.db6',
    'sqlalchemy',
    'sqlalchemy.engine',
    'tidal_auth',
    'online_playlist_parser',
    'tkinter',
    'tkinter.filedialog',
    # numpy 2.x (pyrekordbox) — PyInstaller <6.14 pomija numpy._core._exceptions
    'numpy._core._exceptions',
    'numpy._core._multiarray_umath',
    'numpy._core.multiarray',
    'numpy._core._dtype_ctypes',
]

_datas = [
    ('static', 'static'),
    ('../VERSION', '.'),
    ('scripts', 'scripts'),
]
_binaries = list(_engine_bin)

try:
    _numpy_datas, _numpy_binaries, _numpy_hidden = collect_all('numpy')
    _datas += _numpy_datas
    _binaries += _numpy_binaries
    hidden_imports += _numpy_hidden
except Exception:
    pass

try:
    _certifi_datas, _certifi_binaries, _certifi_hidden = collect_all('certifi')
    _datas += _certifi_datas
    _binaries += _certifi_binaries
    hidden_imports += _certifi_hidden
except Exception:
    pass

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_certifi.py'],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NJR-konwerter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX bywa źródłem fałszywych alarmów AV na Windows – wyłącz na release jeśli trzeba
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=platform.system() != 'Darwin',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if platform.system() == 'Darwin':
    app = BUNDLE(
        exe,
        name='NJR Konwerter.app',
        icon=None,
        bundle_identifier='pl.djdamsza.njr-konwerter',
        info_plist={
            'CFBundleShortVersionString': _version,
            'CFBundleVersion': _version,
            'CFBundleDisplayName': 'NJR Konwerter',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.13',
        },
    )
