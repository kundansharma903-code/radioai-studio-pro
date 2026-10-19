"""
RadioAI Studio Pro — Sweeper Engine (BASS overlay player)

Plays sweeper audio overlaid on top of a song using a separate BASS
channel. The sweeper is timed to start at a calculated position within
the currently playing song by polling the deck's BASS handle position.

The overlay channel is independent — both song and sweeper play
simultaneously through the same BASS output device (like Jazler SOHO).

BASS license: evaluation DLL. Purchase commercial license before broadcast.
"""

import os
import threading
import time
import ctypes

from pybass3 import BassStream, BassChannel
import pybass3.bass_module as _bm
from pybass3.codes import channel as _ch

BASS_STREAM_PRESCAN = 0x20000


class SweeperEngine:
    """Overlay sweeper player (separate BASS channel).

    Usage::

        engine = SweeperEngine()
        engine.schedule_for_song(song_info, sweeper_info, deck_handle)
    """

    POLL_MS = 100

    def __init__(self):
        # Each schedule_for_song() gets its OWN cancel Event + handle slot
        # (a small dict).  The old shared Event was set by cancel() and
        # immediately clear()ed by the next schedule, so the previous
        # watcher kept running; both threads also shared self._handle and
        # the old thread's ``finally`` could free the NEW sweeper.
        self._lock    = threading.Lock()
        self._current = None          # {"cancel": Event, "handle": int}
        self._thread  = None

    @property
    def _handle(self):
        cur = self._current
        return int(cur["handle"]) if cur else 0

    # ── Public ────────────────────────────────────────────────────────────────

    def schedule_for_song(self, song_info, sweeper_info, deck_handle,
                          on_start=None, on_end=None):
        """Schedule a sweeper overlay for the currently playing song.

        Parameters
        ----------
        song_info : dict
            duration_ms, intro_end_ms (optional).
        sweeper_info : dict
            file_path, duration_ms, position, sweeper_volume, position_offset.
        deck_handle : int
            The raw BASS stream handle of the deck song (use
            ``AudioEngine.bass_handle(cid)`` — NOT the engine channel id).
        on_start : callable, optional
            Called on the watcher thread once the sweeper actually plays.
        on_end : callable, optional
            Called on the watcher thread when this schedule finishes
            (only if it had started).
        """
        self.cancel()

        trigger_ms = self._calc_trigger(song_info, sweeper_info)
        if trigger_ms is None:
            return

        sw_path = sweeper_info.get("file_path", "")
        if not sw_path or not os.path.exists(sw_path):
            return

        raw_vol = sweeper_info.get("sweeper_volume", 100)
        sw_vol = 100 if raw_vol is None else max(0, min(100, int(raw_vol)))
        state = {"cancel": threading.Event(), "handle": 0}
        with self._lock:
            self._current = state
        cancel_ev = state["cancel"]

        def _fire():
            from core.audio._bass import bass_file_arg
            fname, uflag = bass_file_arg(sw_path)
            try:
                handle = BassStream.CreateFile(
                    False, fname, 0, 0, BASS_STREAM_PRESCAN | uflag
                )
            except Exception as e:
                err = _bm.BASS_ErrorGetCode()
                print(f"[SweeperEngine] stream error {err}: {e}")
                return 0

            with self._lock:
                if cancel_ev.is_set():
                    # Cancelled while the stream was being created.
                    try:
                        BassStream.Free(handle)
                    except Exception:
                        pass
                    return 0
                state["handle"] = handle
            from core.audio_engine import _get_dll, BASS_ATTRIB_VOL
            dll = _get_dll()
            dll.BASS_ChannelSetAttribute(handle, BASS_ATTRIB_VOL,
                                         ctypes.c_float(sw_vol / 100.0))
            BassChannel.Play(handle, False)
            print(f"[SweeperEngine] fired: {os.path.basename(sw_path)} vol={sw_vol}")
            return handle

        def _watcher():
            started = False
            try:
                if trigger_ms > 0:
                    # Wait for deck to reach trigger position
                    time.sleep(0.5)  # give BASS time to latch
                    while not cancel_ev.is_set():
                        if not deck_handle:
                            return          # nothing to time against
                        pos_s = BassChannel.GetPositionSeconds(deck_handle)
                        pos_ms = int(pos_s * 1000)
                        if pos_ms >= trigger_ms:
                            break
                        state_ = BassChannel.IsActive(deck_handle)
                        if state_ in (_ch.ACTIVE_STOPPED, 0):
                            return
                        time.sleep(self.POLL_MS / 1000.0)

                if cancel_ev.is_set():
                    return
                if not _fire():
                    return
                started = True

                if on_start:
                    try:
                        on_start()
                    except Exception:
                        pass

                # Wait for sweeper to finish
                while not cancel_ev.is_set() and state["handle"]:
                    st = BassChannel.IsActive(state["handle"])
                    if st in (_ch.ACTIVE_STOPPED, 0):
                        break
                    time.sleep(0.15)

                time.sleep(0.15)  # drain buffer

            except Exception as e:
                print(f"[SweeperEngine] error: {e}")
            finally:
                self._free_state(state)
                with self._lock:
                    if self._current is state:
                        self._current = None
                if started and on_end:
                    try:
                        on_end()
                    except Exception:
                        pass

        self._thread = threading.Thread(target=_watcher, daemon=True)
        self._thread.start()

    def cancel(self):
        """Stop the current overlay (pending or playing). Only ever frees
        the handle owned by the schedule being cancelled."""
        with self._lock:
            state = self._current
            self._current = None
        if state is not None:
            state["cancel"].set()
            self._free_state(state)

    @property
    def is_playing(self):
        h = self._handle
        if not h:
            return False
        try:
            return BassChannel.IsActive(h) == _ch.ACTIVE_PLAYING
        except Exception:
            return False

    # ── Trigger calculation ───────────────────────────────────────────────────

    def _calc_trigger(self, song, sweeper):
        song_dur  = int(song.get("duration_ms", 0) or 0)
        sw_dur    = int(sweeper.get("duration_ms", 0) or 0)
        intro_end = int(song.get("intro_end_ms", 0) or 0)
        offset    = float(sweeper.get("position_offset", 0) or 0)
        pos       = (sweeper.get("position") or "").strip()

        if song_dur <= 0:
            return 0

        if pos == "Start of Song":
            trigger = 0
        elif pos == "Before Intro":
            trigger = max(0, intro_end - sw_dur) if (intro_end > 0 and sw_dur > 0) else 0
        elif pos == "Before End":
            trigger = max(0, song_dur - sw_dur) if sw_dur > 0 else max(0, song_dur - 8000)
        elif pos == "Bridge at End":
            half = sw_dur // 2 if sw_dur > 0 else 4000
            trigger = max(0, song_dur - half)
        elif pos in ("Custom", "Custom Position"):
            trigger = int(offset * 1000) if offset else 0
        elif pos == "Independent":
            trigger = 0
        else:
            half = sw_dur // 2 if sw_dur > 0 else 4000
            trigger = max(0, song_dur - half)

        if offset and pos not in ("Custom", "Custom Position"):
            trigger = max(0, trigger + int(offset * 1000))

        return trigger

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _free_state(self, state):
        """Stop + free the handle owned by ``state`` (idempotent)."""
        with self._lock:
            h = int(state.get("handle") or 0)
            state["handle"] = 0
        if h:
            try:
                BassChannel.Stop(h)
                BassStream.Free(h)
            except Exception:
                pass

    def _free_handle(self):
        """Back-compat: free whatever the current schedule owns."""
        cur = self._current
        if cur is not None:
            self._free_state(cur)
