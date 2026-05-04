"""
RadioAI Studio Pro — Instant Jingle Engine

Polyphonic BASS playback for the Instant Jingles screen. Multiple pads can
play simultaneously through the same BASS output device. Each pad gets its
own BASS stream handle; the engine tracks them in a dict so Stop All can
kill every channel at once and Latch can toggle a single pad on/off.

Design parallels SweeperEngine (overlay player) — same DLL handle pattern,
same volume-attribute write — but extended to N concurrent channels.

Polyphony cap: 8. BASS itself can handle far more, but UI scaling (and the
practical reality of a DJ overlapping more than 8 jingles in a live break)
makes higher counts a footgun. Clamp + warn rather than silently drop.
"""

import ctypes
import logging
import os
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from pybass3 import BassStream, BassChannel
import pybass3.bass_module as _bm

# Reuse the DLL loader + BASS_ATTRIB_VOL constant from AudioEngine — single
# source of truth for ctypes argtype declarations.
from core.audio_engine import _get_dll, BASS_ATTRIB_VOL, BASS_STREAM_PRESCAN

log = logging.getLogger("InstantJingleEngine")

# BASS_ChannelFlags() flag — loop the sample on EOF.
BASS_SAMPLE_LOOP = 4
# Magic value to ChannelFlags() that means "set/clear from this mask only".
_FLAGS_MASK_LOOP = BASS_SAMPLE_LOOP


class InstantJingleEngine(QObject):
    """Multi-channel jingle player.

    Usage::

        engine = InstantJingleEngine()
        engine.play_pad(pad_id=42, file_path='/path/x.mp3', volume=90, loop=False)
        engine.stop_pad(42)
        engine.stop_all()
    """

    # Emitted from the BASS callback thread (sync end-of-stream). Connect
    # with Qt.AutoConnection — Qt will marshal to the main thread.
    pad_started = pyqtSignal(int)   # pad_id
    pad_ended   = pyqtSignal(int)   # pad_id (stream finished naturally)
    pad_stopped = pyqtSignal(int)   # pad_id (stopped by user / stop_all)

    MAX_POLYPHONY = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dll = _get_dll()
        # pad_id -> BASS stream handle (int)
        self._channels: dict[int, int] = {}
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────

    def play_pad(self, pad_id: int, file_path: str,
                 volume: int = 100, loop: bool = False) -> bool:
        """Play a pad. Returns True if playback started.

        If the same pad_id is already playing, the existing channel is stopped
        first (re-trigger). If the polyphony cap is reached, the oldest
        channel is evicted to make room.
        """
        if not file_path:
            log.warning(f"[pad {pad_id}] no file_path — skipping")
            return False
        if not os.path.exists(file_path):
            log.warning(f"[pad {pad_id}] file missing: {file_path}")
            return False

        with self._lock:
            # Re-trigger: stop existing channel for this pad
            if pad_id in self._channels:
                self._stop_handle(self._channels[pad_id])
                del self._channels[pad_id]

            # Polyphony cap — evict oldest (insertion order) if full
            if len(self._channels) >= self.MAX_POLYPHONY:
                oldest_id, oldest_handle = next(iter(self._channels.items()))
                log.warning(
                    f"polyphony cap reached ({self.MAX_POLYPHONY}); "
                    f"evicting pad {oldest_id}"
                )
                self._stop_handle(oldest_handle)
                del self._channels[oldest_id]
                self.pad_stopped.emit(int(oldest_id))

            # Create the stream
            try:
                handle = BassStream.CreateFile(
                    False, file_path.encode("utf-8"), 0, 0, BASS_STREAM_PRESCAN
                )
            except Exception as exc:
                err = _bm.BASS_ErrorGetCode()
                log.error(f"[pad {pad_id}] BASS_StreamCreateFile error {err}: {exc}")
                return False

            # Set volume
            v = max(0, min(100, int(volume))) / 100.0
            self._dll.BASS_ChannelSetAttribute(
                int(handle), BASS_ATTRIB_VOL, ctypes.c_float(v)
            )

            # Loop flag (best-effort — BASS_ChannelFlags isn't in pybass3 always)
            if loop:
                try:
                    if hasattr(self._dll, "BASS_ChannelFlags"):
                        self._dll.BASS_ChannelFlags.argtypes = [
                            ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong
                        ]
                        self._dll.BASS_ChannelFlags.restype = ctypes.c_ulong
                        self._dll.BASS_ChannelFlags(
                            int(handle), BASS_SAMPLE_LOOP, _FLAGS_MASK_LOOP
                        )
                except Exception as exc:
                    log.warning(f"[pad {pad_id}] could not set LOOP flag: {exc}")

            # Play
            BassChannel.Play(int(handle), False)
            self._channels[pad_id] = int(handle)
            log.info(
                f"[pad {pad_id}] playing {os.path.basename(file_path)} "
                f"vol={volume} loop={loop}"
            )

        self.pad_started.emit(int(pad_id))
        return True

    def stop_pad(self, pad_id: int) -> bool:
        """Stop a specific pad. Returns True if it was playing."""
        with self._lock:
            handle = self._channels.pop(pad_id, None)
        if handle is None:
            return False
        self._stop_handle(handle)
        log.info(f"[pad {pad_id}] stopped")
        self.pad_stopped.emit(int(pad_id))
        return True

    def stop_all(self) -> int:
        """Emergency stop — kills every channel. Returns count stopped."""
        with self._lock:
            ids = list(self._channels.keys())
            for pid, handle in self._channels.items():
                self._stop_handle(handle)
            self._channels.clear()
        for pid in ids:
            self.pad_stopped.emit(int(pid))
        log.warning(f"STOP ALL — killed {len(ids)} channel(s)")
        return len(ids)

    def is_playing(self, pad_id: int) -> bool:
        return pad_id in self._channels

    def active_pad_ids(self) -> list[int]:
        with self._lock:
            return list(self._channels.keys())

    def get_duration_ms(self, file_path: str) -> Optional[int]:
        """Probe a file for its duration in milliseconds. Used by the
        editor's Assign Audio path so the duration can be cached."""
        if not file_path or not os.path.exists(file_path):
            return None
        try:
            handle = BassStream.CreateFile(
                False, file_path.encode("utf-8"), 0, 0, BASS_STREAM_PRESCAN
            )
        except Exception:
            return None
        try:
            # BASS_ChannelGetLength → bytes; convert via BASS_ChannelBytes2Seconds
            if not hasattr(self._dll, "BASS_ChannelGetLength"):
                self._dll.BASS_ChannelGetLength.argtypes = [
                    ctypes.c_ulong, ctypes.c_ulong
                ]
                self._dll.BASS_ChannelGetLength.restype = ctypes.c_ulonglong
            if not hasattr(self._dll, "BASS_ChannelBytes2Seconds"):
                self._dll.BASS_ChannelBytes2Seconds.argtypes = [
                    ctypes.c_ulong, ctypes.c_ulonglong
                ]
                self._dll.BASS_ChannelBytes2Seconds.restype = ctypes.c_double
            byte_len = self._dll.BASS_ChannelGetLength(int(handle), 0)
            seconds  = self._dll.BASS_ChannelBytes2Seconds(int(handle), byte_len)
            return int(round(seconds * 1000))
        except Exception:
            return None
        finally:
            try:
                self._stop_handle(int(handle))
            except Exception:
                pass

    # ── Internals ─────────────────────────────────────────────────────────

    def _stop_handle(self, handle) -> None:
        """Best-effort BASS_ChannelStop + BASS_StreamFree."""
        try:
            if not hasattr(self._dll, "BASS_ChannelStop"):
                self._dll.BASS_ChannelStop.argtypes = [ctypes.c_ulong]
                self._dll.BASS_ChannelStop.restype  = ctypes.c_bool
            if not hasattr(self._dll, "BASS_StreamFree"):
                self._dll.BASS_StreamFree.argtypes = [ctypes.c_ulong]
                self._dll.BASS_StreamFree.restype  = ctypes.c_bool
            self._dll.BASS_ChannelStop(int(handle))
            self._dll.BASS_StreamFree(int(handle))
        except Exception as exc:
            log.warning(f"_stop_handle({handle}) error: {exc}")
