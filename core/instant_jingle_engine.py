"""
RadioAI Studio Pro — Instant Jingle Engine (Phase B4 — adapter).

Thin adapter over `core.audio.AudioEngine`. Maps `pad_id → channel_id`
and forwards the IJE public API onto the shared multi-channel engine.

The polyphony cap (8 pads) is enforced HERE — not at the engine level —
so it filters to JINGLE PAD channels only. Other consumers of the same
AudioEngine (Songs Library row preview, Audio Cue Editor PREVIEW, Spots
Now Airing) keep their channels independent of the jingle pad cap.

Public API preserved (caller in ui/instant_jingles.py is untouched):
  - play_pad(pad_id, file_path, volume, loop)
  - stop_pad(pad_id)
  - stop_all()
  - is_playing(pad_id)
  - active_pad_ids()
  - get_duration_ms(file_path)

Improvement over the pre-B4 implementation: `pad_ended` signal now
actually fires on natural EOS (the engine's playback_ended signal does
the heavy lifting; we translate cid → pad_id).

If this rebase causes regressions, revert via:
  git revert <Phase B4 commit hash>
The pre-rebase direct-BASS implementation is preserved in git history
(the commit prior to Phase B4 — see `git log --oneline core/instant_jingle_engine.py`).
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal


log = logging.getLogger("InstantJingleEngine")


class InstantJingleEngine(QObject):
    """Multi-channel jingle player. Adapter over AudioEngine.

    Usage::

        engine = AudioEngine(parent=main_window)
        ije = InstantJingleEngine(engine=engine)
        ije.play_pad(pad_id=42, file_path='/path/x.mp3', volume=90, loop=False)
        ije.stop_pad(42)
        ije.stop_all()
    """

    # Same signals as the legacy implementation. The receiver in
    # ui/instant_jingles.py connects to all three.
    pad_started = pyqtSignal(int)   # pad_id — when play_pad succeeds
    pad_ended   = pyqtSignal(int)   # pad_id — natural EOS (now ACTUALLY wired)
    pad_stopped = pyqtSignal(int)   # pad_id — manual stop / stop_all / eviction

    MAX_POLYPHONY = 8

    def __init__(self, engine=None, parent=None):
        super().__init__(parent)
        self._engine = engine
        # pad_id → channel_id. Insertion order = age, used for eviction.
        self._pads: dict[int, int] = {}
        self._lock = threading.Lock()

        # Wire engine.playback_ended → translate cid to pad_id and emit
        # pad_ended. Pre-B4 the pad_ended signal was declared but never
        # fired — the rebase fixes that for free.
        if self._engine is not None:
            self._engine.playback_ended.connect(self._on_engine_ended)

    # ── Public API ────────────────────────────────────────────────────────

    def play_pad(self, pad_id: int, file_path: str,
                 volume: int = 100, loop: bool = False) -> bool:
        """Play a pad. Returns True if playback started.

        Re-trigger semantics: if the same pad_id is already playing, the
        existing channel is stopped first (BASS handles fresh restart).

        Polyphony cap (8): filters to JINGLE PAD channels only — does NOT
        touch other AudioEngine consumers. When at cap, the oldest pad
        (insertion order) is evicted.
        """
        if not file_path:
            log.warning(f"[pad {pad_id}] no file_path — skipping")
            return False
        if not os.path.exists(file_path):
            log.warning(f"[pad {pad_id}] file missing: {file_path}")
            return False
        if self._engine is None:
            log.warning(f"[pad {pad_id}] no engine — IJE inactive")
            return False

        with self._lock:
            # Re-trigger: stop existing channel for this pad
            if pad_id in self._pads:
                old_cid = self._pads.pop(pad_id)
                self._cleanup_silently(old_cid)

            # Polyphony cap (filtered to OUR pads only)
            if len(self._pads) >= self.MAX_POLYPHONY:
                oldest_pid, oldest_cid = next(iter(self._pads.items()))
                log.warning(
                    f"polyphony cap reached ({self.MAX_POLYPHONY}); "
                    f"evicting pad {oldest_pid}"
                )
                self._cleanup_silently(oldest_cid)
                del self._pads[oldest_pid]
                self.pad_stopped.emit(int(oldest_pid))

            # Create stream + play via engine. AudioEngine.load_file
            # will raise on missing file or BASS error — propagate as
            # a bool return rather than letting it bubble.
            try:
                cid = self._engine.load_file(file_path, loop=loop)
            except Exception as exc:
                log.error(f"[pad {pad_id}] engine.load_file failed: {exc}")
                return False

            self._engine.set_volume(cid, max(0, min(100, int(volume))))
            self._engine.play(cid)
            self._pads[pad_id] = cid
            log.info(
                f"[pad {pad_id}] playing ch={cid} "
                f"{os.path.basename(file_path)} vol={volume} loop={loop}"
            )

        self.pad_started.emit(int(pad_id))
        return True

    def stop_pad(self, pad_id: int) -> bool:
        """Stop a specific pad. Returns True if it was playing."""
        with self._lock:
            cid = self._pads.pop(pad_id, None)
        if cid is None:
            return False
        self._cleanup_silently(cid)
        log.info(f"[pad {pad_id}] stopped (ch={cid})")
        self.pad_stopped.emit(int(pad_id))
        return True

    def stop_all(self) -> int:
        """Emergency stop — kills every JINGLE PAD channel only. Other
        AudioEngine consumers (library / cue editor / spots) are untouched.

        Returns count stopped."""
        with self._lock:
            ids = list(self._pads.keys())
            for _pid, cid in self._pads.items():
                self._cleanup_silently(cid)
            self._pads.clear()
        for pid in ids:
            self.pad_stopped.emit(int(pid))
        log.warning(f"STOP ALL — killed {len(ids)} jingle pad(s)")
        return len(ids)

    def is_playing(self, pad_id: int) -> bool:
        """True if the pad is currently in our active map. Mirrors the
        pre-B4 semantics — checks dict membership, not BASS state."""
        return pad_id in self._pads

    def active_pad_ids(self) -> list[int]:
        with self._lock:
            return list(self._pads.keys())

    def get_duration_ms(self, file_path: str) -> Optional[int]:
        """Probe a file's duration without consuming a channel slot.
        Returns ms, or None if unreadable."""
        if self._engine is None:
            return None
        return self._engine.probe_duration_ms(file_path)

    # ── Internals ─────────────────────────────────────────────────────────

    def _cleanup_silently(self, cid: int) -> None:
        """engine.cleanup(cid) wrapped to swallow any error — IJE never
        propagates BASS-level errors back to the UI; the caller already
        knows the pad is "stopped" by virtue of having been removed from
        the dict."""
        try:
            self._engine.cleanup(cid)
        except Exception as exc:
            log.warning(f"engine.cleanup({cid}) error: {exc}")

    def _on_engine_ended(self, channel_id: int) -> None:
        """AudioEngine reports natural EOS — translate cid to our pad_id
        and fire pad_ended. Filtered to OUR channels (the engine is
        shared)."""
        pad_id = None
        with self._lock:
            for pid, cid in list(self._pads.items()):
                if cid == channel_id:
                    pad_id = pid
                    del self._pads[pid]
                    break
        if pad_id is not None:
            log.info(f"[pad {pad_id}] ended (natural EOS, ch={channel_id})")
            self.pad_ended.emit(int(pad_id))
