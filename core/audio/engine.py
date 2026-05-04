"""
RadioAI Studio Pro — Multi-channel AudioEngine (Phase A1).

A QObject-based BASS player that manages up to MAX_CHANNELS independent
streams through a single BASS output device. Each load_file returns a
never-reused channel id; subsequent play / pause / resume / stop / cleanup
calls reference the channel by that id.

Phase A roadmap:
  A1 — architecture + single channel: load_file, play, pause, resume, stop,
       cleanup, cleanup_all. Per-channel EOS sync callback bridges to Qt.
       Position polling timer is created but inert (A2 starts it).
  A2 — position + volume + seek (shared QTimer drives position_changed).
  A3 — multi-channel polish (concurrent play, polyphony cap eviction).
  A4 — tag reading via mutagen (separate TagReader module).
  A5 — polish + tests + Phase A complete.

Threading model
---------------
BASS_ChannelSetSync invokes its callback from a BASS internal thread —
NEVER call Qt or DB from inside the C callback. The callback emits a
private pyqtSignal (`_stream_ended_internal`) which Qt automatically
queues onto the engine's owning thread (Qt main thread by default), where
`_on_stream_ended_main` then mutates state and emits the public signals.

BASS lifecycle
--------------
This engine does NOT call BASS_Init / BASS_Free. main.py owns that via
core.audio_engine.bass_init / bass_free (the canonical, single-process
device). Instantiate this engine after bass_init() has run.
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal

from pybass3 import BassStream, BassChannel

from core.audio._bass import (
    BASS_ATTRIB_VOL, BASS_STREAM_PRESCAN,
    BASS_SYNC_END, BASS_SYNC_ONETIME,
    SYNCPROC, get_dll, error_code,
)
from core.audio.channels import Channel, CHANNEL_STATES
from core.audio.exceptions import (
    AudioEngineError, ChannelError, FormatError,
)

log = logging.getLogger("AudioEngine")


class AudioEngine(QObject):
    """Multi-channel BASS player with PyQt6 signals.

    Up to MAX_CHANNELS streams can be loaded concurrently. Channel ids are
    monotonic and never reused — once a channel is cleaned up its id is
    permanently retired, which prevents stale-id confusion in UI consumers.
    """

    # ── Public signals ────────────────────────────────────────────────────
    #
    # position_changed   — A2 will start emitting (channel_id, position_ms)
    # playback_ended     — natural end-of-stream (sync callback fired)
    # error_occurred     — recoverable per-channel error (e.g. seek failed)
    # channel_state_changed — every state transition: loaded/playing/paused/
    #                         stopped/ended/error

    position_changed      = pyqtSignal(int, int)   # (channel_id, position_ms)
    playback_ended        = pyqtSignal(int)        # channel_id
    error_occurred        = pyqtSignal(int, str)   # (channel_id, message)
    channel_state_changed = pyqtSignal(int, str)   # (channel_id, state)

    # ── Internal bridge ───────────────────────────────────────────────────
    #
    # The BASS sync callback fires from BASS's internal thread. Emitting a
    # pyqtSignal across threads with Qt.AutoConnection becomes a queued
    # delivery to the receiver's thread (engine's owning thread = Qt main
    # thread by default). The slot then mutates state safely.

    _stream_ended_internal = pyqtSignal(int)       # channel_id

    # ── Constants ─────────────────────────────────────────────────────────

    MAX_CHANNELS        = 8
    POSITION_UPDATE_MS  = 100

    # ─────────────────────────────────────────────────────────────────────

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dll = get_dll()
        self._channels: dict[int, Channel] = {}
        self._lock = threading.Lock()
        # Monotonic, never-reused. Starts at 1 — 0 is sentinel for "invalid".
        self._next_id: int = 1

        # Cross-thread bridge: BASS callback thread → Qt main thread.
        # AutoConnection on a different-thread emit becomes QueuedConnection.
        self._stream_ended_internal.connect(
            self._on_stream_ended_main,
            Qt.ConnectionType.QueuedConnection,
        )

        # Shared position-poll timer. A1 leaves it inert; A2 starts it and
        # connects timeout to a polling slot. Single timer for all channels
        # (cheaper than one timer each).
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POSITION_UPDATE_MS)
        # self._poll_timer.timeout.connect(self._poll_all)   # ← Phase A2

        log.info("AudioEngine initialised (multi-channel BASS)")

    # ── Public API: load / playback control ───────────────────────────────

    def load_file(self, path: str) -> int:
        """Open `path` as a BASS stream. Returns the new channel id.

        Raises:
            AudioEngineError — if path missing/empty, capacity reached, or
                               BASS fails to create the stream.
        """
        if not path:
            raise AudioEngineError("file path is empty")
        if not os.path.exists(path):
            raise AudioEngineError(f"file not found: {path}")

        with self._lock:
            if len(self._channels) >= self.MAX_CHANNELS:
                raise AudioEngineError(
                    f"channel cap reached ({self.MAX_CHANNELS}); "
                    f"cleanup an existing channel before loading another"
                )

            try:
                handle = BassStream.CreateFile(
                    False, path.encode("utf-8"),
                    0, 0,
                    BASS_STREAM_PRESCAN,
                )
            except Exception as exc:
                err = error_code()
                # BASS_ERROR_FILEFORM (41) and BASS_ERROR_CODEC (44) → FormatError;
                # everything else surfaces as AudioEngineError.
                msg = (f"BASS_StreamCreateFile failed (err {err}): {exc}; "
                       f"path={path!r}")
                if err in (41, 44):
                    raise FormatError(msg) from exc
                raise AudioEngineError(msg) from exc

            handle = int(handle)

            # Default volume = 100% (1.0). Per-channel; doesn't affect others.
            self._dll.BASS_ChannelSetAttribute(
                handle, BASS_ATTRIB_VOL, ctypes.c_float(1.0)
            )

            # Allocate id BEFORE wiring sync, so the callback can capture it.
            channel_id = self._next_id
            self._next_id += 1

            # Per-channel SYNCPROC. Pin the ref on the Channel so ctypes
            # doesn't garbage-collect the closure mid-playback.
            sync_cb = self._make_sync_cb(channel_id)
            sync_handle = self._dll.BASS_ChannelSetSync(
                handle,
                BASS_SYNC_END | BASS_SYNC_ONETIME,
                0,
                sync_cb,
                None,
            )

            ch = Channel(
                id=channel_id,
                handle=handle,
                file_path=path,
                state="loaded",
                volume=100,
                sync_cb=sync_cb,
                sync_handle=int(sync_handle) if sync_handle else 0,
            )
            self._channels[channel_id] = ch

        self.channel_state_changed.emit(channel_id, "loaded")
        log.info(f"[ch {channel_id}] loaded {os.path.basename(path)}")
        return channel_id

    def play(self, channel_id: int) -> None:
        ch = self._require_channel(channel_id)
        # Restart from beginning: BASS_ChannelPlay(restart=False) resumes from
        # current position, which is fine for both loaded and paused states.
        BassChannel.Play(ch.handle, False)
        ch.state = "playing"
        self.channel_state_changed.emit(channel_id, "playing")
        log.info(f"[ch {channel_id}] playing")

    def pause(self, channel_id: int) -> None:
        ch = self._require_channel(channel_id)
        BassChannel.Pause(ch.handle)
        ch.state = "paused"
        self.channel_state_changed.emit(channel_id, "paused")
        log.info(f"[ch {channel_id}] paused")

    def resume(self, channel_id: int) -> None:
        """Resume a paused channel. No-op if not currently paused."""
        ch = self._require_channel(channel_id)
        if ch.state != "paused":
            return
        BassChannel.Resume(ch.handle)
        ch.state = "playing"
        self.channel_state_changed.emit(channel_id, "playing")
        log.info(f"[ch {channel_id}] resumed")

    def stop(self, channel_id: int) -> None:
        """Manual stop. Distinct from natural end-of-stream (which emits
        playback_ended via the sync callback). Stopping a channel does NOT
        free its stream — the caller must still call cleanup() when done."""
        ch = self._require_channel(channel_id)
        BassChannel.Stop(ch.handle)
        ch.state = "stopped"
        self.channel_state_changed.emit(channel_id, "stopped")
        log.info(f"[ch {channel_id}] stopped")

    # ── Public API: queries ───────────────────────────────────────────────

    def is_playing(self, channel_id: int) -> bool:
        ch = self._channels.get(channel_id)
        return ch is not None and ch.state == "playing"

    def get_state(self, channel_id: int) -> str:
        """Return current state, or 'stopped' if the channel is unknown."""
        ch = self._channels.get(channel_id)
        return ch.state if ch else "stopped"

    def active_channels(self) -> list[int]:
        with self._lock:
            return list(self._channels.keys())

    # ── Public API: cleanup ───────────────────────────────────────────────

    def cleanup(self, channel_id: int) -> None:
        """Stop the channel, unhook its sync callback, free the BASS stream,
        and drop it from the active map. Idempotent on unknown ids."""
        with self._lock:
            ch = self._channels.pop(channel_id, None)
        if ch is None:
            return
        try:
            if ch.sync_handle:
                self._dll.BASS_ChannelRemoveSync(ch.handle, ch.sync_handle)
            BassChannel.Stop(ch.handle)
            BassStream.Free(ch.handle)
        except Exception as exc:
            log.warning(f"[ch {channel_id}] cleanup error: {exc}")
        log.info(f"[ch {channel_id}] cleaned up")

    def cleanup_all(self) -> None:
        """Cleanup every active channel. Safe to call at shutdown."""
        with self._lock:
            ids = list(self._channels.keys())
        for cid in ids:
            self.cleanup(cid)

    # ── Internals ─────────────────────────────────────────────────────────

    def _require_channel(self, channel_id: int) -> Channel:
        ch = self._channels.get(channel_id)
        if ch is None:
            raise ChannelError(f"channel {channel_id} not found")
        return ch

    def _make_sync_cb(self, channel_id: int):
        """Create a SYNCPROC bound to a specific channel id.

        BASS invokes this from its internal thread — we MUST NOT touch Qt
        or DB here. The closure emits a private signal which Qt queues
        onto the main thread for `_on_stream_ended_main` to handle.
        """
        engine_ref = self  # captured by closure

        def _cb(handle, channel, data, user):
            try:
                engine_ref._stream_ended_internal.emit(channel_id)
            except Exception:
                # Swallow — the BASS thread cannot raise back into Python
                # without crashing the host process.
                pass

        return SYNCPROC(_cb)

    def _on_stream_ended_main(self, channel_id: int) -> None:
        """Runs on the Qt main thread (queued from BASS callback). Safe to
        mutate engine state and emit public signals."""
        ch = self._channels.get(channel_id)
        if ch is None or ch.state == "ended":
            return
        ch.state = "ended"
        self.channel_state_changed.emit(channel_id, "ended")
        self.playback_ended.emit(channel_id)
        log.info(f"[ch {channel_id}] ended (natural EOS)")
