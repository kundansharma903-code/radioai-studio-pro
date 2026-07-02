"""
RadioAI Studio Pro — Multi-channel AudioEngine (Phase A1).

A QObject-based BASS player that manages up to MAX_CHANNELS independent
streams through a single BASS output device. Each load_file returns a
never-reused channel id; subsequent play / pause / resume / stop / cleanup
calls reference the channel by that id.

Capacity behavior (Phase A3): when MAX_CHANNELS is reached, the oldest
channel (by insertion order — Python 3.7+ dicts preserve it) is
automatically evicted to make room. The eviction emits
channel_state_changed(oldest_id, "stopped") before cleanup so UI consumers
tracking the active set see a clean transition. This matches the
InstantJingleEngine precedent.

Phase A roadmap:
  A1 — architecture + single channel: load_file, play, pause, resume, stop,
       cleanup, cleanup_all. Per-channel EOS sync callback bridges to Qt.
  A2 — position + volume + seek: shared QTimer drives position_changed,
       seek_to_ms, set_volume (silent clamp), get_position_ms,
       get_duration_ms. Stop now resets position to 0; ended keeps at
       duration. Dual EOS detection (sync callback + poll fallback).
  A3 — multi-channel polish (concurrent play, polyphony cap eviction,
       fade_volume_to via BASS_ChannelSlideAttribute).
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
    BASS_ATTRIB_VOL, BASS_POS_BYTE, BASS_STREAM_PRESCAN, BASS_STREAM_DECODE,
    BASS_SAMPLE_LOOP,
    BASS_SYNC_POS, BASS_SYNC_END, BASS_SYNC_SLIDE, BASS_SYNC_ONETIME,
    BASS_SYNC_MIXTIME,
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

    Lifecycle contract (A5):
      - Caller MUST invoke cleanup_all() before BASS_Free / app shutdown.
      - The engine intentionally does NOT implement __del__ — Python GC
        ordering is unreliable with Qt teardown (BASS_Free may already
        have been called by the time the GC fires).
      - In Qt apps: hook MainWindow.closeEvent → engine.cleanup_all().
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
    # Phase 1 (2026-05-17) — sample-accurate BASS-driven transition events.
    # mix_point_reached fires when playback hits the byte position the
    # caller registered via set_position_sync. fade_completed fires when
    # a BASS_ChannelSlideAttribute (used by fade_volume_to) finishes its
    # ramp. Both replace the prior 250ms polling-based fade triggers in
    # Studio with sample-accurate notifications driven from BASS itself,
    # matching the Jazler / mAirList / RadioBoss industry pattern.
    mix_point_reached     = pyqtSignal(int)        # channel_id
    fade_completed        = pyqtSignal(int)        # channel_id

    # ── Internal bridge ───────────────────────────────────────────────────
    #
    # The BASS sync callback fires from BASS's internal thread. Emitting a
    # pyqtSignal across threads with Qt.AutoConnection becomes a queued
    # delivery to the receiver's thread (engine's owning thread = Qt main
    # thread by default). The slot then mutates state safely.

    _stream_ended_internal       = pyqtSignal(int)   # channel_id
    _mix_point_reached_internal  = pyqtSignal(int)   # channel_id
    _fade_completed_internal     = pyqtSignal(int)   # channel_id

    # ── Constants ─────────────────────────────────────────────────────────

    MAX_CHANNELS        = 8
    POSITION_UPDATE_MS  = 100

    # ─────────────────────────────────────────────────────────────────────

    def __init__(self, parent=None, *,
                 route_via_mixer: bool = False):
        """``route_via_mixer`` (Phase 5.2 opt-in): when True AND
        ``bassmix.dll`` is available, every loaded stream is created
        with the BASS_STREAM_DECODE flag and added to the singleton
        ``MixerBus``. The mixer is the only handle that plays to the
        output device — every engine ultimately feeds it. When False
        (default), the legacy direct-play architecture is used: each
        stream plays straight to the BASS device, and BASS auto-mixes
        at the device level.

        ════════════════════════════════════════════════════════════════
        CRITICAL INVARIANT — default MUST stay False (2026-05-17 lock)
        ════════════════════════════════════════════════════════════════
        The BASSmix migration attempt 2026-05-17 surfaced stutter +
        broken pause symptoms that couldn't be resolved in-session.
        Operator-locked: stay on direct-play until a future
        BASSmix retry session diagnoses the root cause.
        See HANDOVER_2026_05_17.md "Incident #26 — Phase 5 BASSmix
        retry blocked" for what was tried and why none of those
        fixes worked.
        DO NOT CHANGE the default to True. Don't.
        ════════════════════════════════════════════════════════════════

        Auto-falls back to ``route_via_mixer=False`` if bassmix.dll
        is missing — the engine never refuses to start. Operator can
        flip the flag back on at runtime once the DLL is installed
        (next ``load_file`` will route via mixer)."""
        super().__init__(parent)
        self._dll = get_dll()
        self._channels: dict[int, Channel] = {}
        self._lock = threading.Lock()
        # Monotonic, never-reused. Starts at 1 — 0 is sentinel for "invalid".
        self._next_id: int = 1
        # ── Phase 5 mixer routing ───────────────────────────────────────
        # Forced off if bassmix.dll absent. The engine eagerly creates
        # the mixer stream when routing is on, so the first load_file
        # has a target to add channels to.
        self._route_via_mixer: bool = False
        if route_via_mixer:
            try:
                from core.audio.mixer_bus import MixerBus
                if MixerBus.is_available():
                    mb = MixerBus.instance()
                    if mb.handle() is None:
                        mb.create()
                    if mb.handle() is not None:
                        self._route_via_mixer = True
                        log.info(
                            f"AudioEngine: routing via MixerBus "
                            f"(handle={mb.handle()})")
                    else:
                        log.warning(
                            "AudioEngine: mixer create() failed — "
                            "falling back to direct-play")
                else:
                    log.info(
                        "AudioEngine: route_via_mixer requested but "
                        "bassmix.dll not available — using direct-play")
            except Exception as exc:
                log.warning(
                    f"AudioEngine: mixer init failed ({exc}) — "
                    f"falling back to direct-play")

        # Cross-thread bridge: BASS callback thread → Qt main thread.
        # AutoConnection on a different-thread emit becomes QueuedConnection.
        self._stream_ended_internal.connect(
            self._on_stream_ended_main,
            Qt.ConnectionType.QueuedConnection,
        )
        # Phase 1 sync bridges — internal signals fire from the BASS
        # callback thread; the public signals are emitted on the main
        # thread via queued delivery.
        self._mix_point_reached_internal.connect(
            self.mix_point_reached,
            Qt.ConnectionType.QueuedConnection,
        )
        self._fade_completed_internal.connect(
            self.fade_completed,
            Qt.ConnectionType.QueuedConnection,
        )

        # Shared position-poll timer (Phase A2 wired). Single timer drives
        # position_changed for every "playing" channel — cheaper than one
        # timer per channel. play()/resume() start it; _poll_all stops it
        # when no channels remain in the playing state.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POSITION_UPDATE_MS)
        self._poll_timer.timeout.connect(self._poll_all)

        log.info("AudioEngine initialised (multi-channel BASS)")

    # ── Public API: load / playback control ───────────────────────────────

    def load_file(self, path: str, loop: bool = False) -> int:
        """Open `path` as a BASS stream. Returns the new channel id.

        Args:
            path: Audio file path.
            loop: If True, channel loops indefinitely when played
                  (BASS_SAMPLE_LOOP flag at stream creation). Default
                  False (one-shot playback). Phase B4 addition — used
                  primarily by Instant Jingles loop-mode pads.

        Note: `loop` is set at stream-creation time (BASS_SAMPLE_LOOP).
        It cannot be toggled after load — reload with a different value
        if needed.

        If MAX_CHANNELS is already reached, the oldest channel is evicted
        automatically to make room (Phase A3 — silent eviction matches
        InstantJingleEngine precedent). The eviction emits
        channel_state_changed(oldest_id, "stopped") before cleanup so UI
        consumers track the transition.

        Raises:
            AudioEngineError — path missing/empty, or BASS stream-creation
                               failure (decoder/format issues surface as
                               FormatError).
        """
        if not path:
            raise AudioEngineError("file path is empty")
        if not os.path.exists(path):
            raise AudioEngineError(f"file not found: {path}")

        # Capacity policy (Phase A3): evict oldest to make room.
        # Done before the lock-protected section because cleanup() takes
        # the lock internally — calling it from inside another lock would
        # deadlock.
        while len(self._channels) >= self.MAX_CHANNELS:
            self._evict_oldest()

        with self._lock:
            flags = BASS_STREAM_PRESCAN
            if loop:
                flags |= BASS_SAMPLE_LOOP
            # Phase 5.2 — when routing through the unified mixer, every
            # stream is created decoder-only. The mixer pulls data from
            # it and is the single handle that talks to the output
            # device. Without this flag, the stream would ALSO try to
            # play directly to the device, double-output.
            if self._route_via_mixer:
                flags |= BASS_STREAM_DECODE
            try:
                handle = BassStream.CreateFile(
                    False, path.encode("utf-8"),
                    0, 0,
                    flags,
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
            #
            # Phase 5.3 critical fix (2026-05-17): for mixer-routed
            # decode streams, OR in BASS_SYNC_MIXTIME so EOS fires at
            # MIXER-time (when audio actually reaches the speakers),
            # NOT at decode-time (~500ms ahead of speakers). Without
            # MIXTIME, Studio loads the next song while the mixer is
            # still playing the previous song's last 500ms — both
            # songs feed the mixer briefly, causing the audible
            # stutter operator reported.
            sync_type = BASS_SYNC_END | BASS_SYNC_ONETIME
            if self._route_via_mixer:
                sync_type |= BASS_SYNC_MIXTIME
            sync_cb = self._make_sync_cb(channel_id)
            sync_handle = self._dll.BASS_ChannelSetSync(
                handle,
                sync_type,
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

        # Phase 5.2 — attach to mixer if routing is enabled. Done OUTSIDE
        # the _lock to avoid holding it across a BASSmix call (the mixer
        # has its own lock; nesting risk). If attach fails, log + fall
        # through — the stream is loaded but won't audibly play through
        # the mixer; legacy state is `loaded`, callers see no error.
        if self._route_via_mixer:
            try:
                from core.audio.mixer_bus import MixerBus
                mb = MixerBus.instance()
                ok = mb.add_channel(handle)
                if not ok:
                    log.warning(
                        f"[ch {channel_id}] mixer add_channel failed; "
                        f"channel loaded but not audibly routed")
                else:
                    # Mark this channel as mixer-attached so cleanup
                    # detaches BEFORE freeing the stream.
                    ch.extras["_in_mixer"] = True
                    # Make sure the mixer is playing — needed when the
                    # first channel is added (BASS_MIXER_RESUME does it
                    # automatically, this is defence-in-depth).
                    mb.play()
            except Exception as exc:
                log.warning(
                    f"[ch {channel_id}] mixer attach raised: {exc}")

        self.channel_state_changed.emit(channel_id, "loaded")
        log.info(
            f"[ch {channel_id}] loaded {os.path.basename(path)} "
            f"(mixer={self._route_via_mixer})")
        return channel_id

    def play(self, channel_id: int) -> None:
        ch = self._require_channel(channel_id)
        if ch.extras.get("_in_mixer"):
            # Phase 5.2 fix (2026-05-17) — decode-only sources cannot
            # be played directly (BASS_ChannelPlay returns
            # BASS_ERROR_DECODE 38). The MixerBus.create() already
            # called Play on the mixer handle; the mixer pulls data
            # from this source automatically. Just clear the
            # per-channel paused flag if previously paused, then
            # update bookkeeping.
            try:
                from core.audio.mixer_bus import MixerBus
                MixerBus.instance().resume_source(ch.handle)
            except Exception as exc:
                log.debug(f"[ch {channel_id}] mixer resume on play: {exc}")
        else:
            # Legacy direct-play path — unchanged.
            BassChannel.Play(ch.handle, False)
        ch.state = "playing"
        self._ensure_poll_timer()
        self.channel_state_changed.emit(channel_id, "playing")
        log.info(f"[ch {channel_id}] playing")

    def pause(self, channel_id: int) -> None:
        ch = self._require_channel(channel_id)
        if ch.extras.get("_in_mixer"):
            # Phase 5.2 fix — BASS_ChannelPause on a decode source
            # is a no-op (mixer keeps pulling data). Use
            # BASS_Mixer_ChannelFlags(PAUSE) to actually halt the
            # mixer's pull from this source.
            try:
                from core.audio.mixer_bus import MixerBus
                MixerBus.instance().pause_source(ch.handle)
            except Exception as exc:
                log.debug(f"[ch {channel_id}] mixer pause: {exc}")
        else:
            BassChannel.Pause(ch.handle)
        ch.state = "paused"
        self.channel_state_changed.emit(channel_id, "paused")
        log.info(f"[ch {channel_id}] paused")

    def resume(self, channel_id: int) -> None:
        """Resume a paused channel. No-op if not currently paused."""
        ch = self._require_channel(channel_id)
        if ch.state != "paused":
            return
        if ch.extras.get("_in_mixer"):
            try:
                from core.audio.mixer_bus import MixerBus
                MixerBus.instance().resume_source(ch.handle)
            except Exception as exc:
                log.debug(f"[ch {channel_id}] mixer resume: {exc}")
        else:
            BassChannel.Resume(ch.handle)
        ch.state = "playing"
        self._ensure_poll_timer()
        self.channel_state_changed.emit(channel_id, "playing")
        log.info(f"[ch {channel_id}] resumed")

    def stop(self, channel_id: int) -> None:
        """Manual stop. Distinct from natural end-of-stream (which emits
        playback_ended via the sync callback). Stopping a channel does NOT
        free its stream — the caller must still call cleanup() when done.

        Phase A2: position is reset to 0 so a subsequent play() restarts
        from the beginning. Natural EOS ('ended' state) keeps position at
        duration; that's the distinguishing semantic between the two."""
        ch = self._require_channel(channel_id)
        if ch.extras.get("_in_mixer"):
            # Pause the mixer pull from this source + reset position.
            try:
                from core.audio.mixer_bus import MixerBus
                MixerBus.instance().pause_source(ch.handle)
            except Exception as exc:
                log.debug(f"[ch {channel_id}] mixer stop pause: {exc}")
        else:
            BassChannel.Stop(ch.handle)
        try:
            self._dll.BASS_ChannelSetPosition(ch.handle, 0, BASS_POS_BYTE)
        except Exception as exc:
            log.debug(f"[ch {channel_id}] position reset on stop failed: {exc}")
        ch.state = "stopped"
        self.channel_state_changed.emit(channel_id, "stopped")
        log.info(f"[ch {channel_id}] stopped (position reset to 0)")

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

    def get_position_ms(self, channel_id: int) -> int:
        """Current playback position. Returns 0 if the channel is unknown
        or BASS reports an error — this is a query path called from paint
        loops, so it must never raise."""
        ch = self._channels.get(channel_id)
        if ch is None:
            return 0
        return self._read_position_ms(ch.handle)

    def get_duration_ms(self, channel_id: int) -> int:
        """Total stream duration. Returns 0 on unknown channel / error."""
        ch = self._channels.get(channel_id)
        if ch is None:
            return 0
        return self._read_duration_ms(ch.handle)

    # ── Public API: position + volume control ─────────────────────────────

    def seek_to_ms(self, channel_id: int, position_ms: int) -> None:
        """Jump to `position_ms`. Clamps to [0, duration].

        Emits position_changed immediately so UI scrubbers snap without
        waiting for the next 100ms poll tick. BASS-level seek failures
        surface via error_occurred (does NOT raise — UI shouldn't crash
        on an unsupported-format seek).

        Raises ChannelError if `channel_id` is invalid (channel not loaded
        or already cleaned up). UI consumers should disconnect signals on
        cleanup to prevent post-cleanup races (Phase A5 / Q2)."""
        ch = self._require_channel(channel_id)
        target_ms = max(0, int(position_ms))
        # Clamp to duration if known
        dur_ms = self._read_duration_ms(ch.handle)
        if dur_ms > 0 and target_ms > dur_ms:
            target_ms = dur_ms

        try:
            target_bytes = self._dll.BASS_ChannelSeconds2Bytes(
                ch.handle, target_ms / 1000.0
            )
            ok = self._dll.BASS_ChannelSetPosition(
                ch.handle, target_bytes, BASS_POS_BYTE
            )
            if not ok:
                err = error_code()
                msg = f"seek failed (err {err})"
                log.warning(f"[ch {channel_id}] {msg}")
                self.error_occurred.emit(channel_id, msg)
                return
        except Exception as exc:
            msg = f"seek failed: {exc}"
            log.warning(f"[ch {channel_id}] {msg}")
            self.error_occurred.emit(channel_id, msg)
            return

        # Snap-feedback for UI scrub — emit before the next tick
        self.position_changed.emit(channel_id, target_ms)

    def set_volume(self, channel_id: int, volume: int) -> None:
        """Set per-channel volume in [0, 100].

        Clamps silently per Q4 (Phase A2 spec) — UI sliders sometimes
        overshoot by 1 due to float→int rounding, and raising would be
        a footgun for consumers."""
        ch = self._require_channel(channel_id)
        v = max(0, min(100, int(volume)))
        self._dll.BASS_ChannelSetAttribute(
            ch.handle, BASS_ATTRIB_VOL, ctypes.c_float(v / 100.0)
        )
        ch.volume = v

    def get_volume(self, channel_id: int) -> int:
        """Last-set volume for a channel (0–100). Returns 100 on unknown id."""
        ch = self._channels.get(channel_id)
        return ch.volume if ch else 100

    def fade_volume_to(self, channel_id: int, target_volume: int,
                       duration_ms: int) -> None:
        """Smoothly slide channel volume to `target_volume` over
        `duration_ms` via BASS_ChannelSlideAttribute (BASS-native; no Python
        timer needed).

        Edge cases (Phase A3 / Q4):
          - duration_ms <= 0 → behaves identically to set_volume (instant).
          - Channel in any state — paused / loaded channels apply the fade
            when play() resumes (BASS-native behavior).

        Volume is clamped silently to [0, 100]. ch.volume cache updates
        synchronously to the target value; callers who need the in-flight
        BASS volume can use BASS_ChannelGetAttribute directly. This matches
        the legacy AudioEngine.fade_to source-of-truth semantic.
        """
        ch = self._require_channel(channel_id)
        target = max(0, min(100, int(target_volume)))

        if duration_ms <= 0:
            # Instant — delegate so the clamp + cache logic stays in
            # one place.
            self.set_volume(channel_id, target)
            return

        self._dll.BASS_ChannelSlideAttribute(
            ch.handle,
            BASS_ATTRIB_VOL,
            ctypes.c_float(target / 100.0),
            ctypes.c_ulong(int(duration_ms)),
        )
        # Source-of-truth update: caller sees ch.volume == target
        # immediately, even though BASS is still tweening.
        ch.volume = target

    # ── Public API: sample-accurate sync callbacks (Phase 1) ──────────────
    #
    # These replace the previous "poll position every 250ms and check
    # threshold" pattern with BASS-native byte-position and slide-end
    # callbacks. The BASS audio thread fires the callback at the exact
    # sample boundary; the engine emits a Qt signal across threads so
    # consumers handle the event on the main thread.

    def set_position_sync(self, channel_id: int,
                           position_ms: int) -> Optional[int]:
        """Register a one-time BASS_SYNC_POS at the given playback position.
        When the channel's byte position crosses ``position_ms`` while
        playing, ``mix_point_reached(channel_id)`` is emitted on the main
        Qt thread.

        Returns the sync handle (use with ``remove_sync``) or None on
        any failure — position out of range, channel unknown, or BASS
        error. The engine retains a reference to the SYNCPROC closure
        so ctypes doesn't garbage-collect it mid-playback.

        Caller pattern (Studio Phase 1): on every new song load, call
        set_position_sync(cid, mix_point_ms). One sync per channel is
        sufficient; replace by removing the old one first if mix_point
        changes mid-track.
        """
        ch = self._require_channel(channel_id)
        if position_ms <= 0:
            return None
        try:
            byte_pos = self._dll.BASS_ChannelSeconds2Bytes(
                ch.handle, ctypes.c_double(position_ms / 1000.0))
        except Exception as exc:
            log.debug(f"[ch {channel_id}] Seconds2Bytes failed: {exc}")
            return None
        # BASS_ChannelSeconds2Bytes returns 0xFF…FF (unsigned -1) on err.
        if byte_pos == 0xFFFFFFFFFFFFFFFF:
            log.debug(
                f"[ch {channel_id}] set_position_sync: invalid pos_ms="
                f"{position_ms}, err={error_code()}")
            return None
        cb = self._make_pos_sync_cb(channel_id)
        # Phase 5.3 fix — mixer-routed channels need MIXTIME so the
        # mix-point sync fires when audio actually reaches the speakers,
        # not at decode-time (which leads speakers by ~500ms in a
        # buffered mixer pipeline). Otherwise the fade triggers before
        # listener perceives the mix point → wrong-feeling transition.
        sync_type = BASS_SYNC_POS | BASS_SYNC_ONETIME
        if ch.extras.get("_in_mixer"):
            sync_type |= BASS_SYNC_MIXTIME
        try:
            sync_handle = self._dll.BASS_ChannelSetSync(
                ch.handle,
                sync_type,
                ctypes.c_ulonglong(byte_pos),
                cb,
                None,
            )
        except Exception as exc:
            log.warning(
                f"[ch {channel_id}] BASS_ChannelSetSync (POS) failed: {exc}")
            return None
        if not sync_handle:
            log.debug(
                f"[ch {channel_id}] BASS_ChannelSetSync (POS) "
                f"returned 0, err={error_code()}")
            return None
        # Pin the callback so ctypes doesn't free it; cleanup will
        # remove it via remove_sync.
        ch.extras.setdefault("_pos_syncs", []).append(
            (cb, int(sync_handle)))
        log.info(
            f"[ch {channel_id}] position sync registered at "
            f"{position_ms}ms (sync={sync_handle})")
        return int(sync_handle)

    def set_slide_end_sync(self, channel_id: int) -> Optional[int]:
        """Register a one-time BASS_SYNC_SLIDE callback. Fires when the
        next ``BASS_ChannelSlideAttribute`` on this channel completes.
        Emits ``fade_completed(channel_id)`` on the main Qt thread.

        Typical use: register immediately AFTER calling
        ``fade_volume_to(cid, 0, duration)`` to be notified when the
        outgoing fade has fully reached zero. Caller can then cleanup
        the channel (or rely on negative-target auto-stop).

        Returns the sync handle or None on failure."""
        ch = self._require_channel(channel_id)
        cb = self._make_slide_sync_cb(channel_id)
        try:
            sync_handle = self._dll.BASS_ChannelSetSync(
                ch.handle,
                BASS_SYNC_SLIDE | BASS_SYNC_ONETIME,
                ctypes.c_ulonglong(0),
                cb,
                None,
            )
        except Exception as exc:
            log.warning(
                f"[ch {channel_id}] BASS_ChannelSetSync (SLIDE) failed: {exc}")
            return None
        if not sync_handle:
            log.debug(
                f"[ch {channel_id}] BASS_ChannelSetSync (SLIDE) "
                f"returned 0, err={error_code()}")
            return None
        ch.extras.setdefault("_slide_syncs", []).append(
            (cb, int(sync_handle)))
        return int(sync_handle)

    def remove_sync(self, channel_id: int, sync_handle: int) -> None:
        """Remove a sync previously registered via set_position_sync /
        set_slide_end_sync. Idempotent on unknown handles."""
        ch = self._channels.get(channel_id)
        if ch is None or not sync_handle:
            return
        try:
            self._dll.BASS_ChannelRemoveSync(
                ch.handle, ctypes.c_ulong(int(sync_handle)))
        except Exception as exc:
            log.debug(
                f"[ch {channel_id}] remove_sync({sync_handle}) failed: {exc}")
        # Drop the stored callback ref too.
        for key in ("_pos_syncs", "_slide_syncs"):
            syncs = ch.extras.get(key)
            if not syncs:
                continue
            ch.extras[key] = [
                (cb, h) for cb, h in syncs if h != int(sync_handle)
            ]

    def _make_pos_sync_cb(self, channel_id: int):
        """Build a SYNCPROC closure that emits mix_point_reached for the
        captured ``channel_id``. Returned object MUST be kept alive while
        the sync is registered (stored in Channel.extras)."""
        engine = self

        def _pos_cb(handle, channel, data, user):
            try:
                engine._mix_point_reached_internal.emit(channel_id)
            except Exception:
                # NEVER let an exception escape a BASS callback — it
                # crashes the audio thread.
                pass
        return SYNCPROC(_pos_cb)

    def _make_slide_sync_cb(self, channel_id: int):
        """Build a SYNCPROC closure that emits fade_completed for the
        captured ``channel_id``."""
        engine = self

        def _slide_cb(handle, channel, data, user):
            try:
                engine._fade_completed_internal.emit(channel_id)
            except Exception:
                pass
        return SYNCPROC(_slide_cb)

    # ── Public API: cleanup ───────────────────────────────────────────────

    def cleanup(self, channel_id: int) -> None:
        """Stop the channel, unhook ALL sync callbacks (EOS + any
        Phase-1 position/slide syncs registered via set_position_sync /
        set_slide_end_sync), detach from the BASSmix mixer if attached,
        free the BASS stream, and drop it from the active map.
        Idempotent on unknown ids.

        Order matters when route_via_mixer is on: mixer-detach BEFORE
        stream-free, otherwise the mixer briefly holds a dangling
        handle (potential crash inside BASSmix's pull thread)."""
        with self._lock:
            ch = self._channels.pop(channel_id, None)
        if ch is None:
            return
        try:
            # Phase 5.2 — detach from the mixer FIRST. Idempotent at
            # the MixerBus layer: unknown handles are silently skipped.
            if ch.extras.get("_in_mixer"):
                try:
                    from core.audio.mixer_bus import MixerBus
                    MixerBus.instance().remove_channel(ch.handle)
                except Exception as exc:
                    log.debug(
                        f"[ch {channel_id}] mixer detach failed: {exc}")
            # EOS sync (always present, allocated in load_file)
            if ch.sync_handle:
                self._dll.BASS_ChannelRemoveSync(ch.handle, ch.sync_handle)
            # Phase 1 syncs — position + slide callbacks registered by
            # Studio after load_file. Drop them BEFORE Stop/Free so a
            # ramp-completion mid-cleanup can't surprise us.
            for key in ("_pos_syncs", "_slide_syncs"):
                for _cb, sync_handle in ch.extras.get(key, []):
                    try:
                        self._dll.BASS_ChannelRemoveSync(
                            ch.handle, ctypes.c_ulong(int(sync_handle)))
                    except Exception:
                        pass
            BassChannel.Stop(ch.handle)
            BassStream.Free(ch.handle)
        except Exception as exc:
            log.warning(f"[ch {channel_id}] cleanup error: {exc}")
        log.info(f"[ch {channel_id}] cleaned up")

    def cleanup_all(self) -> None:
        """Cleanup every active channel. Safe to call at shutdown.

        Phase B5: per-channel error isolation. cleanup() already wraps
        its BASS calls in try/except, but this outer guard catches any
        unexpected exception so a single bad channel can't prevent the
        rest from being cleaned up. Errors are counted + logged; the
        method always returns normally."""
        with self._lock:
            ids = list(self._channels.keys())
        errors = 0
        for cid in ids:
            try:
                self.cleanup(cid)
            except Exception as exc:
                errors += 1
                log.warning(f"cleanup_all: channel {cid} cleanup raised: {exc}")
        if errors:
            log.warning(
                f"cleanup_all completed with {errors}/{len(ids)} errors")

    # ── Public API: diagnostics (Phase A5) ────────────────────────────────

    def is_fading(self, channel_id: int) -> bool:
        """True while a BASS_ChannelSlideAttribute is active for this
        channel's volume. Phase B UIs use this to dim transport controls
        during a fade."""
        ch = self._channels.get(channel_id)
        if ch is None:
            return False
        try:
            # BASS_ChannelIsSliding is in the legacy DLL declaration; the
            # new _bass.py omitted it. Declare on demand here so the
            # query path can run without a full DLL re-init.
            if not hasattr(self._dll.BASS_ChannelIsSliding, "argtypes") or \
                    self._dll.BASS_ChannelIsSliding.argtypes is None:
                self._dll.BASS_ChannelIsSliding.argtypes = [
                    ctypes.c_ulong, ctypes.c_ulong
                ]
                self._dll.BASS_ChannelIsSliding.restype = ctypes.c_bool
            return bool(self._dll.BASS_ChannelIsSliding(
                ch.handle, BASS_ATTRIB_VOL))
        except Exception:
            return False

    def get_channel_info(self, channel_id: int) -> dict:
        """Read-only diagnostic snapshot for Phase B debug overlays.
        Returns {} for unknown channels."""
        ch = self._channels.get(channel_id)
        if ch is None:
            return {}
        return {
            "id":          ch.id,
            "file_path":   ch.file_path,
            "state":       ch.state,
            "volume":      ch.volume,
            "position_ms": self._read_position_ms(ch.handle),
            "duration_ms": self._read_duration_ms(ch.handle),
            "is_fading":   self.is_fading(ch.id),
        }

    def get_active_channels(self) -> list[int]:
        """Channel ids currently in 'playing' or 'paused' state. Useful
        for Phase B "currently playing" panels and debug overlays.

        Note vs `active_channels()`: that method returns ALL loaded
        channels (any state); this one filters to only the audibly-engaged
        ones. Different semantic by design."""
        return [
            cid for cid, ch in self._channels.items()
            if ch.state in ("playing", "paused")
        ]

    def probe_duration_ms(self, path: str) -> Optional[int]:
        """Read an audio file's duration WITHOUT creating a persistent
        channel.

        Loads with PRESCAN, reads length, frees the handle. Returns ms
        or None if the file can't be loaded. No channel is added to the
        active map — `active_channels()` is unchanged after this call.

        Phase B4 primitive: lets Instant Jingles (and any future import
        flow) cache duration without consuming a channel slot."""
        if not path or not os.path.exists(path):
            return None
        try:
            handle = BassStream.CreateFile(
                False, path.encode("utf-8"),
                0, 0,
                BASS_STREAM_PRESCAN,
            )
        except Exception as exc:
            log.debug(f"probe_duration_ms({path!r}) load failed: {exc}")
            return None
        h = int(handle)
        try:
            len_bytes = self._dll.BASS_ChannelGetLength(h, BASS_POS_BYTE)
            return int(self._dll.BASS_ChannelBytes2Seconds(h, len_bytes) * 1000)
        except Exception:
            return None
        finally:
            try:
                BassStream.Free(h)
            except Exception:
                pass

    # ── Internals ─────────────────────────────────────────────────────────

    def _require_channel(self, channel_id: int) -> Channel:
        ch = self._channels.get(channel_id)
        if ch is None:
            raise ChannelError(f"channel {channel_id} not found")
        return ch

    def _evict_oldest(self) -> int:
        """Evict the oldest channel to make room (Phase A3 / Q1).

        Eviction uses Python 3.7+ dict insertion order — the first key in
        iter() is the oldest. No separate `loaded_at` field is needed
        (matches InstantJingleEngine precedent).

        Q2 ordering: channel_state_changed(oldest_id, "stopped") is
        emitted BEFORE cleanup, so UI consumers see "channel X stopped" →
        "channel Y loaded" in clean order rather than a silent disappear.

        Returns the evicted channel id, or 0 if the engine has no channels.
        """
        with self._lock:
            if not self._channels:
                return 0
            oldest_id = next(iter(self._channels))

        log.warning(
            f"channel cap reached ({self.MAX_CHANNELS}); "
            f"evicting oldest ch {oldest_id}"
        )
        # Q2: emit the stop signal BEFORE cleanup.
        self.channel_state_changed.emit(oldest_id, "stopped")
        self.cleanup(oldest_id)
        return oldest_id

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
        """Runs on the Qt main thread. Safe to mutate engine state and emit
        public signals.

        Idempotent: the BASS sync callback (primary) and the poll-loop
        fallback (secondary, in _poll_all) may both fire for the same
        channel in a rare race. The state == "ended" guard below ensures
        we emit playback_ended at most once per channel lifecycle.
        """
        ch = self._channels.get(channel_id)
        if ch is None:
            return
        if ch.state == "ended":
            return
        ch.state = "ended"
        # Note: we deliberately do NOT reset position here. "ended" semantics
        # = playback finished naturally and position stays at duration. That
        # distinguishes ended from stopped (which resets to 0).
        self.channel_state_changed.emit(channel_id, "ended")
        self.playback_ended.emit(channel_id)
        log.info(f"[ch {channel_id}] ended (natural EOS)")

    # ── Position polling (Phase A2) ───────────────────────────────────────

    def _ensure_poll_timer(self) -> None:
        """Start the shared poll timer if it's not already running. Called
        from play() and resume(). _poll_all stops the timer when it sees no
        playing channels."""
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _poll_all(self) -> None:
        """Per-tick: emit position_changed for every playing channel; catch
        natural EOS as a fallback when the BASS sync callback doesn't fire
        (rare but real — same defensive pattern the legacy AudioEngine has).

        Stops the timer when no playing channels remain — saves CPU on
        idle. play()/resume() restart it via _ensure_poll_timer."""
        any_playing = False
        # snapshot via list() so concurrent dict mutation (e.g. cleanup
        # during a poll-driven _on_stream_ended_main) doesn't break iteration
        for cid, ch in list(self._channels.items()):
            if ch.state != "playing":
                continue
            any_playing = True
            pos_ms = self._read_position_ms(ch.handle)
            dur_ms = self._read_duration_ms(ch.handle)

            self.position_changed.emit(cid, pos_ms)

            # Fallback EOS detection. 50ms tolerance because
            # GetPosition→Bytes2Seconds rounding loses sub-frame precision.
            if dur_ms > 0 and pos_ms >= dur_ms - 50:
                # Triggers state == "ended" guard if sync callback already
                # fired for this channel.
                self._on_stream_ended_main(cid)

        if not any_playing:
            self._poll_timer.stop()

    # ── BASS byte-position read helpers ──────────────────────────────────

    def _read_position_ms(self, handle: int) -> int:
        """Synchronous position read. Returns 0 on any BASS error —
        this is a paint-loop primitive, MUST NOT raise.

        Phase 5.3 fix (2026-05-17): for mixer-routed sources, use
        ``BASS_Mixer_ChannelGetPosition`` instead of the standard
        ``BASS_ChannelGetPosition``. The former is latency-compensated
        (BASS_MIXER_POSEX flag enables it) — it returns the position
        the listener is HEARING right now, accounting for the mixer's
        output buffer. The standard call returns decode-position
        (where the mixer has pulled to), which leads speaker by the
        full mixer buffer (~500ms). Without this fix, the progress
        bar shows position 500ms AHEAD of audio."""
        try:
            # Determine if this is a mixer-routed source by checking
            # if the handle is in the mixer's tracked set.
            if self._route_via_mixer:
                try:
                    from core.audio.mixer_bus import MixerBus
                    from core.audio._bassmix import get_mixer_dll
                    mb = MixerBus.instance()
                    if mb.is_attached(handle):
                        mixer_dll = get_mixer_dll()
                        if mixer_dll is not None:
                            pos_bytes = mixer_dll.BASS_Mixer_ChannelGetPosition(
                                ctypes.c_ulong(int(handle)),
                                ctypes.c_ulong(BASS_POS_BYTE),
                            )
                            return int(self._dll.BASS_ChannelBytes2Seconds(
                                handle, pos_bytes) * 1000)
                except Exception:
                    pass   # fall through to standard read
            pos_bytes = self._dll.BASS_ChannelGetPosition(handle, BASS_POS_BYTE)
            return int(self._dll.BASS_ChannelBytes2Seconds(handle, pos_bytes) * 1000)
        except Exception:
            return 0

    def _read_duration_ms(self, handle: int) -> int:
        """Synchronous BASS_ChannelGetLength + Bytes2Seconds."""
        try:
            len_bytes = self._dll.BASS_ChannelGetLength(handle, BASS_POS_BYTE)
            return int(self._dll.BASS_ChannelBytes2Seconds(handle, len_bytes) * 1000)
        except Exception:
            return 0

    # ── Peak-level read for the LR meter widget ──────────────────────────
    #
    # BASS packs the level into a single DWORD: low-word = left peak,
    # high-word = right peak, each 0..32768 (= 0..1.0). We normalize to
    # floats and return (left, right). A clamped 0,0 is returned on any
    # error or when the channel id isn't known — paint-loop primitive,
    # MUST NOT raise.

    def get_levels(self, channel_id: int) -> tuple[float, float]:
        """Return (left, right) peak levels normalized to 0.0–1.0 for
        the given channel. Studio's _LevelMeters polls this at ~30Hz
        from a QTimer so the bars react to whatever's currently audible
        on the deck."""
        try:
            ch = self._channels.get(int(channel_id))
        except Exception:
            return (0.0, 0.0)
        if ch is None:
            return (0.0, 0.0)
        try:
            packed = int(self._dll.BASS_ChannelGetLevel(ch.handle))
        except Exception:
            return (0.0, 0.0)
        if packed == 0xFFFFFFFF:   # BASS error sentinel (-1 cast to unsigned)
            return (0.0, 0.0)
        # Low word = left, high word = right; range 0..32768.
        left  = (packed & 0xFFFF) / 32768.0
        right = ((packed >> 16) & 0xFFFF) / 32768.0
        # Clamp defensively — BASS occasionally returns slightly >1
        # values during peak transients.
        if left  > 1.0: left  = 1.0
        if right > 1.0: right = 1.0
        if left  < 0.0: left  = 0.0
        if right < 0.0: right = 0.0
        return (left, right)
