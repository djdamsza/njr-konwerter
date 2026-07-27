# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec – NJR konwerter
# Build: pyinstaller njr.spec

import os
import platform
from pathlib import Path

block_cipher = None

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
]

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=_engine_bin,
    datas=[
        ('static', 'static'),
        ('../VERSION', '.'),
        ('scripts', 'scripts'),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
