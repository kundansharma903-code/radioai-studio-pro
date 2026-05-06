"""
Studio v3 — Phase C playback wiring tests.

Covers the five surfaces wired in Phase C:

  1. Bottom-transport ▶ Play button — idle starts the queue (loads
     first track + auto-starts scheduler if not running + flips
     auto-advance ON); playing forwards to pause/resume toggle.
  2. Bottom-transport ■ Stop button — narrow scope: deck channel
     only, jingle pads untouched (latent broadcast-critical bug fix).
  3. AUTO header pill click — toggles scheduler.start/stop AND
     ``_auto_advance_enabled`` together.
  4. Auto-advance gating — EOS path (d) honors
     ``_auto_advance_enabled`` flag (default True, preserves the
     legacy 9 EOS-path tests verbatim).
  5. SIGNAL header pill — 1Hz polling reflects the AudioEngine's
     real "any channel playing?" state.

Pattern mirrors Phase A's ``_FakeIJE`` and Phase B's ``_FakeScheduler``
mock styles. ``_FakeAudioEngine`` exposes the engine surface Studio
actually touches: load_file / play / pause / resume / stop / cleanup
/ get_state / get_active_channels / set_volume / get_duration_ms /
seek_to_ms / cleanup_all, plus the three pyqtSignal-shaped
attributes Studio subscribes to (position_changed, playback_ended,
error_occurred).
"""

from __future__ import annotations

from typing import Optional

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtCore import Qt, QEvent, QPointF

from core.database import Database
from ui.studio import Studio


# ── Test doubles ────────────────────────────────────────────────────────


class _RecordingSignal:
    def __init__(self):
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, _slot=None) -> None:
        self._slots.clear()

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class _FakeAudioEngine:
    """Records every call. Channel ids monotonically increasing.
    State machine tracks per-channel state so get_state can return
    realistic values across pause/resume/stop sequences."""

    def __init__(self):
        self.calls: list[tuple] = []
        self._next_cid: int = 100
        self._states: dict[int, str] = {}
        self.position_changed = _RecordingSignal()
        self.playback_ended   = _RecordingSignal()
        self.error_occurred   = _RecordingSignal()

    def load_file(self, path: str) -> int:
        self._next_cid += 1
        cid = self._next_cid
        self.calls.append(("load_file", path, cid))
        self._states[cid] = "loaded"
        return cid

    def play(self, cid: int) -> None:
        self.calls.append(("play", cid))
        self._states[cid] = "playing"

    def pause(self, cid: int) -> None:
        self.calls.append(("pause", cid))
        self._states[cid] = "paused"

    def resume(self, cid: int) -> None:
        self.calls.append(("resume", cid))
        self._states[cid] = "playing"

    def stop(self, cid: int) -> None:
        self.calls.append(("stop", cid))
        self._states[cid] = "stopped"

    def cleanup(self, cid: int) -> None:
        self.calls.append(("cleanup", cid))
        self._states.pop(cid, None)

    def cleanup_all(self) -> None:
        self.calls.append(("cleanup_all",))
        self._states.clear()

    def set_volume(self, cid: int, vol: int) -> None:
        self.calls.append(("set_volume", cid, vol))

    def get_state(self, cid: int) -> str:
        return self._states.get(cid, "stopped")

    def get_active_channels(self) -> list[int]:
        return list(self._states.keys())

    def get_duration_ms(self, cid: int) -> int:
        return 60_000

    def seek_to_ms(self, cid: int, ms: int) -> None:
        self.calls.append(("seek_to_ms", cid, ms))

    # ── Helpers ──────────────────────────────────────────────────────────

    def calls_named(self, name: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == name]


class _FakeScheduler:
    """Tracks running state + records start/stop. peek_next returns
    whatever the test seeded; pick_next_item walks that list and
    advances an internal cursor (so _compute_next_song's path that
    calls pick_next_item under is_running() works deterministically)."""

    def __init__(self, items: Optional[list[dict]] = None):
        self._items: list[dict] = list(items or [])
        self._pick_cursor: int = 0
        self.peek_calls: int = 0
        self.start_calls: int = 0
        self.stop_calls: int = 0
        self._running: bool = False
        self.spot_due          = _RecordingSignal()
        self.song_auto_advance = _RecordingSignal()
        self.break_approaching = _RecordingSignal()
        self.next_break_in     = _RecordingSignal()
        self.started           = _RecordingSignal()
        self.stopped           = _RecordingSignal()

    def peek_next(self, n: int = 5, now=None) -> list[dict]:
        self.peek_calls += 1
        return self._items[:n]

    def pick_next_item(self, now=None) -> Optional[dict]:
        if self._pick_cursor >= len(self._items):
            return None
        it = self._items[self._pick_cursor]
        self._pick_cursor += 1
        return it

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self.start_calls += 1
        self._running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self._running = False

    def set_items(self, items: list[dict]) -> None:
        self._items = list(items)
        self._pick_cursor = 0


def _peek_item(item_id: int, title: str, file_path: str,
               duration_ms: int = 60_000) -> dict:
    """peek_next-shaped dict (matches core/scheduler/engine.py output)."""
    return {
        "item_type":   "song",
        "item_id":     item_id,
        "file_path":   file_path,
        "title":       title,
        "artist":      "Artist",
        "duration_ms": duration_ms,
        "clock_id":    1,
        "slot_idx":    item_id - 1,
    }


# ── Fixtures ────────────────────────────────────────────────────────────


def _real_song_file(db: Database) -> Optional[str]:
    """Pick a real on-disk audio path so engine.load_file's existence
    guard inside _on_queue_song_play passes without us having to
    monkey-patch os.path.exists."""
    rows = db._conn().execute(
        "SELECT file_path FROM songs WHERE file_path IS NOT NULL "
        "AND file_path != '' ORDER BY id LIMIT 5"
    ).fetchall()
    import os as _os
    for r in rows:
        if r[0] and _os.path.exists(r[0]):
            return r[0]
    return None


@pytest.fixture
def studio_fake(qtbot):
    """Studio + _FakeAudioEngine + _FakeScheduler with one real
    on-disk song file path seeded into both the engine queue path
    and the scheduler peek list."""
    db = Database()
    fp = _real_song_file(db)
    if fp is None:
        pytest.skip("Need at least one real on-disk song")
    eng = _FakeAudioEngine()
    sch = _FakeScheduler([_peek_item(1, "Track A", fp, 60_000),
                          _peek_item(2, "Track B", fp, 90_000)])
    s = Studio(db=db, engine=eng, scheduler=sch,
               instant_jingle_engine=None)
    qtbot.addWidget(s)
    return s, eng, sch


# ── Tests ───────────────────────────────────────────────────────────────


def test_play_button_idle_loads_first_track_and_starts_engine(studio_fake):
    """Bottom transport ▶ click on idle Studio:
      - calls scheduler.start (because scheduler wasn't running)
      - calls engine.load_file with a real path
      - calls engine.play with the new cid
      - sets _playback_cid + _current_track + _auto_advance_enabled=True
    """
    studio, eng, sch = studio_fake
    assert studio._playback_cid is None
    assert sch.start_calls == 0

    studio._on_play_clicked()

    # Scheduler auto-on
    assert sch.start_calls == 1
    # Engine wires: load + play
    loads = eng.calls_named("load_file")
    plays = eng.calls_named("play")
    assert len(loads) == 1
    assert len(plays) == 1
    assert plays[0][1] == loads[0][2]   # play(cid) for the loaded cid
    # Studio state
    assert studio._playback_cid == loads[0][2]
    assert studio._current_track is not None
    assert studio._auto_advance_enabled is True


def test_play_button_when_already_playing_toggles_pause(studio_fake):
    """If a track is already loaded, ▶ delegates to the existing
    pause toggle instead of restarting playback (Live-Assist
    operator's "pause-during-banter" muscle memory)."""
    studio, eng, sch = studio_fake
    studio._on_play_clicked()              # idle → start
    cid = studio._playback_cid
    eng.calls.clear()                      # focus on the second click

    studio._on_play_clicked()              # already playing → pause

    pauses = eng.calls_named("pause")
    assert len(pauses) == 1
    assert pauses[0][1] == cid
    # No fresh load/play
    assert eng.calls_named("load_file") == []


def test_deck_stop_narrow_scope(studio_fake):
    """■ stops + cleans up the deck channel only. cleanup_all is NOT
    called — that's the whole point of the Phase C narrowing
    (jingle pads stay alive)."""
    studio, eng, _sch = studio_fake
    studio._on_play_clicked()
    cid = studio._playback_cid
    eng.calls.clear()

    studio._on_deck_stop()

    # stop + cleanup on the deck channel
    assert ("stop", cid) in eng.calls
    assert ("cleanup", cid) in eng.calls
    # cleanup_all explicitly NOT called
    assert eng.calls_named("cleanup_all") == []
    # Studio state cleared
    assert studio._playback_cid is None
    assert studio._current_track is None


def test_auto_pill_click_starts_scheduler_when_off(studio_fake):
    """AUTO pill click while scheduler is stopped → start + flip
    _auto_advance_enabled to True."""
    studio, _eng, sch = studio_fake
    sch._running = False
    studio._auto_advance_enabled = False    # match the "AUTO OFF" state

    studio._on_auto_pill_clicked()

    assert sch.start_calls == 1
    assert sch._running is True
    assert studio._auto_advance_enabled is True


def test_auto_pill_click_stops_scheduler_when_on(studio_fake):
    """Reverse direction: scheduler running → click flips both off
    in lockstep (Jazler Live-Assist semantic)."""
    studio, _eng, sch = studio_fake
    sch._running = True
    studio._auto_advance_enabled = True

    studio._on_auto_pill_clicked()

    assert sch.stop_calls == 1
    assert sch._running is False
    assert studio._auto_advance_enabled is False


def test_auto_advance_skipped_when_flag_off(qtbot, studio_fake):
    """Live-Assist mode: track ends, _auto_advance_enabled is False,
    EOS path (d) lands in the "idle until next play click" branch.
    No fresh load_file/play happens — Studio stays idle."""
    studio, eng, _sch = studio_fake
    studio._on_play_clicked()
    first_cid = studio._playback_cid
    studio._auto_advance_enabled = False
    eng.calls.clear()

    studio._on_engine_playback_ended(first_cid)

    # Cleanup of the ended channel is fine; what we DON'T expect is
    # a fresh load_file for the next song.
    assert eng.calls_named("load_file") == []
    assert studio._playback_cid is None
    assert studio._current_track is None


def test_signal_pill_reflects_engine_playing_state(studio_fake):
    """SIGNAL pill source-of-truth = _compute_signal_state. Returns
    True when any channel is in 'playing' state, False otherwise.
    1Hz polling in _on_tick pushes this to header.set_signal()."""
    studio, eng, _sch = studio_fake
    # Idle: no channels
    assert studio._compute_signal_state() is False
    # Start playback → True
    studio._on_play_clicked()
    assert studio._compute_signal_state() is True
    # Pause → still True? No, paused != playing. False per spec.
    eng.pause(studio._playback_cid)
    assert studio._compute_signal_state() is False
    # Resume → True
    eng.resume(studio._playback_cid)
    assert studio._compute_signal_state() is True


def test_studio_without_engine_play_button_noop(qtbot):
    """Decorative fallback — engine=None Studio must not crash on
    a play click. Same contract as Phase A's no-IJE fallback."""
    db = Database()
    s = Studio(db=db, engine=None, scheduler=None,
               instant_jingle_engine=None)
    qtbot.addWidget(s)

    # All four entry points are no-ops (or handle None gracefully)
    s._on_play_clicked()
    s._on_deck_stop()
    s._on_auto_pill_clicked()    # scheduler=None → just flips flag
    assert s._compute_signal_state() is False
