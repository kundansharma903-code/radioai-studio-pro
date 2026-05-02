"""RadioAI Studio Pro -- Sweeper Engine

Plays sweeper audio OVERLAID on top of a song using an independent
VLC MediaPlayer. The sweeper is timed to start at a specific position
within the currently playing song, determined by the sweeper's
``position`` setting (Bridge at End, Before Intro, Start of Song,
Before End, Independent, Custom).

The overlay player is completely separate from the Studio's deck A/B
players, so both the song and the sweeper play simultaneously -- just
like Jazler SOHO.
"""

import os
import threading
import time

import vlc


class SweeperEngine:
    """Overlay sweeper player.

    Usage::

        engine = SweeperEngine(vlc_instance)
        engine.schedule_for_song(song_info, sweeper_info)

    The engine polls the active deck's position every 100ms and fires
    the sweeper at the calculated trigger point.
    """

    POLL_MS = 100  # position check interval

    def __init__(self, vlc_instance):
        self._inst = vlc_instance
        self._player = vlc_instance.media_player_new()
        self._thread = None
        self._cancel = threading.Event()

    # -- public --------------------------------------------------------

    def schedule_for_song(self, song_info, sweeper_info, deck_player,
                          on_start=None, on_end=None):
        """Schedule a sweeper overlay for the currently playing song.

        Parameters
        ----------
        song_info : dict
            Must have: duration_ms, intro_end_ms (optional), file_path.
        sweeper_info : dict
            Must have: file_path, duration_ms, position, sweeper_volume,
            song_volume (optional duck level), position_offset (optional).
        deck_player : vlc.MediaPlayer
            The Studio deck player currently playing the song (deck A or B).
        on_start : callable, optional
            Called when the sweeper starts playing (for UI update).
        on_end : callable, optional
            Called when the sweeper finishes.
        """
        self.cancel()  # stop any pending schedule

        trigger_ms = self._calc_trigger(song_info, sweeper_info)
        if trigger_ms is None:
            return

        sw_path = sweeper_info.get("file_path", "")
        if not sw_path or not os.path.exists(sw_path):
            return

        sw_vol = int(sweeper_info.get("sweeper_volume", 100) or 100)

        self._cancel.clear()

        def _fire_sweeper():
            """Load and play the sweeper overlay immediately."""
            media = self._inst.media_new(sw_path)
            self._player.set_media(media)
            self._player.audio_set_volume(sw_vol)
            self._player.play()
            time.sleep(0.12)  # VLC latch
            self._player.audio_set_volume(sw_vol)  # re-apply (Windows quirk)
            print(f"[SweeperEngine] fired: {os.path.basename(sw_path)} vol={sw_vol}")

        def _watcher():
            try:
                if trigger_ms <= 0:
                    # START_OF_SONG (or immediate): fire right away,
                    # no polling needed. This avoids the race where
                    # VLC reports pos=-1 / state=NothingSpecial for
                    # the first ~300ms after play() and the watcher
                    # either skips or exits.
                    _fire_sweeper()
                else:
                    # Wait for the deck to reach the trigger point.
                    # Give VLC 500ms to latch before we start
                    # checking state, so we don't exit on a
                    # transient NothingSpecial / Stopped state.
                    time.sleep(0.5)

                    while not self._cancel.is_set():
                        pos = deck_player.get_time()
                        if pos >= 0 and pos >= trigger_ms:
                            break
                        st = deck_player.get_state()
                        if st in (vlc.State.Ended, vlc.State.Error):
                            return
                        time.sleep(self.POLL_MS / 1000.0)

                    if self._cancel.is_set():
                        return

                    _fire_sweeper()

                if on_start:
                    try:
                        on_start()
                    except Exception:
                        pass

                # Wait for sweeper to finish
                while not self._cancel.is_set():
                    st = self._player.get_state()
                    if st in (vlc.State.Ended, vlc.State.Stopped,
                              vlc.State.Error):
                        break
                    time.sleep(0.15)

                # Drain buffer
                time.sleep(0.20)
                self._player.stop()

            except Exception as e:
                print(f"[SweeperEngine] error: {e}")
            finally:
                if on_end:
                    try:
                        on_end()
                    except Exception:
                        pass

        self._thread = threading.Thread(target=_watcher, daemon=True)
        self._thread.start()

    def cancel(self):
        """Cancel any pending or playing sweeper."""
        self._cancel.set()
        try:
            self._player.stop()
        except Exception:
            pass

    @property
    def is_playing(self):
        try:
            return self._player.get_state() == vlc.State.Playing
        except Exception:
            return False

    # -- trigger calculation -------------------------------------------

    def _calc_trigger(self, song, sweeper):
        """Return the ms position in the song where the sweeper should start."""
        song_dur = int(song.get("duration_ms", 0) or 0)
        sw_dur = int(sweeper.get("duration_ms", 0) or 0)
        intro_end = int(song.get("intro_end_ms", 0) or 0)
        offset = float(sweeper.get("position_offset", 0) or 0)
        pos = (sweeper.get("position") or "").strip()

        if song_dur <= 0:
            return 0  # fallback: start immediately

        if pos == "Start of Song":
            trigger = 0

        elif pos == "Before Intro":
            if intro_end > 0 and sw_dur > 0:
                trigger = max(0, intro_end - sw_dur)
            else:
                trigger = 0  # fallback

        elif pos == "Before End":
            trigger = max(0, song_dur - sw_dur) if sw_dur > 0 else max(0, song_dur - 8000)

        elif pos == "Bridge at End":
            # Half over current song's end, half over next song's start
            half = sw_dur // 2 if sw_dur > 0 else 4000
            trigger = max(0, song_dur - half)

        elif pos == "Custom":
            trigger = int(offset * 1000) if offset else 0

        elif pos == "Independent":
            trigger = 0  # play immediately

        else:
            # Unknown position — default to Bridge at End
            half = sw_dur // 2 if sw_dur > 0 else 4000
            trigger = max(0, song_dur - half)

        # Apply offset adjustment (seconds → ms)
        if offset and pos != "Custom":
            trigger = max(0, trigger + int(offset * 1000))

        return trigger
