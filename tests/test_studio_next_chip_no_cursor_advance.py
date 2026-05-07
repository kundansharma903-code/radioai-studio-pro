"""
Studio NEXT chip / RDS panel — non-destructive preview.

Operator (Kavish) audit 2026-05-07: the NEXT chip showed a stale
title while the Up Coming queue showed the correct order. Root cause:
_apply_idle_state and _apply_playing_state were calling
_compute_next_song for display-only purposes, which calls
scheduler.pick_next_item — a DESTRUCTIVE op that advances the
internal cursor. Every song-start triggered a chip refresh, eating
an extra scheduler slot per play. The live broadcast was skipping
clock slots in pairs.

Fix: a new _peek_next_for_display helper uses scheduler.peek_next
(snapshots cursor + restores) so display refreshes never mutate
scheduler state. The 3 display call sites now use peek; the 3
dispatch call sites still use the destructive variant.

This file pins both contracts:
  • _peek_next_for_display does NOT advance _clock_slot_cursor
    even after multiple calls (the bug surface).
  • The returned item is the same one peek_next would return as
    items[0] (or items[1+] when the head is an overlay sweeper).
  • Falls back to static _queue_songs[0] when the scheduler is
    idle or every peeked slot was an overlay sweeper.
  • _compute_next_song (dispatch path) still advances the cursor
    so real EOS-driven playback walks the clock pattern as before.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.studio import Studio


# ── Fakes ───────────────────────────────────────────────────────────────────

class _RecordingSignal:
    def __init__(self):
        self._slots = []
    def connect(self, fn):  self._slots.append(fn)
    def emit(self, *a, **k):
        for fn in list(self._slots):
            fn(*a, **k)


class _CursorTrackingScheduler:
    """Mirrors SchedulerEngine's pick/peek contract:
      • pick_next_item: advances internal cursor, returns popped head.
      • peek_next(n):  snapshots+restores cursor; returns next n items
        without mutating state.
    Lets tests assert that a method call does or does NOT advance
    the cursor.
    """

    def __init__(self):
        self._items: list[dict] = []
        self._cursor = 0
        self._running = True
        for name in ("spot_due", "song_auto_advance", "break_approaching",
                     "next_break_in", "schedule_reloaded", "error_occurred",
                     "started", "stopped", "active_clock_changed"):
            setattr(self, name, _RecordingSignal())

    def is_running(self):  return self._running
    def start(self):       self._running = True
    def stop(self):        self._running = False

    def queue(self, *items):
        self._items.extend(items)

    @property
    def cursor(self):
        return self._cursor

    def pick_next_item(self, _now=None):
        if self._cursor >= len(self._items):
            return None
        item = self._items[self._cursor]
        self._cursor += 1
        return item

    def peek_next(self, n=5, now=None):
        # Snapshot cursor, simulate n picks, restore cursor.
        saved = self._cursor
        out = []
        try:
            for _ in range(int(n)):
                if self._cursor >= len(self._items):
                    break
                out.append(self._items[self._cursor])
                self._cursor += 1
        finally:
            self._cursor = saved
        return out


@pytest.fixture
def db():
    return Database()


def _make_studio(db, scheduler=None, sweeper_engine=None) -> Studio:
    return Studio(db, parent=None, engine=None,
                  scheduler=scheduler,
                  instant_jingle_engine=None,
                  sweeper_engine=sweeper_engine)


def _song(item_id, title):
    return {
        "item_type": "song", "item_id": int(item_id),
        "title": title, "artist": "Artist",
        "file_path": f"{title}.mp3", "duration_ms": 180000,
        "clock_id": 1, "slot_idx": item_id,
    }


def _sweeper(item_id, position="Bridge at End"):
    return {
        "item_type": "sweeper", "item_id": int(item_id),
        "title": f"SW-{item_id}", "artist": "SWEEPER",
        "file_path": f"sw_{item_id}.mp3", "duration_ms": 8000,
        "position": position,
        "clock_id": 1, "slot_idx": item_id,
    }


# ── Cursor invariance under display refreshes ─────────────────────────────

def test_peek_does_not_advance_cursor_single_call(qapp, db):
    sched = _CursorTrackingScheduler()
    studio = _make_studio(db, scheduler=sched)
    # Push items AFTER ctor (init's idle-state setup may run an extra
    # display refresh; we measure from the post-init cursor position).
    sched.queue(_song(101, "Bezubaan"), _song(102, "Piya"))
    cursor_before = sched.cursor

    head = studio._peek_next_for_display(after_id=None)

    assert sched.cursor == cursor_before, \
        "peek must NOT advance cursor"
    assert head is not None
    assert head["id"] == 101 and head["title"] == "Bezubaan"
    studio.deleteLater()


def test_peek_does_not_advance_cursor_repeated_calls(qapp, db):
    """The chip refresh fires on tick + on every state change. Five
    rapid refreshes must still leave the cursor where it started."""
    sched = _CursorTrackingScheduler()
    studio = _make_studio(db, scheduler=sched)
    sched.queue(_song(1, "A"), _song(2, "B"), _song(3, "C"))
    cursor_before = sched.cursor

    for _ in range(5):
        studio._peek_next_for_display(after_id=None)

    assert sched.cursor == cursor_before
    studio.deleteLater()


def test_peek_returns_same_head_on_every_call(qapp, db):
    """Idempotent — repeated peeks return the same head until a real
    pick advances the cursor."""
    sched = _CursorTrackingScheduler()
    studio = _make_studio(db, scheduler=sched)
    sched.queue(_song(1, "A"), _song(2, "B"))

    h1 = studio._peek_next_for_display(after_id=None)
    h2 = studio._peek_next_for_display(after_id=None)
    h3 = studio._peek_next_for_display(after_id=None)

    assert h1["id"] == h2["id"] == h3["id"] == 1
    studio.deleteLater()


# ── Dispatch path still mutates ───────────────────────────────────────────

def test_compute_next_song_advances_cursor(qapp, db):
    """Sanity: the dispatch path (real EOS / Play-from-idle) keeps the
    destructive contract — _compute_next_song eats one slot per call."""
    sched = _CursorTrackingScheduler()
    studio = _make_studio(db, scheduler=sched)
    sched.queue(_song(1, "A"), _song(2, "B"))
    cursor_before = sched.cursor

    n1 = studio._compute_next_song(after_id=None)
    n2 = studio._compute_next_song(after_id=None)

    assert n1["id"] == 1 and n2["id"] == 2
    assert sched.cursor == cursor_before + 2
    studio.deleteLater()


# ── Sweeper-skip parity between peek and pick ─────────────────────────────

def test_peek_skips_overlay_sweeper_when_deck_has_song(qapp, db):
    """If the head item is an overlay-style sweeper AND the deck has
    a song, the real dispatch would skip the sweeper to find a deck
    candidate. The display preview must show the same skipped result —
    otherwise the chip lies about what'll land on the deck."""
    sched = _CursorTrackingScheduler()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=object())
    sched.queue(_sweeper(1, "Bridge at End"), _song(101, "Bezubaan"))
    studio._playback_cid = 5
    studio._current_track = {"id": 99, "duration_ms": 180000}

    head = studio._peek_next_for_display(after_id=None)

    # Should skip the sweeper and show the song
    assert head["id"] == 101 and head["_item_type"] == "song"
    studio.deleteLater()


def test_peek_returns_independent_sweeper_as_deck_candidate(qapp, db):
    """Independent sweepers always go to the deck (sequential play),
    so the chip should announce them as the next deck item."""
    sched = _CursorTrackingScheduler()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=object())
    sched.queue(_sweeper(1, "Independent"), _song(101, "Bezubaan"))
    studio._playback_cid = 5
    studio._current_track = {"id": 99, "duration_ms": 180000}

    head = studio._peek_next_for_display(after_id=None)

    assert head["id"] == 1 and head["_item_type"] == "sweeper"
    studio.deleteLater()


def test_peek_returns_sweeper_when_deck_is_idle(qapp, db):
    """Deck-idle case (RR_SW regression): the sweeper would fall
    through to deck-load during real dispatch, so the chip must show
    it as the next deck item, not skip past."""
    sched = _CursorTrackingScheduler()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=object())
    sched.queue(_sweeper(1, "Bridge at End"), _song(101, "Bezubaan"))
    studio._playback_cid = None
    studio._current_track = None

    head = studio._peek_next_for_display(after_id=None)

    assert head["id"] == 1 and head["_item_type"] == "sweeper"
    studio.deleteLater()


# ── Static-queue fallback ─────────────────────────────────────────────────

def test_peek_falls_back_to_static_queue_when_scheduler_idle(qapp, db):
    """No scheduler running → use the in-memory _queue_songs list."""
    studio = _make_studio(db, scheduler=None)
    if not studio._queue_songs:
        pytest.skip("dev DB has no songs to drive this test")
    head = studio._peek_next_for_display(after_id=None)
    assert head is studio._queue_songs[0]
    studio.deleteLater()
