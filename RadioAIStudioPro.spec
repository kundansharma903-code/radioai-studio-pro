# -*- mode: python ; coding: utf-8 -*-
"""
RadioAI Studio Pro — PyInstaller spec (Phase M)

Produces ``dist/RadioAI Studio Pro/RadioAI Studio Pro.exe`` plus
the ``_internal/`` folder containing Python runtime + dependencies
+ bundled assets. This output folder is what the Inno Setup
installer (Phase N) will copy to ``C:\\Program Files\\RadioAI
Studio Pro\\``.

Build:
    py -m PyInstaller RadioAIStudioPro.spec --clean --noconfirm

Output layout (onefolder mode):
    dist\\RadioAI Studio Pro\\
        RadioAI Studio Pro.exe         ← main launcher, icon embedded
        _internal\\
            Python311.dll              ← Python runtime
            PyQt6 libs, pybass3, ...   ← all dependencies
            assets\\                    ← splash, icons, fonts, qss
            database\\                  ← schema.sql, seeds.sql
            base_library.zip
            ...

Source-code protection: PyInstaller compiles all .py files to .pyc
bytecode and zips them into the bundle. The original .py source is
NOT shipped. (Determined attackers can decompile bytecode with
tools like uncompyle6, but it's not casual-user-visible. Phase O
later can layer PyArmor / Nuitka for stronger obfuscation if
operator wants commercial-grade protection.)
"""

import os
from pathlib import Path

# SPECPATH is set by PyInstaller to the directory containing this
# spec file when invoked. Use it as project root.
PROJECT_ROOT = Path(SPECPATH).resolve()


# ── Data files (resources bundled alongside the exe) ─────────────────────
# Pattern: (source_path_relative_to_project, dest_path_inside_bundle)
datas = [
    # Branding + UI assets
    ("assets/splash.png",         "assets"),
    ("assets/icon.png",           "assets"),
    ("assets/icon.ico",           "assets"),
    ("assets/logo.png",           "assets"),
    ("assets/style.qss",          "assets"),
    ("assets/premium.qss",        "assets"),
    # Fonts directory — recurse-bundle every TTF/OTF inside
    ("assets/fonts",              "assets/fonts"),
    # Database schema + seeds — used for fresh-install bootstrap
    # (Database() creates a new DB at first run from these if no
    # legacy DB exists at %LOCALAPPDATA%).
    ("database/schema.sql",       "database"),
    ("database/seeds.sql",        "database"),
]


# ── Hidden imports (modules PyInstaller's static analysis misses) ────────
# pybass3 loads its DLLs dynamically via ctypes — PyInstaller's
# import scanner doesn't see those references. We list them
# explicitly + bundle the vendor DLLs in the binaries section.
hiddenimports = [
    "pybass3",
    "pybass3.bass_module",
    "pybass3.bass_channel",
    "pybass3.bass_stream",
    "pybass3.bass_tags",
    # Pillow — used by the SOTG report PDF generator
    "PIL._tkinter_finder",
    # reportlab — PDF generation for SOTG daily reports
    "reportlab.pdfgen",
    "reportlab.pdfgen.canvas",
    "reportlab.lib.pagesizes",
    # sqlite3 dynamic loadable extensions
    "sqlite3",
]


# ── BASS DLLs (pybass3's vendor binaries) ────────────────────────────────
# pybass3 ships its native binaries inside its install location
# under vendor/. PyInstaller's auto-detection sometimes misses
# these; pin them explicitly.
import pybass3
_PYBASS3_DIR = Path(pybass3.__file__).parent
binaries = []
for dll_name in ("bass.dll", "tags.dll"):
    src = _PYBASS3_DIR / "vendor" / dll_name
    if src.exists():
        # Bundle into pybass3/vendor/ inside the bundle so pybass3's
        # internal loader can find it via its package-relative path.
        binaries.append((str(src), "pybass3/vendor"))


# ── Modules to exclude (save space + boot time) ──────────────────────────
excludes = [
    "tkinter",          # not used; default Python ships with it
    "matplotlib",
    "scipy",
    "pytest",           # tests aren't bundled
    "pytest_qt",
    "_pytest",
]


# ════════════════════════════════════════════════════════════════════════
# PyInstaller pipeline
# ════════════════════════════════════════════════════════════════════════

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    # optimize=2 strips docstrings + asserts from .pyc — smaller
    # bundle, marginally faster import. Has no functional impact.
    optimize=2,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    # Output exe name — operator wants "Adobe Photoshop.exe"-style
    # branding (with spaces) over compact "RadioAIStudioPro.exe".
    name="RadioAI Studio Pro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX compression — shrinks binaries ~30-50% but adds startup
    # cost. Disabled by default; flip True if final bundle size
    # becomes a concern.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=False = pure GUI app, no console window flashing on
    # launch. log file (rotating, in %LOCALAPPDATA%\…\Logs\) is the
    # debug surface instead.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Multi-resolution .ico file generated from the source logo.
    # Embeds 16/32/48/64/128/256 px versions so Windows picks the
    # crispest size for whatever surface needs it (Explorer
    # thumbnail, taskbar, Alt-Tab, Task Manager, etc.).
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    # Output folder name — what users see in dist/ and what Inno
    # Setup will copy to C:\Program Files\.
    name="RadioAI Studio Pro",
)
