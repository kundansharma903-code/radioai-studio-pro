"""
Studio sweeper overlay dispatch — Phase 1 wiring (auto + manual).

Operator scenario: a clock pattern includes a sweeper slot. When the
scheduler returns it during AUTO playback, Studio must layer the
sweeper on a separate BASS channel via SweeperEngine — NOT load it
into the deck (which would replace the playing song).

This file pins the new contract:
  • _compute_next_song detects item_type='sweeper', fires the overlay
    via _dispatch_overlay_sweeper, and re-calls pick_next_item to fetch
    the actual deck candidate (skip-past-sweepers).
  • The skip is bounded — a clock that emits nothing but sweepers can't
    infinite-recurse; after _SWEEPER_SKIP_BUDGET (4) consecutive
    sweepers, _compute_next_song falls through to the static-queue
    fallback (or returns None if that's empty too).
  • _dispatch_overlay_sweeper writes a 'sweeper' row to broadcast_log
    so the History panel reflects every aired sweeper, scheduler-driven
    or manual.
  • Manual sweeper play (_on_play_sweeper_overlay) reads the row from
    DB and routes through the same overlay path.
  • All paths no-op gracefully when no SweeperEngine is wired or the
    deck is idle.
"""

from __future__ import annotations

import uuid

import pytest

from PyQt6.QtCore import pyqtSignal, QObject

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


class _FakeScheduler:
    """pick_next_item returns items from an internal queue, one per call.
    The queue starts EMPTY so Studio's idle-state setup (which calls
    _compute_next_song twice during ctor for NEXT chip + RDS panel) drains
    nothing. Tests then `queue(...)` items POST-ctor and call
    _compute_next_song to exercise the overlay path.

    is_running flag is operator-controlled."""

    def __init__(self):
        self._items: list[dict] = []
        self._running = True
        self.spot_due           = _RecordingSignal()
        self.song_auto_advance  = _RecordingSignal()
        self.break_approaching  = _RecordingSignal()
        self.next_break_in      = _RecordingSignal()
        self.schedule_reloaded  = _RecordingSignal()
        self.error_occurred     = _RecordingSignal()
        self.started            = _RecordingSignal()
        self.stopped            = _RecordingSignal()
        self.active_clock_changed = _RecordingSignal()

    def is_running(self):  return self._running
    def start(self):       self._running = True
    def stop(self):        self._running = False

    def queue(self, *items):
        """Push items to be returned by subsequent pick_next_item calls."""
        self._items.extend(items)

    def pick_next_item(self, _now=None):
        return self._items.pop(0) if self._items else None

    def peek_next(self, n=5, now=None):
        return list(self._items[:n])


class _FakeSweeperEngine:
    """Records schedule_for_song() calls so tests can assert the overlay
    path was invoked with the right shape."""

    def __init__(self):
        self.scheduled = []   # list of (song_info, sweeper_info, deck_handle)
        self.cancelled = 0

    def schedule_for_song(self, song_info, sweeper_info, deck_handle,
                          on_start=None, on_end=None):
        self.scheduled.append({
            "song":      dict(song_info),
            "sweeper":   dict(sweeper_info),
            "deck":      deck_handle,
        })

    def cancel(self):
        self.cancelled += 1


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    return Database()


def _make_studio(db, scheduler=None, sweeper_engine=None) -> Studio:
    s = Studio(db, parent=None,
               engine=None, scheduler=scheduler,
               instant_jingle_engine=None,
               sweeper_engine=sweeper_engine)
    return s


def _song_item(item_id, title="Song", file_path="dummy.mp3"):
    return {
        "item_type":   "song",
        "item_id":     int(item_id),
        "title":       title,
        "artist":      "Artist",
        "file_path":   file_path,
        "duration_ms": 180000,
        "clock_id":    1,
        "slot_idx":    0,
    }


def _sweeper_item(item_id, position="Bridge at End"):
    return {
        "item_type":          "sweeper",
        "item_id":            int(item_id),
        "title":              f"SW-{item_id}",
        "artist":             "SWEEPER",
        "file_path":          f"sweeper_{item_id}.mp3",
        "duration_ms":        8000,
        "position":           position,
        "volume_sweeper_pct": 95,
        "offset_seconds":     0.0,
        "clock_id":           1,
        "slot_idx":           1,
    }


# ── Auto-dispatch skip-past-sweepers ────────────────────────────────────────

def test_compute_next_song_skips_sweeper_and_returns_song(qapp, db):
    """Scheduler emits [sweeper, song]. Studio must overlay the sweeper
    and return the song to the deck."""
    sched = _FakeScheduler()
    swe = _FakeSweeperEngine()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=swe)
    # Queue items POST-ctor so Studio's idle-state setup doesn't drain them.
    sched.queue(_sweeper_item(11), _song_item(101))
    # Need a deck song so the overlay path doesn't no-op
    studio._playback_cid = 999
    studio._current_track = {"id": 100, "duration_ms": 180000}
    studio._current_duration_ms = 180000

    nxt = studio._compute_next_song(after_id=None)

    assert nxt is not None and nxt["id"] == 101 and nxt["_item_type"] == "song"
    assert len(swe.scheduled) == 1
    assert swe.scheduled[0]["sweeper"]["file_path"] == "sweeper_11.mp3"
    assert swe.scheduled[0]["sweeper"]["position"] == "Bridge at End"
    assert swe.scheduled[0]["deck"] == 999
    studio.deleteLater()


def test_compute_next_song_skips_multiple_sweepers(qapp, db):
    """Three sweepers in a row, then a song. All sweepers fire; deck
    gets the song."""
    sched = _FakeScheduler()
    swe = _FakeSweeperEngine()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=swe)
    sched.queue(
        _sweeper_item(1, "Start of Song"),
        _sweeper_item(2, "Before Intro"),
        _sweeper_item(3, "Before End"),
        _song_item(50),
    )
    studio._playback_cid = 1
    studio._current_track = {"id": 49, "duration_ms": 200000}
    studio._current_duration_ms = 200000

    nxt = studio._compute_next_song(after_id=None)

    assert nxt is not None and nxt["id"] == 50
    assert len(swe.scheduled) == 3
    positions = [s["sweeper"]["position"] for s in swe.scheduled]
    assert positions == ["Start of Song", "Before Intro", "Before End"]
    studio.deleteLater()


def test_compute_next_song_skip_budget_bounded(qapp, db):
    """A clock that emits nothing but sweepers must not infinite-recurse.
    After _SWEEPER_SKIP_BUDGET sweepers, _compute_next_song falls through
    to the static-queue fallback (here empty → None)."""
    sched = _FakeScheduler()
    swe = _FakeSweeperEngine()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=swe)
    # Budget is 4 → seed 10 sweepers; only 5 picks happen (initial + 4 skips).
    sched.queue(*[_sweeper_item(i) for i in range(10)])
    studio._playback_cid = 1
    studio._current_track = {"id": 1, "duration_ms": 180000}
    studio._current_duration_ms = 180000
    studio._queue_songs = []   # empty static queue → None on fallback

    nxt = studio._compute_next_song(after_id=None)

    assert nxt is None
    # All 5 picks attempted (initial + 4 skips) were sweepers, all overlaid.
    assert len(swe.scheduled) == 5
    studio.deleteLater()


# ── Overlay metadata round-trip ─────────────────────────────────────────────

def test_overlay_uses_current_track_duration_for_trigger(qapp, db):
    sched = _FakeScheduler()
    swe = _FakeSweeperEngine()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=swe)
    sched.queue(_sweeper_item(7))
    studio._playback_cid = 42
    studio._current_track = {"id": 1, "duration_ms": 220000,
                             "intro_end_ms": 12000}
    studio._current_duration_ms = 220000

    studio._compute_next_song(after_id=None)
    assert len(swe.scheduled) == 1
    payload = swe.scheduled[0]
    assert payload["song"]["duration_ms"] == 220000
    assert payload["song"]["intro_end_ms"] == 12000
    assert payload["sweeper"]["sweeper_volume"] == 95


# ── Graceful no-ops ─────────────────────────────────────────────────────────

def test_sweeper_falls_through_to_deck_when_engine_missing(qapp, db):
    """Sweeper item arrives but sweeper_engine kwarg was None.
    With the position-aware fallback, the sweeper loads to the deck
    and plays sequentially (overlay can't fire without an engine)."""
    sched = _FakeScheduler()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=None)
    sched.queue(_sweeper_item(11), _song_item(101))
    studio._playback_cid = 5
    studio._current_track = {"id": 1, "duration_ms": 180000}

    nxt = studio._compute_next_song(after_id=None)
    # Sweeper falls through to deck-load — first picker output wins.
    assert nxt is not None
    assert nxt["id"] == 11 and nxt["_item_type"] == "sweeper"
    studio.deleteLater()


def test_sweeper_falls_through_to_deck_when_deck_idle(qapp, db):
    """No deck song → no overlay possible. Sweeper falls through to
    deck-load and plays sequentially in queue order — this is the
    bug RR_SW exposed: at song-end EOS the deck is idle, so the
    sweeper's overlay can't fire and we MUST load it as a standalone
    queue item or it'd be silently skipped."""
    sched = _FakeScheduler()
    swe = _FakeSweeperEngine()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=swe)
    sched.queue(_sweeper_item(11), _song_item(101))
    studio._playback_cid = None
    studio._current_track = None
    studio._current_duration_ms = 0

    nxt = studio._compute_next_song(after_id=None)
    assert nxt is not None
    assert nxt["id"] == 11 and nxt["_item_type"] == "sweeper"
    # Overlay engine NOT invoked — sweeper loaded to deck instead.
    assert len(swe.scheduled) == 0
    studio.deleteLater()


def test_independent_sweeper_always_falls_through_to_deck(qapp, db):
    """position='Independent' is the explicit standalone marker —
    always load to deck even if the deck has a song. Operator
    explicitly told the scheduler this sweeper is its own queue
    item, not an overlay."""
    sched = _FakeScheduler()
    swe = _FakeSweeperEngine()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=swe)
    sched.queue(_sweeper_item(11, position="Independent"))
    studio._playback_cid = 999
    studio._current_track = {"id": 1, "duration_ms": 180000}
    studio._current_duration_ms = 180000

    nxt = studio._compute_next_song(after_id=None)
    assert nxt is not None
    assert nxt["_item_type"] == "sweeper"
    assert nxt["id"] == 11
    # Even with deck song available, Independent never overlays.
    assert len(swe.scheduled) == 0
    studio.deleteLater()


# ── Manual play hook ────────────────────────────────────────────────────────

def test_manual_sweeper_play_routes_through_overlay(qapp, db):
    """Operator clicks a sweeper in the Libraries panel: Studio reads
    the row from DB, builds an overlay item, and dispatches."""
    prefix = f"_test_studio_swp_overlay_{uuid.uuid4().hex[:8]}_"
    conn = db._conn()
    cur = conn.execute(
        "INSERT INTO sweepers (name, category, file_path, duration_ms, "
        "position, properties, is_enabled) VALUES "
        "(?, 'Station', 'manual.mp3', 7000, 'Independent', 'Special', 1)",
        [prefix + "Manual"])
    sid = int(cur.lastrowid)
    conn.commit()
    try:
        swe = _FakeSweeperEngine()
        studio = _make_studio(db, scheduler=None, sweeper_engine=swe)
        studio._playback_cid = 17
        studio._current_track = {"id": 9, "duration_ms": 180000}
        studio._current_duration_ms = 180000

        studio._on_play_sweeper_overlay(sid)

        assert len(swe.scheduled) == 1
        payload = swe.scheduled[0]
        assert payload["sweeper"]["file_path"] == "manual.mp3"
        assert payload["sweeper"]["position"] == "Independent"
        assert payload["deck"] == 17
        studio.deleteLater()
    finally:
        conn.execute("DELETE FROM sweepers WHERE id = ?", [sid])
        conn.commit()


def test_manual_sweeper_play_disabled_id_is_no_op(qapp, db):
    """Disabled sweeper rows must not overlay (engine never invoked)."""
    prefix = f"_test_studio_swp_overlay_{uuid.uuid4().hex[:8]}_"
    conn = db._conn()
    cur = conn.execute(
        "INSERT INTO sweepers (name, category, file_path, duration_ms, "
        "position, is_enabled) VALUES "
        "(?, 'Station', 'x.mp3', 5000, 'Bridge at End', 0)",
        [prefix + "Disabled"])
    sid = int(cur.lastrowid)
    conn.commit()
    try:
        swe = _FakeSweeperEngine()
        studio = _make_studio(db, scheduler=None, sweeper_engine=swe)
        studio._playback_cid = 1
        studio._current_track = {"id": 1, "duration_ms": 180000}
        studio._current_duration_ms = 180000

        studio._on_play_sweeper_overlay(sid)

        assert len(swe.scheduled) == 0
        studio.deleteLater()
    finally:
        conn.execute("DELETE FROM sweepers WHERE id = ?", [sid])
        conn.commit()


# ── broadcast_log ───────────────────────────────────────────────────────────

def test_overlay_writes_sweeper_row_to_broadcast_log(qapp, db):
    sched = _FakeScheduler()
    swe = _FakeSweeperEngine()
    studio = _make_studio(db, scheduler=sched, sweeper_engine=swe)
    sched.queue(_sweeper_item(33), _song_item(200))
    studio._playback_cid = 1
    studio._current_track = {"id": 1, "duration_ms": 180000}
    studio._current_duration_ms = 180000

    before = db._conn().execute(
        "SELECT COUNT(*) AS n FROM broadcast_log WHERE entry_type='sweeper'"
    ).fetchone()["n"]

    studio._compute_next_song(after_id=None)

    after = db._conn().execute(
        "SELECT COUNT(*) AS n FROM broadcast_log WHERE entry_type='sweeper'"
    ).fetchone()["n"]
    assert after == before + 1
    last = db._conn().execute(
        "SELECT entry_type, song_id, slot_idx, was_manual FROM broadcast_log "
        "WHERE entry_type='sweeper' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert last["entry_type"] == "sweeper"
    assert last["song_id"] is None
    # slot_idx came from the scheduler item (1)
    assert int(last["slot_idx"]) == 1
    # clock_id was set on the scheduler item → was_manual=0
    assert int(last["was_manual"]) == 0
    studio.deleteLater()
