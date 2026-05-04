"""
RadioAI Studio Pro — Stitcher Engine (Jazler-style pre-mix, BASS playback)

Pre-mixes a sequence of audio parts into one contiguous WAV via pydub,
then plays the single WAV through BASS for gap-free, zero-latency output.

BASS license: evaluation DLL. Purchase commercial license before broadcast.
"""

import os
import tempfile
import threading
import time

from pybass3 import BassStream, BassChannel
import pybass3.bass_module as _bm
from pybass3.codes import channel as _ch

# BASS_STREAM_PRESCAN for accurate duration
BASS_STREAM_PRESCAN = 0x20000


class StitcherEngine:
    """Pre-mix stitcher: pydub build → single BASS stream playback.

    Usage::

        engine = StitcherEngine()
        engine.play_block(sequence, target_vol=85, on_done=callback)

    *sequence*: list of dicts with ``{file_path, seek_sec, play_full, label}``.
    """

    HOOK_DURATION_MS = 8000
    POLL_INTERVAL_S  = 0.15
    END_DRAIN_S      = 0.20

    def __init__(self):
        self._running  = False
        self._thread   = None
        self._handle   = 0        # BASS stream handle
        self._temp_path = None    # cleaned up after playback

    # ── Public ────────────────────────────────────────────────────────────────

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
        if self._handle:
            try:
                BassChannel.Stop(self._handle)
            except Exception:
                pass

    @property
    def is_running(self):
        return self._running

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_and_play(self, sequence, target_vol, on_step):
        from pydub import AudioSegment

        steps = [s for s in sequence
                 if s.get("file_path") and os.path.exists(s["file_path"])]
        if not steps:
            return

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
                segment = audio
            else:
                start_ms = int((step.get("seek_sec", 0) or 0) * 1000)
                end_ms   = start_ms + self.HOOK_DURATION_MS
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
            print("[StitcherEngine] pre-mix empty, nothing to play")
            return

        total_sec = len(final) / 1000.0
        print(f"[StitcherEngine] pre-mix ready: {total_sec:.1f}s ({len(steps)} parts)")

        # Export to temp WAV
        fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="stitcher_")
        os.close(fd)
        self._temp_path = tmp_path

        try:
            final.export(tmp_path, format="wav")
        except Exception as e:
            print(f"[StitcherEngine] export error: {e}")
            return

        if not self._running:
            return

        # Load and play via BASS
        try:
            handle = BassStream.CreateFile(
                False, tmp_path.encode("utf-8"), 0, 0, BASS_STREAM_PRESCAN
            )
        except Exception as e:
            err = _bm.BASS_ErrorGetCode()
            print(f"[StitcherEngine] BASS stream error {err}: {e}")
            return

        self._handle = handle

        # Set volume (BASS volume is 0.0–1.0)
        import ctypes
        from core.audio_engine import _get_dll, BASS_ATTRIB_VOL
        dll = _get_dll()
        dll.BASS_ChannelSetAttribute(handle, BASS_ATTRIB_VOL,
                                     ctypes.c_float(target_vol / 100.0))

        BassChannel.Play(handle, False)
        print(f"[StitcherEngine] playing {total_sec:.1f}s via BASS...")

        # Poll until ended
        while self._running:
            state = BassChannel.IsActive(handle)
            if state == _ch.ACTIVE_STOPPED:
                break
            if state == _ch.ACTIVE_STALLED:
                print("[StitcherEngine] BASS stalled")
                break
            time.sleep(self.POLL_INTERVAL_S)

        time.sleep(self.END_DRAIN_S)
        print("[StitcherEngine] playback complete")

    def _cleanup(self):
        if self._handle:
            try:
                BassChannel.Stop(self._handle)
                BassStream.Free(self._handle)
            except Exception:
                pass
            self._handle = 0

        if self._temp_path and os.path.exists(self._temp_path):
            try:
                os.remove(self._temp_path)
                print(f"[StitcherEngine] cleaned {self._temp_path}")
            except Exception:
                pass
            self._temp_path = None
