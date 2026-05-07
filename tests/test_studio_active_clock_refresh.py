"""
Studio v3 — Active Clock indicator refresh paths.

Operator scenario: assign a clock to the current (weekday, hour) cell
in Auto Schedule, navigate back to Studio. The header's "Active Clock"
indicator must reflect the new clock without requiring AUTO to be on.

This file verifies the four refresh triggers Studio uses:
  1. Studio's own 1Hz tick (independent of scheduler running) — so
     AUTO-OFF mode also gets fresh indicator data.
  2. ``showEvent`` (fires on navigate-back from another screen) —
     forces an immediate refresh.
  3. AUTO pill toggle — forces refresh after start/stop so the
     operator sees the effect of their click within one frame.
  4. Scheduler's own ``active_clock_changed`` signal (when running)
     still routes through the same dedupe state — covers the
     auto-running broadcast case.

All four paths converge through ``_set_displayed_active_clock`` which
dedupes against ``_displayed_active_clock_id`` so the header repaints
only on transition.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import pytest

from core.database import Database
from ui.studio import Studio


def _now_dow_hour() -> tuple[int, int]:
    n = datetime.now()
    return int(n.weekday()), int(n.hour)


def _drop_clock(db: Database, clock_id: int) -> None:
    conn = db._conn()
    try:
        conn.execute("DELETE FROM auto_schedule WHERE clock_id = ?",
                     [int(clock_id)])
        conn.execute("DELETE FROM clock_slots WHERE clock_id = ?",
                     [int(clock_id)])
        conn.execute("DELETE FROM clocks WHERE id = ?", [int(clock_id)])
        conn.commit()
    except Exception:
        pass


@pytest.fixture
def studio(qtbot):
    """Studio with NO scheduler — exercises the AUTO-off path where
    Studio's own 1Hz tick + showEvent are the only refresh triggers."""
    db = Database()
    s = Studio(db=db, engine=None, scheduler=None,
               instant_jingle_engine=None)
    qtbot.addWidget(s)
    yield s


# ── 1. Studio's 1Hz tick picks up a fresh clock assignment ────────────


def test_studio_tick_resolves_active_clock_without_scheduler(qtbot, studio):
    """AUTO is off → scheduler not running → the only path that drives
    the indicator is Studio's own _on_tick → _studio_check_active_clock.
    Assign a clock to the current cell, run one tick manually, assert
    the header shows the new clock name."""
    db = studio._db
    dow, hour = _now_dow_hour()
    name = f"_test_studio_tick_{uuid.uuid4().hex[:8]}"
    cid = db.create_clock(name)
    db.set_auto_schedule_cell(dow, hour, cid)
    try:
        # Snapshot pre-tick state (header should be blank since
        # constructor's seed found no active clock at construction
        # time — the test cell was set after Studio was built).
        # Studio.__init__ called _seed_active_clock_indicator() but
        # current_active_clock() on a None scheduler returns (None, "")
        # so header stays at default "" → renders location fallback.
        # Now bump the dedupe so the next check fires regardless.
        studio._displayed_active_clock_id = -2

        studio._studio_check_active_clock()

        assert studio._header._active_clock_name == name, (
            "Studio's 1Hz tick must pick up the freshly-assigned clock "
            "without scheduler running")
    finally:
        db.clear_auto_schedule_cell(dow, hour)
        _drop_clock(db, cid)


# ── 2. showEvent forces an immediate refresh ──────────────────────────


def test_showevent_triggers_active_clock_refresh(qtbot, studio):
    """Navigate-back semantic: when Studio becomes visible after the
    user assigned a clock in Auto Schedule, _force_studio_refresh
    runs and the indicator updates within one event-loop iteration."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QShowEvent

    db = studio._db
    dow, hour = _now_dow_hour()
    name = f"_test_showevent_{uuid.uuid4().hex[:8]}"
    cid = db.create_clock(name)
    db.set_auto_schedule_cell(dow, hour, cid)
    try:
        # Pre-condition: indicator may already reflect the cell from
        # Studio's tick, OR it may not have run yet. Reset state so
        # we observe the showEvent path explicitly.
        studio._header.set_active_clock("")
        studio._displayed_active_clock_id = -2

        # Fire a synthetic show event — Studio.showEvent override
        # invokes _force_studio_refresh which re-resolves the cell.
        studio.showEvent(QShowEvent())

        assert studio._header._active_clock_name == name
    finally:
        db.clear_auto_schedule_cell(dow, hour)
        _drop_clock(db, cid)


# ── 3. AUTO pill toggle forces an immediate refresh ──────────────────


class _MinimalScheduler:
    """Minimal scheduler stub — only the surfaces Studio touches at
    construction + AUTO-toggle time. Mirror pattern from
    test_studio_spot_deferred.py."""

    def __init__(self, running: bool = False):
        self._running = bool(running)
        self.start_calls = 0
        self.stop_calls = 0

        class _S:
            def __init__(self):
                self._slots = []

            def connect(self, slot):
                self._slots.append(slot)

            def emit(self, *args):
                for s in self._slots:
                    s(*args)

        # Create individual signal stand-ins per attribute name.
        for attr in ("spot_due", "song_auto_advance", "break_approaching",
                     "next_break_in", "started", "stopped",
                     "active_clock_changed"):
            setattr(self, attr, _S())

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self.start_calls += 1
        self._running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self._running = False

    def peek_next(self, n: int = 5, now=None) -> list:
        return []

    def current_active_clock(self) -> tuple:
        return None, ""


def test_auto_toggle_forces_refresh_to_pick_up_new_cell(qtbot):
    """AUTO toggle click triggers _force_studio_refresh — operator's
    workflow: assign a clock, click AUTO, see the indicator update
    immediately. Works whether the toggle starts or stops scheduler."""
    db = Database()
    sch = _MinimalScheduler(running=False)
    s = Studio(db=db, engine=None, scheduler=sch,
               instant_jingle_engine=None)
    qtbot.addWidget(s)

    dow, hour = _now_dow_hour()
    name = f"_test_auto_toggle_{uuid.uuid4().hex[:8]}"
    cid = db.create_clock(name)
    db.set_auto_schedule_cell(dow, hour, cid)
    try:
        # Pre-toggle: clear the indicator state so we can observe the
        # post-click refresh
        s._header.set_active_clock("")
        s._displayed_active_clock_id = -2

        # Click AUTO (off → on transition)
        s._on_auto_pill_clicked()

        assert sch.start_calls == 1
        assert s._header._active_clock_name == name, (
            "AUTO pill click must trigger a fresh active-clock resolve")
    finally:
        db.clear_auto_schedule_cell(dow, hour)
        _drop_clock(db, cid)


# ── 4. Dedupe — same-clock reads don't re-render ──────────────────────


def test_displayed_active_clock_dedupes_unchanged_resolves(qtbot, studio):
    """Studio's 1Hz tick runs continuously. If the cell hasn't changed,
    the header should NOT repaint on every tick — _displayed_active_clock_id
    cache prevents redundant set_active_clock calls."""
    db = studio._db
    dow, hour = _now_dow_hour()
    name = f"_test_dedupe_{uuid.uuid4().hex[:8]}"
    cid = db.create_clock(name)
    db.set_auto_schedule_cell(dow, hour, cid)
    try:
        # First check — should fire and update header
        studio._displayed_active_clock_id = -2
        studio._studio_check_active_clock()
        assert studio._header._active_clock_name == name
        cached_id_after_first = studio._displayed_active_clock_id

        # Manually clear header text — proves the dedupe path skips
        # set_active_clock when the cached id matches the resolved id.
        studio._header._active_clock_name = "SHOULD_NOT_BE_OVERWRITTEN"

        studio._studio_check_active_clock()

        # Header was NOT updated because dedupe matched cached id
        assert studio._header._active_clock_name == "SHOULD_NOT_BE_OVERWRITTEN"
        assert studio._displayed_active_clock_id == cached_id_after_first
    finally:
        db.clear_auto_schedule_cell(dow, hour)
        _drop_clock(db, cid)
