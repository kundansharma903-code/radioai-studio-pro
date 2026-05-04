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
        self._handle  = 0
        self._thread  = None
        self._cancel  = threading.Event()

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
            The BASS stream handle of the currently playing deck song.
        on_start : callable, optional
        on_end : callable, optional
        """
        self.cancel()

        trigger_ms = self._calc_trigger(song_info, sweeper_info)
        if trigger_ms is None:
            return

        sw_path = sweeper_info.get("file_path", "")
        if not sw_path or not os.path.exists(sw_path):
            return

        sw_vol = int(sweeper_info.get("sweeper_volume", 100) or 100)
        self._cancel.clear()

        def _fire():
            try:
                handle = BassStream.CreateFile(
                    False, sw_path.encode("utf-8"), 0, 0, BASS_STREAM_PRESCAN
                )
            except Exception as e:
                err = _bm.BASS_ErrorGetCode()
                print(f"[SweeperEngine] stream error {err}: {e}")
                return 0

            self._handle = handle
            from core.audio_engine import _get_dll, BASS_ATTRIB_VOL
            dll = _get_dll()
            dll.BASS_ChannelSetAttribute(handle, BASS_ATTRIB_VOL,
                                         ctypes.c_float(sw_vol / 100.0))
            BassChannel.Play(handle, False)
            print(f"[SweeperEngine] fired: {os.path.basename(sw_path)} vol={sw_vol}")
            return handle

        def _watcher():
            try:
                if trigger_ms <= 0:
                    # Immediate — fire now
                    h = _fire()
                else:
                    # Wait for deck to reach trigger position
                    time.sleep(0.5)  # give BASS time to latch
                    while not self._cancel.is_set():
                        if deck_handle:
                            pos_s = BassChannel.GetPositionSeconds(deck_handle)
                            pos_ms = int(pos_s * 1000)
                            if pos_ms >= trigger_ms:
                                break
                            state = BassChannel.IsActive(deck_handle)
                            if state in (_ch.ACTIVE_STOPPED, 0):
                                return
                        time.sleep(self.POLL_MS / 1000.0)

                    if self._cancel.is_set():
                        return
                    h = _fire()

                if on_start:
                    try:
                        on_start()
                    except Exception:
                        pass

                # Wait for sweeper to finish
                while not self._cancel.is_set() and self._handle:
                    state = BassChannel.IsActive(self._handle)
                    if state in (_ch.ACTIVE_STOPPED, 0):
                        break
                    time.sleep(0.15)

                time.sleep(0.15)  # drain buffer

            except Exception as e:
                print(f"[SweeperEngine] error: {e}")
            finally:
                self._free_handle()
                if on_end:
                    try:
                        on_end()
                    except Exception:
                        pass

        self._thread = threading.Thread(target=_watcher, daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel.set()
        self._free_handle()

    @property
    def is_playing(self):
        if not self._handle:
            return False
        try:
            return BassChannel.IsActive(self._handle) == _ch.ACTIVE_PLAYING
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
        elif pos == "Custom":
            trigger = int(offset * 1000) if offset else 0
        elif pos == "Independent":
            trigger = 0
        else:
            half = sw_dur // 2 if sw_dur > 0 else 4000
            trigger = max(0, song_dur - half)

        if offset and pos != "Custom":
            trigger = max(0, trigger + int(offset * 1000))

        return trigger

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _free_handle(self):
        if self._handle:
            try:
                BassChannel.Stop(self._handle)
                BassStream.Free(self._handle)
            except Exception:
                pass
            self._handle = 0
