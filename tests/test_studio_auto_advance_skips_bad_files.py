"""
Studio auto-advance — skip-past for items with missing/invalid file_path.

Operator (Kavish) reported 2026-05-07: added a sweeper "RR_SW" with
no audio file picked, scheduled it in a clock. AUTO mode on. After
the first song ended, no next song played — the player stopped.

Root cause: the scheduler picked RR_SW as the next deck candidate
(deck-idle fallback for a sweeper, working as designed since the
RR_SW regression fix in commit 111c4ec). _on_queue_song_play saw the
empty file_path, logged "file missing", and silently returned.
Nothing else fired — the broadcast stalled because there was no
"try the next item" retry path.

Fix: _compute_next_song validates file_path BEFORE returning the
candidate. If the path is empty or doesn't exist, the cursor advances
and the loop continues to the next slot. Bounded by _SKIP_BUDGET so
a clock full of broken rows can't infinite-loop.

Pinned behaviour:
  • A song row with empty file_path is skipped; the next valid item
    is returned to the deck.
  • A sweeper row with empty file_path is skipped (deck-idle case).
  • Mixed broken + valid: walks past all broken rows up to the
    budget; returns the first valid candidate.
  • Skip budget exhausted (≥7 broken rows in a row) → returns None
    and falls back to static queue.
  • _on_queue_song_play, when given a bad path, applies idle state
    + status pills (UX safety: no phantom "now playing" tile).
"""

from __future__ import annotations

import os
import tempfile

import pytest

from core.database import Database
from ui.studio import Studio


# ── Shared fakes ────────────────────────────────────────────────────────────

class _RecordingSignal:
    def __init__(self):
        self._slots = []
    def connect(self, fn):  self._slots.append(fn)
    def emit(self, *a, **k):
        for fn in list(self._slots):
            fn(*a, **k)


class _FakeScheduler:
    def __init__(self):
        self._items: list[dict] = []
        self._running = True
        for n in ("spot_due", "song_auto_advance", "break_approaching",
                   "next_break_in", "schedule_reloaded", "error_occurred",
                   "started", "stopped", "active_clock_changed"):
            setattr(self, n, _RecordingSignal())

    def is_running(self):  return self._running
    def stop(self):        self._running = False

    def queue(self, *items):
        self._items.extend(items)

    def pick_next_item(self, _now=None):
        return self._items.pop(0) if self._items else None

    def peek_next(self, n=5, now=None):
        return list(self._items[:n])


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def real_audio_path(tmp_path):
    """A real on-disk file so the file_path-existence check passes.
    Contents don't matter — _compute_next_song only checks
    os.path.exists, not BASS-decodable."""
    p = tmp_path / "fake_song.mp3"
    p.write_bytes(b"fake")
    return str(p)


def _make_studio(db) -> Studio:
    return Studio(db, parent=None, engine=None,
                  scheduler=None, instant_jingle_engine=None,
                  sweeper_engine=None)


def _song(item_id, title, file_path):
    return {
        "item_type": "song", "item_id": int(item_id),
        "title": title, "artist": "A", "file_path": file_path,
        "duration_ms": 180000, "clock_id": 1, "slot_idx": item_id,
    }


def _sweeper(item_id, file_path, position="Independent"):
    return {
        "item_type": "sweeper", "item_id": int(item_id),
        "title": f"SW-{item_id}", "artist": "SWEEPER",
        "file_path": file_path, "duration_ms": 8000,
        "position": position,
        "clock_id": 1, "slot_idx": item_id,
    }


# ── Skip-past behaviour ─────────────────────────────────────────────────────

def test_skips_song_with_empty_file_path(qapp, db, real_audio_path):
    sched = _FakeScheduler()
    studio = _make_studio(db)
    studio._scheduler = sched
    sched.queue(
        _song(1, "Broken", ""),                      # empty path
        _song(2, "Valid",  real_audio_path),
    )

    nxt = studio._compute_next_song(after_id=None)

    assert nxt is not None
    assert nxt["id"] == 2 and nxt["title"] == "Valid"
    studio.deleteLater()


def test_skips_song_with_nonexistent_file_path(qapp, db, real_audio_path):
    sched = _FakeScheduler()
    studio = _make_studio(db)
    studio._scheduler = sched
    sched.queue(
        _song(1, "Broken", "C:\\nonexistent\\file.mp3"),
        _song(2, "Valid",  real_audio_path),
    )

    nxt = studio._compute_next_song(after_id=None)

    assert nxt is not None
    assert nxt["id"] == 2 and nxt["title"] == "Valid"
    studio.deleteLater()


def test_skips_sweeper_with_empty_file_path_at_eos(qapp, db, real_audio_path):
    """RR_SW regression: sweeper without a picked audio file lands
    on the deck (deck-idle fallback for sweepers), but file_path is
    empty so it'd stall the player. Skip-past + return next song."""
    sched = _FakeScheduler()
    studio = _make_studio(db)
    studio._scheduler = sched
    sched.queue(
        _sweeper(1, "", position="Independent"),     # RR_SW shape
        _song(2, "Valid", real_audio_path),
    )
    studio._playback_cid = None
    studio._current_track = None

    nxt = studio._compute_next_song(after_id=None)

    assert nxt is not None
    assert nxt["id"] == 2 and nxt["_item_type"] == "song"
    studio.deleteLater()


def test_skips_multiple_consecutive_broken_rows(qapp, db, real_audio_path):
    sched = _FakeScheduler()
    studio = _make_studio(db)
    studio._scheduler = sched
    sched.queue(
        _song(1, "B1", ""),
        _song(2, "B2", "missing.mp3"),
        _song(3, "B3", ""),
        _song(4, "Valid", real_audio_path),
    )

    nxt = studio._compute_next_song(after_id=None)

    assert nxt is not None and nxt["id"] == 4
    studio.deleteLater()


def test_skip_budget_caps_broken_run(qapp, db):
    """A clock full of broken rows must not infinite-loop. Budget is
    7 (initial + 6 skips) — beyond that we fall through to static
    queue (None when empty)."""
    sched = _FakeScheduler()
    studio = _make_studio(db)
    studio._scheduler = sched
    # 10 broken rows, budget 7
    sched.queue(*[_song(i, f"B{i}", "") for i in range(10)])
    studio._queue_songs = []

    nxt = studio._compute_next_song(after_id=None)
    assert nxt is None
    studio.deleteLater()


# ── _on_queue_song_play idles on bad file ──────────────────────────────────

def test_on_queue_song_play_applies_idle_state_on_missing_file(qapp, db):
    """Defensive UX: a bad path slipping through to _on_queue_song_play
    must idle the panels rather than leave a phantom now-playing tile."""
    studio = _make_studio(db)
    # Fake an engine that would otherwise be real
    class _FakeEngine:
        def cleanup(self, *_): pass
    studio._engine = _FakeEngine()
    # Pre-populate as if a previous song was loaded
    studio._current_track = {"id": 99, "title": "Prev"}
    studio._playback_cid = 5

    studio._on_queue_song_play({"id": 100, "title": "Bad",
                                 "file_path": "no_such_file.mp3"})

    assert studio._current_track is None
    studio.deleteLater()
