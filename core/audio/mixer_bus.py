"""
MixerBus — the single unified output bus for Phase 5.

Wraps one BASSmix mixer stream that every engine routes through. Each
audio engine (AudioEngine, SweeperEngine, StitcherEngine,
InstantJingleEngine) creates its source streams with the
``BASS_STREAM_DECODE`` flag — they don't play to the device directly —
and adds them to this mixer via ``add_channel``. The mixer is the
only handle that actually plays audio to the output.

This file is **additive** for Step 5.1 — no engine references it yet.
Step 5.2 onwards begins opt-in integration.

Graceful degradation
--------------------
If ``bassmix.dll`` is not installed (Step 5.0 README explains how),
``MixerBus.is_available()`` returns False and ``create()`` returns
None. Callers MUST treat None as "no mixer; use legacy direct-play
path" — the safety contract for the migration window.

Threading
---------
``add_channel`` / ``remove_channel`` are safe to call from any thread
per BASS docs. The mixer's internal audio thread is decoupled from
Qt's main thread — sample-accurate timing is preserved.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from pybass3 import BassChannel

from core.audio._bass import (
    BASS_ATTRIB_VOL, BASS_POS_BYTE,
    error_code,
)
from core.audio._bassmix import (
    BASS_MIXER_NONSTOP, BASS_MIXER_POSEX,
    BASS_MIXER_CHAN_NORAMPIN,
    get_mixer_dll, is_available as mixer_available,
)

log = logging.getLogger("MixerBus")


class MixerBus(QObject):
    """Singleton output bus. One instance per process.

    The mixer is configured with:
      • BASS_MIXER_NONSTOP — never auto-stops even when all sources
        finish. Critical for radio: a silence gap is fine, the device
        stays open, the next item is added without restart latency.
      • BASS_MIXER_RESUME — auto-resume when a channel is added (in
        case the operator paused playback and a new dispatch arrives).
      • Mixer rate 48000 Hz, 2 channels (stereo). BASSmix resamples
        any source to match.

    Public API (all methods are no-ops when the mixer isn't available):
      create()        — initialise the mixer stream (call once at startup)
      add_channel(h)  — attach an HSTREAM (created with BASS_STREAM_DECODE)
      remove_channel(h) — detach
      play()          — start the mixer playing to output
      stop()          — stop the mixer
      set_master_volume(0..100)
      cleanup()       — free the mixer (called at app shutdown)
      is_attached(h)  — True if handle h is currently in this mixer
      is_available()  — staticmethod, mirrors core.audio._bassmix.is_available
    """

    # ── Public signals (reserved for future steps; not emitted yet) ──────
    state_changed     = pyqtSignal(str)    # "created", "playing", "stopped", "freed"

    # ── Constants ────────────────────────────────────────────────────────
    # IMPORTANT: must match the BASS device sample rate (`bass_init`
    # uses 44100 Hz). A mismatch (e.g. mixer at 48000 Hz + device at
    # 44100 Hz) makes every source play 48000/44100 ≈ 9% FASTER plus
    # buffer underruns ("atak atak ke chal raha hai") because the
    # device consumes samples slower than the mixer produces them.
    # Caller can override via create(rate=...) if bass_init was given
    # a non-default rate.
    DEFAULT_RATE     = 44100
    DEFAULT_CHANNELS = 2

    # ── Singleton ────────────────────────────────────────────────────────
    _instance: Optional["MixerBus"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "MixerBus":
        """Return the process-wide singleton. Lazy-creates the wrapper
        object. The BASS mixer stream itself is NOT created here —
        callers must invoke ``create()`` explicitly during app
        initialisation (typically right after bass_init())."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ── Lifecycle ────────────────────────────────────────────────────────

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dll = get_mixer_dll()       # None if bassmix.dll missing
        self._mixer_handle: Optional[int] = None
        self._channels: set[int] = set()
        self._master_volume: int = 100
        self._lock = threading.Lock()

    @staticmethod
    def is_available() -> bool:
        """True iff bassmix.dll is loaded and we can create a mixer.
        Used by engines + Studio to decide between mixer routing and
        legacy direct-play during the Step 5 migration window."""
        return mixer_available()

    def create(self, rate: int = DEFAULT_RATE,
               channels: int = DEFAULT_CHANNELS) -> Optional[int]:
        """Create the BASS mixer stream. Idempotent — second call
        returns the existing handle. Returns the HSTREAM, or None
        when bassmix.dll is unavailable (legacy-path fallback)."""
        if self._dll is None:
            log.info("create() skipped — bassmix.dll not loaded")
            return None
        with self._lock:
            if self._mixer_handle is not None:
                return self._mixer_handle
            # NONSTOP keeps the mixer running across silent gaps —
            # essential for a broadcast bus (no device-restart latency
            # between songs). POSEX makes per-source position queries
            # accurate so the progress bar tracks correctly inside a
            # mixed stream. No "resume" flag is needed; BASSmix
            # automatically plays added channels unless the
            # BASS_MIXER_CHAN_PAUSE flag is set on the channel itself.
            flags = BASS_MIXER_NONSTOP | BASS_MIXER_POSEX
            handle = self._dll.BASS_Mixer_StreamCreate(
                ctypes.c_ulong(int(rate)),
                ctypes.c_ulong(int(channels)),
                ctypes.c_ulong(int(flags)),
            )
            if not handle:
                err = error_code()
                log.warning(
                    f"BASS_Mixer_StreamCreate failed err={err} "
                    f"rate={rate} ch={channels}")
                return None
            self._mixer_handle = int(handle)
            # Set master volume so the cached value is applied.
            self._apply_master_volume_locked()
            log.info(
                f"MixerBus created handle={self._mixer_handle} "
                f"rate={rate} ch={channels}")
        # Explicitly start the mixer playing. Critical: without this
        # the mixer never pulls data from sources → device output
        # underruns → audible stutter ("atak atak"). BASS_MIXER_NONSTOP
        # keeps it running across silent gaps (no source attached).
        try:
            BassChannel.Play(self._mixer_handle, False)
        except Exception as exc:
            log.warning(f"MixerBus initial Play failed: {exc}")
        self.state_changed.emit("created")
        return self._mixer_handle

    def handle(self) -> Optional[int]:
        """Current mixer HSTREAM, or None if not yet created."""
        return self._mixer_handle

    # ── Channel routing ──────────────────────────────────────────────────

    def add_channel(self, channel_id: int, *, paused: bool = False) -> bool:
        """Attach a decode-only HSTREAM to the mixer. The stream must
        have been created with ``BASS_STREAM_DECODE`` — the engine's
        load_file path handles that flag when route_via_mixer=True.

        Returns True on success. False on:
          • mixer not available (bassmix.dll missing)
          • mixer not yet created (caller must invoke create() first)
          • underlying BASS_Mixer_StreamAddChannel error

        Idempotent: re-adding a handle that's already in the mixer
        returns True without re-attaching (BASS returns its own error
        in that case; we treat it as success)."""
        if self._dll is None or self._mixer_handle is None:
            return False
        if channel_id in self._channels:
            return True
        flags = 0
        if paused:
            from core.audio._bassmix import BASS_MIXER_CHAN_PAUSE
            flags |= BASS_MIXER_CHAN_PAUSE
        # Don't ramp newly-added channels — fades are explicit per-channel
        # via fade_volume_to / BASS_ChannelSlideAttribute.
        flags |= BASS_MIXER_CHAN_NORAMPIN
        # 2026-05-17 stutter fix (per ChatGPT analysis + BASSmix docs):
        # allocate a per-source buffer inside the mixer. Without this
        # flag, BASS_Mixer_ChannelGetPosition forces the mixer's audio
        # thread to compute byte offsets synchronously against live mix
        # state. Our 100ms Python QTimer position poll then locks the
        # mixer thread long enough to cause device underruns → audible
        # micro-cuts ("atak-atak" stutter operator reported). The flag
        # gives the mixer a dedicated read-buffer so position queries
        # are instant.
        from core.audio._bassmix import BASS_MIXER_CHAN_BUFFER
        flags |= BASS_MIXER_CHAN_BUFFER
        ok = self._dll.BASS_Mixer_StreamAddChannel(
            ctypes.c_ulong(self._mixer_handle),
            ctypes.c_ulong(int(channel_id)),
            ctypes.c_ulong(flags),
        )
        if not ok:
            err = error_code()
            log.warning(
                f"add_channel({channel_id}) failed err={err}")
            return False
        with self._lock:
            self._channels.add(int(channel_id))
        log.debug(f"add_channel({channel_id}) → mixer={self._mixer_handle}")
        return True

    def remove_channel(self, channel_id: int) -> bool:
        """Detach a channel from the mixer. Idempotent on unknown ids.
        Note that BASS_Mixer_ChannelRemove does NOT free the underlying
        stream — caller still needs BASS_StreamFree."""
        if self._dll is None:
            return False
        if channel_id not in self._channels:
            return True   # idempotent
        ok = self._dll.BASS_Mixer_ChannelRemove(
            ctypes.c_ulong(int(channel_id)))
        with self._lock:
            self._channels.discard(int(channel_id))
        if not ok:
            err = error_code()
            log.debug(
                f"remove_channel({channel_id}) BASS_Mixer_ChannelRemove "
                f"returned 0 err={err} (channel may already be gone)")
        return True

    def is_attached(self, channel_id: int) -> bool:
        """True if the channel is currently routed through this mixer."""
        return channel_id in self._channels

    def attached_channels(self) -> list[int]:
        """Snapshot of currently-attached channel ids."""
        with self._lock:
            return sorted(self._channels)

    # ── Transport ────────────────────────────────────────────────────────

    def play(self) -> None:
        """Start the mixer stream playing to the output device. Idempotent."""
        if self._mixer_handle is None:
            return
        try:
            BassChannel.Play(self._mixer_handle, False)
        except Exception as exc:
            log.warning(f"play() failed: {exc}")
            return
        self.state_changed.emit("playing")

    def stop(self) -> None:
        """Stop the mixer. Attached channels remain attached; calling
        play() resumes playback. Use cleanup() for full teardown."""
        if self._mixer_handle is None:
            return
        try:
            BassChannel.Stop(self._mixer_handle)
        except Exception as exc:
            log.warning(f"stop() failed: {exc}")
            return
        self.state_changed.emit("stopped")

    # ── Master volume ────────────────────────────────────────────────────

    def set_master_volume(self, volume: int) -> None:
        """0..100, clamped. Affects the mixer output; per-channel
        volumes set via AudioEngine.set_volume / fade_volume_to are
        still applied to the source streams BEFORE the mixer adds
        them up — so per-channel fades remain operator-visible."""
        v = max(0, min(100, int(volume)))
        with self._lock:
            self._master_volume = v
            self._apply_master_volume_locked()

    def get_master_volume(self) -> int:
        return self._master_volume

    def _apply_master_volume_locked(self) -> None:
        """Push the cached volume onto the mixer handle. Called from
        create() and set_master_volume() with _lock held."""
        if self._dll is None or self._mixer_handle is None:
            return
        # Use the base BASS DLL to set the mixer's own attribute —
        # BASS_ChannelSetAttribute works on mixer streams.
        from core.audio._bass import get_dll as _get_bass_dll
        try:
            _get_bass_dll().BASS_ChannelSetAttribute(
                ctypes.c_ulong(self._mixer_handle),
                ctypes.c_ulong(BASS_ATTRIB_VOL),
                ctypes.c_float(self._master_volume / 100.0),
            )
        except Exception as exc:
            log.debug(f"set master volume failed: {exc}")

    # ── Per-source pause/resume (Phase 5.2 fix 2026-05-17) ───────────────

    # Slide-pause pattern (2026-05-17 ChatGPT-confirmed): pure
    # CHAN_PAUSE leaves the mixer's 500ms output buffer playing — the
    # listener hears audio for 500ms after pause is pressed. To
    # achieve clean audible pause we slide volume to 0 over a short
    # ramp FIRST so the buffer drains as silence, then set CHAN_PAUSE
    # to stop the mixer from pulling more data.
    _PAUSE_SLIDE_MS = 60

    def pause_source(self, channel_id: int) -> bool:
        """Pause one source within the mixer:
          1. Slide its volume to 0 over ~60ms (drains the mixer's
             output buffer audibly cleanly)
          2. After the slide, set BASS_MIXER_CHAN_PAUSE so the mixer
             stops pulling data from this source
        Caller should cache the pre-pause volume separately if
        needed for resume — this method does not preserve it.
        Returns True when both steps were attempted."""
        if self._dll is None or channel_id not in self._channels:
            return False
        from core.audio._bass import BASS_ATTRIB_VOL, get_dll as _bass_dll
        from core.audio._bassmix import BASS_MIXER_CHAN_PAUSE
        # Step 1: slide the source's volume down to 0 quickly. This
        # affects the data the mixer is about to pull from the source.
        try:
            _bass_dll().BASS_ChannelSlideAttribute(
                ctypes.c_ulong(int(channel_id)),
                ctypes.c_ulong(BASS_ATTRIB_VOL),
                ctypes.c_float(0.0),
                ctypes.c_ulong(int(self._PAUSE_SLIDE_MS)),
            )
        except Exception as exc:
            log.debug(f"pause_source slide failed: {exc}")
        # Step 2: apply CHAN_PAUSE after a slight delay so the slide
        # has time to drain the buffer. QTimer.singleShot is on the
        # Qt main thread; the BASS_Mixer_ChannelFlags call is
        # cross-thread safe.
        try:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(
                int(self._PAUSE_SLIDE_MS + 10),
                lambda h=int(channel_id): self._apply_chan_pause(h, True))
        except Exception as exc:
            # Fallback: apply pause flag synchronously
            log.debug(f"pause_source QTimer fallback: {exc}")
            self._apply_chan_pause(int(channel_id), True)
        return True

    def resume_source(self, channel_id: int,
                       target_volume_pct: int = 100) -> bool:
        """Resume a previously-paused source:
          1. Clear BASS_MIXER_CHAN_PAUSE (mixer resumes pulling)
          2. Slide volume back up to ``target_volume_pct`` over ~60ms
             (audibly clean fade-in instead of pop)
        """
        if self._dll is None or channel_id not in self._channels:
            return False
        self._apply_chan_pause(int(channel_id), False)
        from core.audio._bass import BASS_ATTRIB_VOL, get_dll as _bass_dll
        try:
            _bass_dll().BASS_ChannelSlideAttribute(
                ctypes.c_ulong(int(channel_id)),
                ctypes.c_ulong(BASS_ATTRIB_VOL),
                ctypes.c_float(max(0.0, min(1.0, target_volume_pct / 100.0))),
                ctypes.c_ulong(int(self._PAUSE_SLIDE_MS)),
            )
        except Exception as exc:
            log.debug(f"resume_source slide failed: {exc}")
        return True

    def _apply_chan_pause(self, channel_id: int, paused: bool) -> None:
        """Internal: set or clear the BASS_MIXER_CHAN_PAUSE flag."""
        if self._dll is None:
            return
        from core.audio._bassmix import BASS_MIXER_CHAN_PAUSE
        try:
            self._dll.BASS_Mixer_ChannelFlags(
                ctypes.c_ulong(int(channel_id)),
                ctypes.c_ulong(BASS_MIXER_CHAN_PAUSE if paused else 0),
                ctypes.c_ulong(BASS_MIXER_CHAN_PAUSE),
            )
        except Exception as exc:
            log.debug(f"_apply_chan_pause failed: {exc}")

    # ── Cleanup ──────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Free the mixer and clear attached-channel tracking. Call at
        app shutdown BEFORE bass_free(). The engines own their own
        source streams — they free those separately."""
        if self._dll is None:
            return
        with self._lock:
            handle = self._mixer_handle
            self._mixer_handle = None
            self._channels.clear()
        if handle is None:
            return
        try:
            # The mixer is a BASS stream — free via the standard path.
            from pybass3 import BassStream
            BassChannel.Stop(handle)
            BassStream.Free(handle)
        except Exception as exc:
            log.warning(f"cleanup() failed: {exc}")
        log.info("MixerBus freed")
        self.state_changed.emit("freed")
