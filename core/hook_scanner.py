"""
RadioAI Studio Pro — Auto-Hook Scanner.

Detects each song's HOOK (the catchiest slice — almost always the
chorus) so the Stitcher's "Coming Up Next" montage has real material,
without the operator hand-placing hook markers on hundreds of bulk-
imported songs.

PRINCIPLE (industry + literature)
---------------------------------
Chorus-detection research (Goto's RefraiD / pychorus) finds the most
REPEATED section; the practical playout-world heuristic — and the
refinement used on top of repetition methods — is that the chorus is
the most ENERGETIC sustained section of the song (highest average
RMS / onset density). Full repetition analysis needs heavy deps
(librosa/numpy DSP stack); the energy heuristic needs only pydub,
which the Stitcher already uses for its pre-mix, and lands on or
inside the chorus for the vast majority of produced pop/film music.

ALGORITHM
---------
1. Decode the file (pydub → ffmpeg), downmix to mono.
2. RMS loudness per 500 ms chunk.
3. Search only the 15%–75% span of the song (skips the intro build
   and the outro fade, where a raw max-energy pick could drift).
4. Slide a hook-length window (default 8 s, matches
   stitcher_config.hook_duration_seconds) across the span; take the
   window with the highest average energy → that's the chorus region.
5. Onset snap: within the 2 s before the window start, move the
   start to the biggest positive energy jump (the chorus "attack"),
   so the hook begins ON the drop instead of mid-bar.

Pure function + a Qt worker for batch scans. No DB writes here —
the caller persists via db.save_song_cue_points.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

log = logging.getLogger("HookScanner")

CHUNK_MS = 500          # RMS resolution
SEARCH_LO = 0.15        # search span start (fraction of duration)
SEARCH_HI = 0.75        # search span end
ONSET_LOOKBACK_MS = 2000


def detect_hook(file_path: str,
                hook_len_s: float = 8.0) -> Optional[tuple[int, int]]:
    """Return (hook_in_ms, hook_out_ms) for the most-energetic
    sustained section of the song, or None when the file can't be
    analysed (missing/undecodable/too short). Never raises."""
    try:
        if not file_path or not os.path.exists(file_path):
            return None
        from pydub import AudioSegment
        seg = AudioSegment.from_file(file_path).set_channels(1)
        dur_ms = len(seg)
        hook_ms = int(hook_len_s * 1000)
        if dur_ms < hook_ms * 2:          # too short to have an intro+hook
            return None

        # 2. per-chunk RMS
        energies: list[float] = []
        for i in range(0, dur_ms - CHUNK_MS, CHUNK_MS):
            energies.append(float(seg[i:i + CHUNK_MS].rms))
        n = len(energies)
        win = max(1, hook_ms // CHUNK_MS)

        # 3. search span (chunk indices), clamped so the window fits
        lo = int(n * SEARCH_LO)
        hi = min(int(n * SEARCH_HI), n - win)
        if hi <= lo:
            lo, hi = 0, max(1, n - win)

        # 4. max-average-energy window (sliding sum)
        cur = sum(energies[lo:lo + win])
        best, best_i = cur, lo
        for i in range(lo + 1, hi + 1):
            cur += energies[i + win - 1] - energies[i - 1]
            if cur > best:
                best, best_i = cur, i

        # 5. onset snap — biggest energy RISE in the 2 s before start
        back = ONSET_LOOKBACK_MS // CHUNK_MS
        snap_i = best_i
        best_jump = 0.0
        for i in range(max(1, best_i - back), best_i + 1):
            jump = energies[i] - energies[i - 1]
            if jump > best_jump:
                best_jump, snap_i = jump, i

        hook_in = snap_i * CHUNK_MS
        hook_out = min(hook_in + hook_ms, dur_ms - 500)
        if hook_out - hook_in < 1000:      # degenerate — give up cleanly
            return None
        return int(hook_in), int(hook_out)
    except Exception as exc:
        log.debug(f"detect_hook failed for {file_path!r}: {exc}")
        return None


class HookScanWorker(QObject):
    """Batch scanner on its own QThread.

    songs: list of dicts with at least id / file_path / title.
    Emits progress(done, total, title, ok) per song and
    finished(set_count, skip_count, fail_count) at the end.
    The db handle's save_song_cue_points persists each result the
    moment it's found, so a mid-scan abort loses nothing."""

    progress = pyqtSignal(int, int, str, bool)
    finished = pyqtSignal(int, int, int)

    def __init__(self, db, songs: list, hook_len_s: float = 8.0,
                 overwrite: bool = False, parent=None):
        super().__init__(parent)
        self._db = db
        self._songs = list(songs)
        self._hook_len_s = float(hook_len_s)
        self._overwrite = bool(overwrite)
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        done = set_n = skip_n = fail_n = 0
        total = len(self._songs)
        for s in self._songs:
            if self._abort:
                break
            done += 1
            title = str(s.get("title") or "?")
            try:
                if (not self._overwrite
                        and int(s.get("hook_in_ms") or 0) > 0):
                    skip_n += 1          # operator's manual hook — keep
                    self.progress.emit(done, total, title, True)
                    continue
                got = detect_hook(s.get("file_path") or "",
                                  self._hook_len_s)
                if got is None:
                    fail_n += 1
                    self.progress.emit(done, total, title, False)
                    continue
                self._db.save_song_cue_points(int(s["id"]), {
                    "hook_in_ms":  got[0],
                    "hook_out_ms": got[1],
                })
                set_n += 1
                self.progress.emit(done, total, title, True)
            except Exception as exc:
                fail_n += 1
                log.warning(f"hook scan {title!r}: {exc}")
                self.progress.emit(done, total, title, False)
        self.finished.emit(set_n, skip_n, fail_n)


def start_scan(db, songs: list, hook_len_s: float = 8.0,
               overwrite: bool = False) -> tuple[QThread, HookScanWorker]:
    """Spin up a worker on a fresh QThread. Caller keeps references
    to BOTH returns (else Python GC kills the thread) and wires the
    worker's signals before this returns... the thread starts here."""
    thread = QThread()
    worker = HookScanWorker(db, songs, hook_len_s, overwrite)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread, worker
