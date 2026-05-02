"""RadioAI Studio Pro — Audio Engine (clean 2-deck architecture)

RULE 1: Only 2 players (Deck A, Deck B). No separate spot player —
        spots play on whichever deck is currently active, same as
        songs, jingles, and sweepers. (The jingle pad overlay player
        is the only exception, since DJ pads fire *over* the mix.)

RULE 2: Active deck = currently playing. Standby deck = loaded and
        waiting silently at volume 0.

RULE 3: Every transition is a crossfade — active fades out, standby
        fades in, then flips.

Primary API:
    load_deck(deck, file_path)          — load without playing
    play_deck(deck)                      — play and mark active
    pause_deck(deck) / stop_deck(deck)   — transport
    seek(deck, ms) / set_volume(deck, v)
    get_state(deck)                      — rich per-deck state
    crossfade_to_standby(duration, cb)   — always fades active→standby
    fade_out_deck(deck, duration)        — fade a single deck to stop
    play_jingle(path) / stop_jingle()    — overlay player (pads only)

Legacy shims (kept so existing bridge slots keep working):
    load_deck_a/load_deck_b, play_deck_a/_b, pause_deck_a/_b,
    stop_deck_a/_b, set_volume_deck_a/_b, seek_deck_a/_b,
    fade_out_deck_a/_b, is_deck_a_playing/_b, is_playing,
    is_finished, get_remaining_ms, crossfade, crossfade_ba,
    get_duration, get_position.
"""

import os
import threading
import time

import vlc


class AudioEngine:
    def __init__(self):
        # Use the Windows system default audio output — whatever the user
        # has set in Windows Sound Settings. No soundcard selection UI
        # required; works on any PC automatically. `--aout=any` tells
        # libVLC to pick the best available audio output module.
        self.instance = vlc.Instance('--no-xlib', '--aout=any', '--quiet')

        # ── Only 2 main players ────────────────────────────────────
        self.deck_a = self.instance.media_player_new()
        self.deck_b = self.instance.media_player_new()

        # Jingle overlay player — intentionally separate so DJ pads
        # fire over the mix without taking over the active deck.
        self.jingle_player = self.instance.media_player_new()

        # State
        self.active_deck = 'A'
        self.deck_a_volume = 85
        self.deck_b_volume = 85
        self.deck_a_file = None
        self.deck_b_file = None
        # `was_started` flags: True once play_deck() has been called on this
        # deck since last load/stop. Used by the JS failsafe so a freshly
        # loaded-but-never-played deck is not treated as "ended".
        self.deck_a_started = False
        self.deck_b_started = False
        self.crossfade_duration = 3.0
        self.is_crossfading = False

        # Legacy callback (no longer used, kept for API compatibility)
        self.on_song_end = None
        self.on_position_update = None

    # ── Helpers ─────────────────────────────────────────────────────
    def _player(self, deck):
        return self.deck_a if deck == 'A' else self.deck_b

    def _target_vol(self, deck):
        return self.deck_a_volume if deck == 'A' else self.deck_b_volume

    # ── Core API ────────────────────────────────────────────────────
    def load_deck(self, deck, file_path):
        """Load a file to a deck WITHOUT playing it.

        Standby decks are loaded at volume 0 so that when the
        crossfade fires we only have to ramp the volume, not deal
        with a pop or click.
        """
        if not file_path or not os.path.exists(file_path):
            return False
        media = self.instance.media_new(file_path)
        player = self._player(deck)
        player.set_media(media)
        if deck == 'A':
            self.deck_a_file = file_path
            self.deck_a_started = False
        else:
            self.deck_b_file = file_path
            self.deck_b_started = False
        # Silent if loaded to standby; target vol if loaded to active.
        player.audio_set_volume(self._target_vol(deck) if self.active_deck == deck else 0)
        return True

    def play_deck(self, deck):
        """Play a deck at its target volume and mark it active.

        VLC quirk: on Windows/DirectSound the audio output isn't
        initialised until `play()` is actually called, so any
        `audio_set_volume()` before `play()` can be silently dropped.
        We re-apply the target volume on a short background timer
        so the spot/music is guaranteed to come out at the right
        level once playback actually starts.
        """
        player = self._player(deck)
        target_vol = int(self._target_vol(deck))
        player.audio_set_volume(target_vol)
        player.play()
        self.active_deck = deck
        if deck == 'A':
            self.deck_a_started = True
        else:
            self.deck_b_started = True

        def reapply_volume():
            try:
                # Two passes — once VLC has initialised the output,
                # once more after media has actually started streaming.
                time.sleep(0.12)
                player.audio_set_volume(target_vol)
                time.sleep(0.18)
                player.audio_set_volume(target_vol)
            except Exception:
                pass
        threading.Thread(target=reapply_volume, daemon=True).start()

    def pause_deck(self, deck):
        self._player(deck).pause()

    def stop_deck(self, deck):
        self._player(deck).stop()
        if deck == 'A':
            self.deck_a_started = False
        else:
            self.deck_b_started = False

    def seek(self, deck, ms):
        try:
            self._player(deck).set_time(int(ms))
        except Exception:
            pass

    def set_volume(self, deck, vol):
        vol = max(0, min(100, int(vol)))
        if deck == 'A':
            self.deck_a_volume = vol
        else:
            self.deck_b_volume = vol
        self._player(deck).audio_set_volume(vol)

    def get_state(self, deck):
        """Rich per-deck state dict used by the new studio UI."""
        player = self._player(deck)
        try:
            state = player.get_state()
        except Exception:
            state = None
        length = player.get_length() or 0
        time_ms = player.get_time() or 0

        is_playing = state == vlc.State.Playing
        is_paused = state == vlc.State.Paused
        is_ended = state in (
            vlc.State.Ended,
            vlc.State.Stopped,
            vlc.State.NothingSpecial,
            vlc.State.Error,
        )
        remaining = max(0, length - time_ms) if length > 0 and time_ms >= 0 else 0

        def fmt(ms):
            if ms is None or ms <= 0:
                return '0:00'
            s = int(ms) // 1000
            return f"{s // 60}:{s % 60:02d}"

        was_started = self.deck_a_started if deck == 'A' else self.deck_b_started
        return {
            'is_playing': is_playing,
            'is_paused': is_paused,
            'is_ended': is_ended,
            'was_started': was_started,
            'elapsed_ms': max(0, time_ms),
            'length_ms': max(0, length),
            'remaining_ms': remaining,
            'elapsed': fmt(time_ms),
            'remaining': fmt(remaining),
            'total': fmt(length),
            'progress': (time_ms / length) if length > 0 else 0,
            'file': self.deck_a_file if deck == 'A' else self.deck_b_file,
            'volume': self._target_vol(deck),
        }

    # ── Crossfade (always active → standby) ─────────────────────────
    def crossfade_to_standby(self, duration=None, callback=None):
        """Crossfade from whichever deck is currently active to the other.

        - active deck: fades OUT (current vol → 0, then stopped)
        - standby deck: starts from 0 vol, fades IN to its target vol
        - at the end, active_deck flips and callback(outgoing, incoming)
          is called.
        """
        if self.is_crossfading:
            return
        if duration is None:
            duration = self.crossfade_duration

        outgoing = self.active_deck
        incoming = 'B' if outgoing == 'A' else 'A'
        out_player = self._player(outgoing)
        in_player = self._player(incoming)

        out_target = self._target_vol(outgoing)
        in_target = self._target_vol(incoming)

        # Kick off incoming at silence then play
        try:
            in_player.audio_set_volume(0)
            in_player.play()
        except Exception:
            pass

        def do_fade():
            self.is_crossfading = True
            try:
                steps = 30
                step_time = max(0.01, duration / steps)
                for i in range(steps + 1):
                    t = i / steps
                    out_player.audio_set_volume(int(out_target * (1 - t)))
                    in_player.audio_set_volume(int(in_target * t))
                    time.sleep(step_time)
                out_player.audio_set_volume(0)
                in_player.audio_set_volume(in_target)
                out_player.stop()
                # Outgoing is now free (no longer "started"); incoming
                # is the active deck and has been playing throughout.
                if outgoing == 'A':
                    self.deck_a_started = False
                else:
                    self.deck_b_started = False
                if incoming == 'A':
                    self.deck_a_started = True
                else:
                    self.deck_b_started = True
                self.active_deck = incoming
            except Exception as e:
                print(f"[AudioEngine] crossfade error: {e}")
            finally:
                self.is_crossfading = False
                if callback:
                    try:
                        callback(outgoing, incoming)
                    except Exception as e:
                        print(f"[AudioEngine] crossfade callback error: {e}")

        threading.Thread(target=do_fade, daemon=True).start()

    # ── Fade out a single deck (FADE OUT button) ────────────────────
    def fade_out_deck(self, deck, duration=3.0):
        def do_fade():
            try:
                start_vol = self._target_vol(deck)
                player = self._player(deck)
                steps = 20
                step_time = max(0.01, duration / steps)
                for i in range(steps + 1):
                    player.audio_set_volume(int(start_vol * (1 - i / steps)))
                    time.sleep(step_time)
                player.stop()
                player.audio_set_volume(int(start_vol))
            except Exception:
                pass
        threading.Thread(target=do_fade, daemon=True).start()

    # ── Jingle overlay ──────────────────────────────────────────────
    def play_jingle(self, file_path):
        if not file_path or not os.path.exists(file_path):
            return False
        media = self.instance.media_new(file_path)
        self.jingle_player.set_media(media)
        self.jingle_player.audio_set_volume(100)
        self.jingle_player.play()
        return True

    def stop_jingle(self):
        self.jingle_player.stop()

    def get_duration(self, file_path):
        try:
            if not file_path or not os.path.exists(file_path):
                return 0
            m = self.instance.media_new(file_path)
            m.parse()
            return m.get_duration() or 0
        except Exception:
            return 0

    # ═══ LEGACY COMPATIBILITY SHIMS ═════════════════════════════════
    # Existing bridge slots and any other callers keep working.

    def load_deck_a(self, file_path, volume=None):
        return self.load_deck('A', file_path)

    def load_deck_b(self, file_path, volume=None):
        return self.load_deck('B', file_path)

    def play_deck_a(self):
        self.play_deck('A')

    def play_deck_b(self):
        self.play_deck('B')

    def pause_deck_a(self):
        self.pause_deck('A')

    def pause_deck_b(self):
        self.pause_deck('B')

    def stop_deck_a(self):
        self.stop_deck('A')

    def stop_deck_b(self):
        self.stop_deck('B')

    def set_volume_deck_a(self, vol):
        self.set_volume('A', vol)

    def set_volume_deck_b(self, vol):
        self.set_volume('B', vol)

    def seek_deck_a(self, ms):
        self.seek('A', ms)

    def seek_deck_b(self, ms):
        self.seek('B', ms)

    def fade_out_deck_a(self, duration=3):
        self.fade_out_deck('A', duration)

    def fade_out_deck_b(self, duration=3):
        self.fade_out_deck('B', duration)

    def is_deck_a_playing(self):
        return self.get_state('A')['is_playing']

    def is_deck_b_playing(self):
        return self.get_state('B')['is_playing']

    def is_playing(self, deck='A'):
        return self.get_state(deck)['is_playing']

    def is_finished(self, deck='A'):
        return self.get_state(deck)['is_ended']

    def get_remaining_ms(self, deck='A'):
        return self.get_state(deck)['remaining_ms']

    def crossfade(self, duration=None):
        """Legacy forward crossfade (A→B) routed through the unified method."""
        if self.active_deck != 'A':
            # If caller asked for A→B but active is already B, nothing to do.
            return
        self.crossfade_to_standby(duration=duration)

    def crossfade_ba(self, duration=None):
        """Legacy reverse crossfade (B→A) routed through the unified method."""
        if self.active_deck != 'B':
            return
        self.crossfade_to_standby(duration=duration)

    def get_position(self):
        """Legacy nested dict consumed by the existing pollPosition UI."""
        try:
            return {
                'deck_a': self.get_state('A'),
                'deck_b': self.get_state('B'),
                'active_deck': self.active_deck,
                'is_crossfading': self.is_crossfading,
            }
        except Exception as e:
            return {'error': str(e)}
