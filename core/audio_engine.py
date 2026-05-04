"""
RadioAI Studio Pro — Audio Engine (BASS via pybass3)
Single-deck playback with:
- BASS_Init on startup (global singleton, shared by stitcher/sweeper)
- BASS_StreamCreateFile → BASS_ChannelPlay
- 250ms QTimer position polling
- BASS_ChannelSetSync end-of-stream callback → Qt bridge (same pattern as VLC)
- BASS_ChannelSlideAttribute crossfade (volume slide, sample-accurate)
- All PyQt6 signals for UI consumption

BASS license: evaluation DLL (un4seen bundled in pybass3).
Purchase commercial license from un4seen.com before broadcast use.
"""

import ctypes
import logging
import os
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

import pybass3.bass_module as _bm
from pybass3 import BassStream, BassChannel
from pybass3.codes import channel as _ch

from core.constants import POSITION_POLL_MS, PRELOAD_BEFORE_END_MS

log = logging.getLogger("AudioEngine")

# ── BASS constants ────────────────────────────────────────────────────────────
BASS_STREAM_PRESCAN   = 0x20000   # scan whole file for duration accuracy
BASS_ATTRIB_VOL       = 2         # per-channel volume attribute (0.0 – 1.0)
BASS_SYNC_END         = 2         # sync type: end-of-stream
BASS_SYNC_ONETIME     = 0x80000000  # fire sync callback only once

# Callback type for BASS_ChannelSetSync
_SYNCPROC = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_ulong,   # handle
    ctypes.c_ulong,   # channel
    ctypes.c_ulong,   # data
    ctypes.c_void_p,  # user
)

# Load the BASS DLL directly for functions pybass3 doesn't wrap
_dll: Optional[ctypes.WinDLL] = None


def _get_dll() -> ctypes.WinDLL:
    global _dll
    if _dll is None:
        _dll = ctypes.WinDLL(str(_bm.BASS_DLL))
        _dll.BASS_ChannelSetAttribute.argtypes  = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_float]
        _dll.BASS_ChannelSetAttribute.restype   = ctypes.c_bool
        _dll.BASS_ChannelGetAttribute.argtypes  = [ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.c_float)]
        _dll.BASS_ChannelGetAttribute.restype   = ctypes.c_bool
        _dll.BASS_ChannelSlideAttribute.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_float, ctypes.c_ulong]
        _dll.BASS_ChannelSlideAttribute.restype = ctypes.c_bool
        _dll.BASS_ChannelIsSliding.argtypes     = [ctypes.c_ulong, ctypes.c_ulong]
        _dll.BASS_ChannelIsSliding.restype      = ctypes.c_bool
        _dll.BASS_ChannelSetSync.argtypes       = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulonglong, _SYNCPROC, ctypes.c_void_p]
        _dll.BASS_ChannelSetSync.restype        = ctypes.c_ulong
        _dll.BASS_ChannelRemoveSync.argtypes    = [ctypes.c_ulong, ctypes.c_ulong]
        _dll.BASS_ChannelRemoveSync.restype     = ctypes.c_bool
    return _dll


def bass_init(device: int = -1, freq: int = 44100) -> bool:
    """Initialize BASS output. Call once at app startup."""
    ok = _bm.BASS_Init(device, freq, 0, 0, None)
    if ok:
        log.info(f"BASS initialised: device={device} freq={freq}")
    else:
        err = _bm.BASS_ErrorGetCode()
        if err == 8:  # BASS_ERROR_ALREADY — already initialised, fine
            log.info("BASS already initialised")
            ok = True
        else:
            log.error(f"BASS_Init failed, error code: {err}")
    return ok


def bass_free() -> None:
    """Release BASS. Call at app shutdown."""
    _bm.BASS_Free()
    log.info("BASS released")


# ── AudioEngine ───────────────────────────────────────────────────────────────

class AudioEngine(QObject):
    """Single-deck BASS audio player with PyQt6 signals."""

    # ── Public signals ────────────────────────────────────────────────────────
    song_started     = pyqtSignal(dict)      # dict = item that started playing
    song_ended       = pyqtSignal(dict)      # dict = item that finished
    song_paused      = pyqtSignal()
    song_resumed     = pyqtSignal()
    position_changed = pyqtSignal(int, int)  # (position_ms, duration_ms)
    volume_changed   = pyqtSignal(int)       # 0–100
    queue_updated    = pyqtSignal(list)
    error_occurred   = pyqtSignal(str)
    preload_needed   = pyqtSignal()          # fires PRELOAD_BEFORE_END_MS before end

    # Internal bridge: BASS callback thread → Qt main thread
    _stream_ended = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._dll = _get_dll()
        self._handle: int = 0          # current BASS stream handle
        self._sync_handle: int = 0     # BASS sync handle (kept alive)
        self._sync_cb = None           # ctypes callback ref (must not be GC'd)
        self._current_item: Optional[dict] = None
        self._volume: int = 85         # 0–100
        self._is_playing: bool = False
        self._is_paused: bool = False
        self._preload_fired: bool = False

        # Bridge internal signal to Qt main thread handler
        self._stream_ended.connect(self._on_stream_ended_main)

        # 250ms poll timer
        self._timer = QTimer(self)
        self._timer.setInterval(POSITION_POLL_MS)
        self._timer.timeout.connect(self._poll)

        log.info("AudioEngine initialised (BASS)")

    # ── BASS sync callback (fires from BASS internal thread) ──────────────────

    def _make_sync_cb(self):
        """Create a ctypes SYNCPROC that emits our bridge signal."""
        def _cb(handle, channel, data, user):
            try:
                self._stream_ended.emit()
            except Exception:
                pass
        cb = _SYNCPROC(_cb)
        self._sync_cb = cb  # keep alive — ctypes callbacks are GC'd otherwise
        return cb

    # ── Qt main thread handler (safe to call Qt) ──────────────────────────────

    def _on_stream_ended_main(self):
        item = self._current_item or {}
        self._is_playing = False
        self._is_paused = False
        self._timer.stop()
        self._log_play(item)
        self.song_ended.emit(item)
        log.info(f"Ended: {item.get('artist','?')} — {item.get('title','?')}")

    # ── Position poll ─────────────────────────────────────────────────────────

    def _poll(self):
        if not self._handle:
            return
        try:
            pos_s = BassChannel.GetPositionSeconds(self._handle)
            dur_s = BassChannel.GetLengthSeconds(self._handle)
            pos_ms = int(pos_s * 1000)
            dur_ms = int(dur_s * 1000)
            self.position_changed.emit(pos_ms, dur_ms)

            # Preload trigger
            if (not self._preload_fired
                    and dur_ms > 0
                    and pos_ms > 0
                    and (dur_ms - pos_ms) <= PRELOAD_BEFORE_END_MS):
                self._preload_fired = True
                self.preload_needed.emit()

            # Fallback end detection (in case sync callback missed)
            state = BassChannel.IsActive(self._handle)
            if state == _ch.ACTIVE_STOPPED and self._is_playing:
                self._on_stream_ended_main()

        except Exception as exc:
            log.debug(f"Poll error: {exc}")

    # ── Playback ──────────────────────────────────────────────────────────────

    def play(self, item: dict) -> bool:
        """Load and play an audio item dict (must have 'file_path')."""
        path = item.get("file_path", "")
        if not path or not os.path.exists(path):
            msg = f"File not found: {path}"
            self.error_occurred.emit(msg)
            log.error(msg)
            return False

        self._stop_current()

        try:
            handle = BassStream.CreateFile(
                False,                      # mem=False → load from file
                path.encode("utf-8"),
                0, 0,
                BASS_STREAM_PRESCAN,
            )
        except Exception as exc:
            err = _bm.BASS_ErrorGetCode()
            msg = f"BASS stream create failed (err {err}): {exc}"
            self.error_occurred.emit(msg)
            log.error(msg)
            return False

        # Set volume before play
        self._dll.BASS_ChannelSetAttribute(handle, BASS_ATTRIB_VOL,
                                           ctypes.c_float(self._volume / 100.0))

        # Register end-of-stream sync callback
        cb = self._make_sync_cb()
        sync = self._dll.BASS_ChannelSetSync(
            handle, BASS_SYNC_END | BASS_SYNC_ONETIME, 0, cb, None
        )
        self._sync_handle = sync

        # Play
        ok = BassChannel.Play(handle, False)
        if not ok:
            err = _bm.BASS_ErrorGetCode()
            msg = f"BASS play failed (err {err})"
            self.error_occurred.emit(msg)
            log.error(msg)
            BassStream.Free(handle)
            return False

        self._handle = handle
        self._current_item = item
        self._is_playing = True
        self._is_paused = False
        self._preload_fired = False
        self._timer.start()

        self.song_started.emit(item)
        log.info(f"Playing: {item.get('artist','?')} — {item.get('title','?')} [{path}]")
        return True

    def stop(self) -> None:
        was_playing = self._is_playing
        item = self._current_item or {}
        self._stop_current()
        if was_playing:
            self.song_ended.emit(item)

    def pause(self) -> None:
        if self._is_playing and not self._is_paused and self._handle:
            BassChannel.Pause(self._handle)
            self._is_playing = False
            self._is_paused = True
            self._timer.stop()
            self.song_paused.emit()

    def resume(self) -> None:
        if self._is_paused and self._handle:
            BassChannel.Resume(self._handle)
            self._is_playing = True
            self._is_paused = False
            self._timer.start()
            self.song_resumed.emit()

    def seek(self, position_ms: int) -> None:
        if self._handle:
            try:
                BassChannel.SetPositionBySeconds(self._handle, position_ms / 1000.0)
            except Exception as exc:
                log.debug(f"Seek error: {exc}")

    def set_volume(self, volume: int) -> None:
        vol = max(0, min(100, volume))
        self._volume = vol
        if self._handle:
            self._dll.BASS_ChannelSetAttribute(
                self._handle, BASS_ATTRIB_VOL, ctypes.c_float(vol / 100.0)
            )
        self.volume_changed.emit(vol)

    def fade_to(self, target_vol: int, duration_ms: int = 3000) -> None:
        """Slide channel volume to target over duration_ms (crossfade helper)."""
        if self._handle:
            self._dll.BASS_ChannelSlideAttribute(
                self._handle, BASS_ATTRIB_VOL,
                ctypes.c_float(target_vol / 100.0),
                ctypes.c_ulong(duration_ms),
            )

    # ── State ─────────────────────────────────────────────────────────────────

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def current_item(self) -> Optional[dict]:
        return self._current_item

    @property
    def position_ms(self) -> int:
        if not self._handle:
            return 0
        try:
            return int(BassChannel.GetPositionSeconds(self._handle) * 1000)
        except Exception:
            return 0

    @property
    def duration_ms(self) -> int:
        if not self._handle:
            return 0
        try:
            return int(BassChannel.GetLengthSeconds(self._handle) * 1000)
        except Exception:
            return 0

    @property
    def volume(self) -> int:
        return self._volume

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _stop_current(self) -> None:
        self._timer.stop()
        self._is_playing = False
        self._is_paused = False
        if self._handle:
            try:
                if self._sync_handle:
                    self._dll.BASS_ChannelRemoveSync(self._handle, self._sync_handle)
                    self._sync_handle = 0
                BassChannel.Stop(self._handle)
                BassStream.Free(self._handle)
            except Exception as exc:
                log.debug(f"Stop/free error: {exc}")
            self._handle = 0
        self._sync_cb = None

    def _log_play(self, item: dict) -> None:
        if not item:
            return
        try:
            from core.database import Database
            db = Database()
            entry_type = item.get("type", "song")
            song_id = item.get("id") if entry_type == "song" else None
            db.log_play(
                entry_type=entry_type,
                song_id=song_id,
                campaign_id=item.get("campaign_id"),
                duration_ms=item.get("duration_secs", 0) * 1000,
                deck="A",
                was_manual=0,
            )
        except Exception as exc:
            log.debug(f"log_play error: {exc}")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Call at app exit before bass_free()."""
        self._stop_current()
        log.info("AudioEngine shutdown")
