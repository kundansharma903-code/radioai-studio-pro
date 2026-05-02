"""RadioAI Studio Pro -- Stitcher Engine (Jazler-style pre-mix)

Professional approach: build ONE continuous AudioSegment from all
parts (opening + hooks + separators + closing) using pydub, export
to a temp WAV, then play it with a SINGLE VLC player. This
eliminates all gaps and cut-offs by design -- there is only one
audio stream, so transitions are sample-accurate.

Jazler SOHO does the same thing internally: it pre-renders the
"Coming Up Next" block into a contiguous buffer, then streams it
through one output channel.
"""

import os
import tempfile
import threading
import time

import vlc


def _get_duration_safe(vlc_instance, path, timeout_s=0.6):
    """Return file duration in milliseconds (mutagen fast path)."""
    try:
        from mutagen import File as MutagenFile
        mf = MutagenFile(path)
        if mf and mf.info and mf.info.length:
            return int(mf.info.length * 1000)
    except Exception:
        pass
    try:
        media = vlc_instance.media_new(path)
        media.parse_with_options(1, 0)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            d = media.get_duration()
            if d and d > 0:
                return int(d)
            time.sleep(0.03)
        return int(media.get_duration() or 0)
    except Exception:
        return 0


def _equal_power_fade(progress):
    """Equal-power crossfade fractions (kept for API compat)."""
    import math
    p = max(0.0, min(1.0, progress))
    return math.cos(p * math.pi / 2), math.sin(p * math.pi / 2)


class StitcherEngine:
    """Pre-mix stitcher: pydub build + single VLC playback.

    Usage::

        engine = StitcherEngine(vlc_instance)
        engine.play_block(sequence, target_vol=85, on_done=callback)

    *sequence* is the list from ``bridge.get_stitcher_play_sequence()``
    with ``{file_path, seek_sec, duration_sec, play_full, label, type}``.
    """

    HOOK_DURATION_MS = 8000
    POLL_INTERVAL_S = 0.25
    END_DRAIN_S = 0.30          # wait after VLC EndReached

    def __init__(self, vlc_instance):
        self._inst = vlc_instance
        self._player = vlc_instance.media_player_new()
        self._running = False
        self._thread = None
        self._temp_path = None   # cleaned up after playback

    # -- public --------------------------------------------------------

    def play_block(self, sequence, target_vol=85, on_step=None, on_done=None):
        if self._running:
            return
        self._running = True

        def _run():
            try:
                self._build_and_play(sequence, target_vol, on_step)
            except Exception as e:
                print(f"[StitcherEngine] error: {e}")
            finally:
                self._cleanup()
                self._running = False
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            self._player.stop()
        except Exception:
            pass

    @property
    def is_running(self):
        return self._running

    # -- internal: build + play ----------------------------------------

    def _build_and_play(self, sequence, target_vol, on_step):
        from pydub import AudioSegment

        # Filter to valid files
        steps = [s for s in sequence
                 if s.get("file_path") and os.path.exists(s["file_path"])]
        if not steps:
            return

        # -- STEP 1: pre-mix into one AudioSegment ---------------------
        print("[StitcherEngine] building pre-mix...")
        final = AudioSegment.empty()

        for idx, step in enumerate(steps):
            path = step["file_path"]
            try:
                audio = AudioSegment.from_file(path)
            except Exception as e:
                print(f"[StitcherEngine] skip {path}: {e}")
                continue

            if step.get("play_full"):
                # Opening / Separator / Closing -- use the entire file
                segment = audio
            else:
                # Hook clip -- slice exactly 8 seconds from hook_point
                start_ms = int((step.get("seek_sec", 0) or 0) * 1000)
                end_ms = start_ms + self.HOOK_DURATION_MS
                # Clamp to file length
                if start_ms >= len(audio):
                    start_ms = max(0, len(audio) - self.HOOK_DURATION_MS)
                if end_ms > len(audio):
                    end_ms = len(audio)
                segment = audio[start_ms:end_ms]

            final = final + segment

            if on_step:
                try:
                    on_step(idx, step)
                except Exception:
                    pass

        if len(final) == 0:
            print("[StitcherEngine] pre-mix is empty, nothing to play")
            return

        total_sec = len(final) / 1000.0
        print(f"[StitcherEngine] pre-mix ready: {total_sec:.1f}s "
              f"({len(final)}ms, {len(steps)} parts)")

        # -- STEP 2: export to temp WAV --------------------------------
        # WAV avoids any ffmpeg re-encoding overhead and is lossless.
        fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="stitcher_")
        os.close(fd)
        self._temp_path = tmp_path

        try:
            final.export(tmp_path, format="wav")
        except Exception as e:
            print(f"[StitcherEngine] export error: {e}")
            return

        file_size = os.path.getsize(tmp_path)
        print(f"[StitcherEngine] exported to {tmp_path} ({file_size} bytes)")

        if not self._running:
            return

        # -- STEP 3: play with single VLC player -----------------------
        media = self._inst.media_new(tmp_path)
        self._player.set_media(media)
        self._player.audio_set_volume(target_vol)
        self._player.play()

        # Re-apply volume after VLC latches (Windows quirk)
        time.sleep(0.15)
        self._player.audio_set_volume(target_vol)

        print(f"[StitcherEngine] playing ({total_sec:.1f}s)...")

        # -- STEP 4: wait for playback to finish -----------------------
        # Poll VLC state -- single file, single player, no chaining.
        while self._running:
            state = self._player.get_state()
            if state == vlc.State.Ended:
                break
            if state == vlc.State.Error:
                print("[StitcherEngine] VLC error during playback")
                break
            time.sleep(self.POLL_INTERVAL_S)

        # Drain buffer: VLC fires Ended ~200ms before the audio output
        # buffer is fully empty. Wait 300ms so the last samples play.
        time.sleep(self.END_DRAIN_S)

        self._player.stop()
        print("[StitcherEngine] playback complete")

    # -- cleanup -------------------------------------------------------

    def _cleanup(self):
        """Delete the temp WAV after playback."""
        try:
            self._player.stop()
        except Exception:
            pass
        if self._temp_path and os.path.exists(self._temp_path):
            try:
                os.remove(self._temp_path)
                print(f"[StitcherEngine] cleaned up {self._temp_path}")
            except Exception:
                pass
            self._temp_path = None
