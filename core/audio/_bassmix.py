"""
Private BASSmix plumbing for core.audio (Phase 5 foundation).

Loads ``bassmix.dll`` if available and exposes the BASSmix C functions
the unified-mixer architecture needs. If the DLL is absent, this
module reports the mixer as "not available" and every caller falls
through to the existing per-engine direct-play code path. **No
breakage when bassmix.dll is missing** — that is the safety contract
for Step 5.0 of the migration.

The BASSmix addon is shipped separately from bass.dll. pybass3 does
NOT bundle it. Operator must download it and drop into one of:

  1. ``core/audio/vendor/bassmix.dll``  (preferred — version-locked
     to this build, lives next to engine code)
  2. The pybass3 vendor directory alongside ``bass.dll`` (typically
     ``site-packages/pybass3/vendor/bassmix.dll``)

Download URL:
    https://www.un4seen.com/files/bassmix24.zip

License:
    BSD-style for non-commercial use. Commercial use requires the
    same BASS license operator already needs for production air.
    Free during development. See vendor/README.md.

Threading
---------
The mixer stream itself runs on BASS's audio thread. Calls into this
module from Python (add/remove channel, position queries) are
thread-safe per BASS's own documentation. Callbacks (sync) follow the
same cross-thread pattern as ``core.audio.engine`` — emit a Qt signal
to marshal to the main thread before touching UI or DB.
"""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path
from typing import Optional

import pybass3.bass_module as _bm

log = logging.getLogger("bassmix")


# ── BASSmix constants (subset we use) ──────────────────────────────────────

# Mixer stream creation flags (from bassmix.h)
BASS_MIXER_END           = 0x10000       # mixer stops when all sources finish
BASS_MIXER_NONSTOP       = 0x20000       # mixer never stops (silent gap-fill)
BASS_MIXER_POSEX         = 0x80000       # accurate per-source position
BASS_SAMPLE_FLOAT        = 0x100         # 32-bit float mixer output (matches BASS)

# AddChannel flags
BASS_MIXER_CHAN_BUFFER   = 0x2000        # buffer source data for level meters
BASS_MIXER_CHAN_PAUSE    = 0x20000       # paused initially; play() to start
BASS_MIXER_CHAN_NORAMPIN = 0x800000      # don't ramp in newly-added channel


# ── DLL singleton (lazy, graceful) ─────────────────────────────────────────

_mixer_dll: Optional[ctypes.WinDLL] = None
_load_attempted: bool = False


def _find_bassmix_dll() -> Optional[Path]:
    """Search candidate locations for bassmix.dll. Returns the first
    matching path, or None if nowhere found."""
    here = Path(__file__).parent
    candidates = [
        here / "vendor" / "bassmix.dll",                  # 1. project-local
        Path(str(_bm.BASS_DLL)).parent / "bassmix.dll",   # 2. alongside bass.dll
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def get_mixer_dll() -> Optional[ctypes.WinDLL]:
    """Return the loaded bassmix.dll handle (singleton). Returns None
    when the DLL is not installed — callers MUST treat None as
    "mixer architecture not available" and fall through to the
    legacy direct-play code path.

    The load attempt happens exactly once per process. After the
    first failure, subsequent calls return None without re-searching.
    """
    global _mixer_dll, _load_attempted
    if _mixer_dll is not None:
        return _mixer_dll
    if _load_attempted:
        return None
    _load_attempted = True

    dll_path = _find_bassmix_dll()
    if dll_path is None:
        log.info(
            "bassmix.dll not found — mixer architecture is disabled. "
            "Engines continue to use the direct-play code path. "
            "To enable: drop bassmix.dll into core/audio/vendor/ "
            "(see core/audio/vendor/README.md)."
        )
        return None

    try:
        dll = ctypes.WinDLL(str(dll_path))
    except Exception as exc:
        log.warning(
            f"bassmix.dll exists at {dll_path} but failed to load: {exc}")
        return None

    # ── Declare argtypes/restypes for the functions we use ────────────
    # BASS_Mixer_StreamCreate(freq, chans, flags) -> HSTREAM
    dll.BASS_Mixer_StreamCreate.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
    ]
    dll.BASS_Mixer_StreamCreate.restype = ctypes.c_ulong

    # BASS_Mixer_StreamAddChannel(mixer, channel, flags) -> BOOL
    dll.BASS_Mixer_StreamAddChannel.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
    ]
    dll.BASS_Mixer_StreamAddChannel.restype = ctypes.c_bool

    # BASS_Mixer_ChannelRemove(channel) -> BOOL
    dll.BASS_Mixer_ChannelRemove.argtypes = [ctypes.c_ulong]
    dll.BASS_Mixer_ChannelRemove.restype = ctypes.c_bool

    # BASS_Mixer_ChannelGetMixer(channel) -> HSTREAM (0 = not in any mixer)
    dll.BASS_Mixer_ChannelGetMixer.argtypes = [ctypes.c_ulong]
    dll.BASS_Mixer_ChannelGetMixer.restype = ctypes.c_ulong

    # BASS_Mixer_ChannelGetPosition(channel, mode) -> position bytes
    dll.BASS_Mixer_ChannelGetPosition.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong,
    ]
    dll.BASS_Mixer_ChannelGetPosition.restype = ctypes.c_ulonglong

    # BASS_Mixer_ChannelSetPosition(channel, pos, mode) -> BOOL
    dll.BASS_Mixer_ChannelSetPosition.argtypes = [
        ctypes.c_ulong, ctypes.c_ulonglong, ctypes.c_ulong,
    ]
    dll.BASS_Mixer_ChannelSetPosition.restype = ctypes.c_bool

    # BASS_Mixer_ChannelFlags(channel, flags, mask) -> DWORD (effective flags)
    dll.BASS_Mixer_ChannelFlags.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
    ]
    dll.BASS_Mixer_ChannelFlags.restype = ctypes.c_ulong

    _mixer_dll = dll
    log.info(f"bassmix.dll loaded from {dll_path}")
    return _mixer_dll


def is_available() -> bool:
    """True iff bassmix.dll loaded successfully. Engines use this to
    decide between mixer routing and direct play during the Step 5
    migration window."""
    return get_mixer_dll() is not None
