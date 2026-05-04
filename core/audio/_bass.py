"""
Private BASS plumbing for core.audio.

Loads the BASS DLL once via pybass3's bundled path and declares ctypes
argtypes/restypes for the BASS functions the new AudioEngine needs but
pybass3 doesn't wrap.

This module is intentionally independent of core.audio_engine — the new
engine should not have a hidden import dependency on the legacy module.
Both modules call the same underlying BASS DLL (BASS_Init is process-global)
and BASS happily reports BASS_ERROR_ALREADY (code 8) on a second init, so
they coexist cleanly.
"""

from __future__ import annotations

import ctypes
from typing import Optional

import pybass3.bass_module as _bm


# ── BASS constants ──────────────────────────────────────────────────────────

BASS_STREAM_PRESCAN   = 0x20000        # accurate duration: scan the file once
BASS_ATTRIB_VOL       = 2              # per-channel volume attribute (0.0–1.0)
BASS_SYNC_END         = 2              # sync type: end-of-stream
BASS_SYNC_ONETIME     = 0x80000000     # fire sync callback only once
BASS_POS_BYTE         = 0              # GetLength / SetPosition mode: bytes
BASS_SAMPLE_LOOP      = 4              # stream creation flag — loop on EOF


# ── ctypes typedefs ─────────────────────────────────────────────────────────

# SYNCPROC signature — see BASS docs.
SYNCPROC = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_ulong,    # handle
    ctypes.c_ulong,    # channel
    ctypes.c_ulong,    # data
    ctypes.c_void_p,   # user
)


# ── DLL singleton ───────────────────────────────────────────────────────────

_dll: Optional[ctypes.WinDLL] = None


def get_dll() -> ctypes.WinDLL:
    """Return the BASS DLL, loaded once with the argtypes we need.

    This is a process-global singleton — callers from any thread get the
    same WinDLL handle. Argtypes are declared here for every BASS function
    the new AudioEngine calls so ctypes does no implicit int conversion at
    each call site.
    """
    global _dll
    if _dll is not None:
        return _dll

    dll = ctypes.WinDLL(str(_bm.BASS_DLL))

    # Volume / attribute control
    dll.BASS_ChannelSetAttribute.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_float
    ]
    dll.BASS_ChannelSetAttribute.restype = ctypes.c_bool

    dll.BASS_ChannelGetAttribute.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.c_float)
    ]
    dll.BASS_ChannelGetAttribute.restype = ctypes.c_bool

    dll.BASS_ChannelSlideAttribute.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_float, ctypes.c_ulong
    ]
    dll.BASS_ChannelSlideAttribute.restype = ctypes.c_bool

    # End-of-stream sync callbacks
    dll.BASS_ChannelSetSync.argtypes = [
        ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulonglong,
        SYNCPROC, ctypes.c_void_p,
    ]
    dll.BASS_ChannelSetSync.restype = ctypes.c_ulong

    dll.BASS_ChannelRemoveSync.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    dll.BASS_ChannelRemoveSync.restype = ctypes.c_bool

    # Position / duration helpers (used by Day A2 — declare now so the
    # engine module doesn't have to redo it)
    dll.BASS_ChannelGetLength.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    dll.BASS_ChannelGetLength.restype = ctypes.c_ulonglong

    dll.BASS_ChannelGetPosition.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    dll.BASS_ChannelGetPosition.restype = ctypes.c_ulonglong

    dll.BASS_ChannelSetPosition.argtypes = [
        ctypes.c_ulong, ctypes.c_ulonglong, ctypes.c_ulong
    ]
    dll.BASS_ChannelSetPosition.restype = ctypes.c_bool

    dll.BASS_ChannelBytes2Seconds.argtypes = [
        ctypes.c_ulong, ctypes.c_ulonglong
    ]
    dll.BASS_ChannelBytes2Seconds.restype = ctypes.c_double

    dll.BASS_ChannelSeconds2Bytes.argtypes = [
        ctypes.c_ulong, ctypes.c_double
    ]
    dll.BASS_ChannelSeconds2Bytes.restype = ctypes.c_ulonglong

    _dll = dll
    return _dll


def error_code() -> int:
    """Last BASS error code (0 = no error)."""
    return int(_bm.BASS_ErrorGetCode())
