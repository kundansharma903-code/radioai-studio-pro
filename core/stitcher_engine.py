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

    @staticmethod
    def assemble_sequence(config: dict, songs: list) -> list:
        """Build a play_block-ready sequence from a stitcher_config
        dict + a list of song dicts. Returns ``[]`` when there aren't
        enough valid hooks AND no fallback is configured — caller
        decides whether to fire or skip.

        Single source of truth shared by:
          • The Stitcher screen's "▶ Preview Full" button
          • Studio's break-approaching auto-fire path

        ``songs`` is a list of dicts with: ``id`` (optional),
        ``file_path`` (required for hook extraction), ``hook_in_ms`` /
        ``hook_out_ms`` (required and must be valid).

        Sequence shape:
          [opening] + [hook1, sep, hook2, sep, ..., hookN] + [closing]

        When fewer than min_hooks_required songs have valid hooks,
        the sequence collapses to ``[fallback]`` if a fallback path
        is set + on disk; else returns ``[]``."""
        opening = (config.get("opening_audio") or "").strip()
        sep = (config.get("separator_audio") or "").strip()
        closing = (config.get("closing_audio") or "").strip()
        fallback = (config.get("fallback_audio") or "").strip()
        min_hooks = int(config.get("min_hooks_required") or 2)
        max_hooks = int(config.get("max_hooks") or 4)

        # Filter to songs with playable file + valid hook range.
        hooked: list[dict] = []
        for s in songs or []:
            fp = (s.get("file_path") or "").strip()
            if not fp or not os.path.exists(fp):
                continue
            hi = int(s.get("hook_in_ms") or 0)
            ho = int(s.get("hook_out_ms") or 0)
            if hi <= 0 or ho <= hi:
                continue
            hooked.append({
                "id":         s.get("id"),
                "file_path":  fp,
                "hook_in_ms": hi,
                "hook_out_ms": ho,
                "title":      s.get("title") or "HOOK",
            })
            if len(hooked) >= max_hooks:
                break

        # Not enough hooks → fallback OR empty.
        if len(hooked) < min_hooks:
            if fallback and os.path.exists(fallback):
                return [{"file_path": fallback, "play_full": True,
                         "label": "FALLBACK"}]
            return []

        seq: list[dict] = []
        if opening and os.path.exists(opening):
            seq.append({"file_path": opening, "play_full": True,
                        "label": "OPENING"})
        for i, song in enumerate(hooked):
            seq.append({
                "file_path": song["file_path"],
                "seek_sec":  song["hook_in_ms"] / 1000.0,
                "label":     song["title"],
            })
            # Separator between hooks (not after the last).
            if i < len(hooked) - 1 and sep and os.path.exists(sep):
                seq.append({"file_path": sep, "play_full": True,
                            "label": "SEP"})
        if closing and os.path.exists(closing):
            seq.append({"file_path": closing, "play_full": True,
                        "label": "CLOSING"})
        return seq

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
