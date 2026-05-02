# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for RadioAI Studio Pro.

Build:
    pyinstaller radioai.spec --clean --noconfirm
Output:
    dist/RadioAI Studio Pro/RadioAI Studio Pro.exe
"""

import os
import sys
from PyInstaller.utils.hooks import collect_submodules

# ── Locate VLC ──────────────────────────────────────────────────────────
VLC_CANDIDATES = [
    r'C:\Program Files\VideoLAN\VLC',
    r'C:\Program Files (x86)\VideoLAN\VLC',
]
VLC_PATH = next((p for p in VLC_CANDIDATES if os.path.exists(p)), None)
if VLC_PATH is None:
    raise SystemExit(
        'VLC not found. Install VideoLAN VLC before building.\n'
        'Looked in: ' + ', '.join(VLC_CANDIDATES)
    )

# ── Binaries (native DLLs bundled alongside the EXE) ────────────────────
binaries = [
    (os.path.join(VLC_PATH, 'libvlc.dll'),     '.'),
    (os.path.join(VLC_PATH, 'libvlccore.dll'), '.'),
    (os.path.join(VLC_PATH, 'plugins'),        'plugins'),
]

# ── Data files (assets + web UI) ────────────────────────────────────────
datas = [
    ('ui/web',      'ui/web'),      # all HTML + CSS + JS recursively
    ('assets',      'assets'),      # icon, fonts, etc.
]

# ── Hidden imports (modules loaded dynamically / via QtWebChannel) ──────
hiddenimports = [
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebChannel',
    'PyQt6.QtNetwork',
    'PyQt6.QtMultimedia',
    'sqlite3',
    'vlc',
    'mutagen',
    'mutagen.mp3',
    'mutagen.id3',
    'mutagen.flac',
    'mutagen.oggvorbis',
    'mutagen.mp4',
    'pydub',
    'librosa',
    'numpy',
    'soundfile',
]
# Include the entire RadioAI package tree (ui/, core/, models/) implicitly.
for pkg in ('ui', 'core', 'models'):
    hiddenimports += collect_submodules(pkg)

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[os.path.abspath(os.getcwd())],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'pdb', 'pydoc_data', 'doctest',
        'test', 'tests',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RadioAI Studio Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX often flags false-positive with Windows Defender
    console=False,      # Windowed app, no console
    disable_windowed_traceback=False,
    icon='assets/radioai.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RadioAI Studio Pro',
)
