"""
Studio auto-start on showEvent — operator (Kavish) request 2026-05-07.

Operator workflow: when Studio is opened (app boot, or navigate-back
from another screen), it should automatically engage the scheduler if
a clock is assigned to the current (weekday, hour) cell. Saves the
operator a manual AUTO-pill click after every restart.

Pinned behaviour:
  • Auto-starts when scheduler exists, is_running()=False, a clock
    is assigned to (weekday, hour), and the operator has not latched
    auto-start off via the AUTO pill in the same session.
  • Skips when no clock is assigned (idle hour cell).
  • Skips when scheduler is already running (idempotent).
  • Latches off when operator explicitly clicks AUTO to stop —
    subsequent showEvents respect the operator's Live-Assist intent.
  • Latch is cleared by an AUTO-on click (operator re-arms manually).
"""

from __future__ import annotations

import sqlite3

import pytest

from PyQt6.QtGui import QShowEvent

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
    def __init__(self):
        self._running = False
        self.start_calls = 0
        self.stop_calls = 0
        for n in ("spot_due", "song_auto_advance", "break_approaching",
                   "next_break_in", "schedule_reloaded", "error_occurred",
                   "started", "stopped", "active_clock_changed"):
            setattr(self, n, _RecordingSignal())

    def is_running(self):  return self._running

    def start(self):
        self._running = True
        self.start_calls += 1

    def stop(self):
        self._running = False
        self.stop_calls += 1

    def pick_next_item(self, _now=None):
        return None

    def peek_next(self, n=5, now=None):
        return []


@pytest.fixture
def db():
    return Database()


def _make_studio(db, scheduler=None) -> Studio:
    return Studio(db, parent=None, engine=None,
                  scheduler=scheduler,
                  instant_jingle_engine=None,
                  sweeper_engine=None)


def _stub_active_clock(monkeypatch, db, row_or_none):
    """Make db.get_active_clock return a fixed row regardless of the
    weekday/hour args. Avoids the hour rollover making tests flaky."""
    def _fake(_dow, _hr):
        return row_or_none
    monkeypatch.setattr(db, "get_active_clock", _fake)


def _row(clock_id: int, name: str = "Test Clock") -> sqlite3.Row:
    """Build a dict-with-keys() shim that mimics sqlite3.Row enough for
    the auto-start helper's _row["id"] / _row["name"] access."""
    class _R:
        def __init__(self, d):
            self._d = d
        def __getitem__(self, k):
            return self._d[k]
        def keys(self):
            return self._d.keys()
    return _R({"id": int(clock_id), "name": name})


def _show(studio):
    studio.showEvent(QShowEvent())


# ── Auto-start happy path ──────────────────────────────────────────────────

def test_auto_starts_when_clock_assigned_and_idle(qapp, db, monkeypatch):
    sched = _FakeScheduler()
    studio = _make_studio(db, scheduler=sched)
    _stub_active_clock(monkeypatch, db, _row(7, "New Clock 021"))

    # Reset the count: ctor's seed path may have run earlier.
    sched.start_calls = 0
    _show(studio)

    assert sched.is_running() is True
    assert sched.start_calls == 1
    assert studio._auto_advance_enabled is True
    studio.deleteLater()


def test_no_auto_start_when_no_clock_assigned(qapp, db, monkeypatch):
    sched = _FakeScheduler()
    studio = _make_studio(db, scheduler=sched)
    _stub_active_clock(monkeypatch, db, None)
    sched.start_calls = 0

    _show(studio)

    assert sched.is_running() is False
    assert sched.start_calls == 0
    studio.deleteLater()


def test_no_auto_start_when_already_running(qapp, db, monkeypatch):
    sched = _FakeScheduler()
    sched._running = True   # already on (e.g. previous session)
    studio = _make_studio(db, scheduler=sched)
    _stub_active_clock(monkeypatch, db, _row(7))
    sched.start_calls = 0

    _show(studio)

    assert sched.start_calls == 0  # idempotent
    studio.deleteLater()


# ── Operator latch behavior ────────────────────────────────────────────────

def test_latch_blocks_subsequent_auto_starts_after_operator_stops(
        qapp, db, monkeypatch):
    """Operator clicks AUTO to stop → flag latches → next showEvent
    respects the operator's intent and does NOT re-arm."""
    sched = _FakeScheduler()
    studio = _make_studio(db, scheduler=sched)
    _stub_active_clock(monkeypatch, db, _row(7))
    sched.start_calls = 0

    # First show → auto-starts
    _show(studio)
    assert sched.start_calls == 1

    # Operator clicks AUTO to stop
    studio._on_auto_pill_clicked()
    assert sched.is_running() is False
    assert studio._operator_stopped_auto is True

    # Second show → must NOT re-arm
    _show(studio)
    assert sched.is_running() is False
    assert sched.start_calls == 1   # still 1, not 2
    studio.deleteLater()


def test_latch_clears_on_operator_auto_on_click(qapp, db, monkeypatch):
    """Operator re-engages AUTO manually → latch clears so future
    showEvent auto-starts can engage."""
    sched = _FakeScheduler()
    studio = _make_studio(db, scheduler=sched)
    _stub_active_clock(monkeypatch, db, _row(7))

    studio._operator_stopped_auto = True   # simulate prior stop

    # Operator clicks AUTO on
    studio._on_auto_pill_clicked()
    assert sched.is_running() is True
    assert studio._operator_stopped_auto is False
    studio.deleteLater()


# ── No-scheduler / no-DB safety ────────────────────────────────────────────

def test_auto_start_no_op_without_scheduler(qapp, db):
    studio = _make_studio(db, scheduler=None)
    # Just verify it doesn't crash on showEvent
    _show(studio)
    studio.deleteLater()


def test_auto_start_handles_get_active_clock_exception(qapp, db, monkeypatch):
    sched = _FakeScheduler()
    studio = _make_studio(db, scheduler=sched)
    def _boom(_dow, _hr): raise RuntimeError("DB blip")
    monkeypatch.setattr(db, "get_active_clock", _boom)
    sched.start_calls = 0

    _show(studio)   # must NOT raise
    assert sched.start_calls == 0
    studio.deleteLater()
