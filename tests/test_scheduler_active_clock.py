"""
SchedulerEngine active-clock tracking tests.

The scheduler now tracks which clock is assigned to the current
(weekday, hour) cell and emits ``active_clock_changed(int, str)`` when
that resolution transitions across ticks. Studio's header subscribes
to this so the operator sees a live "Active Clock: <name>" indicator.

Coverage:
  1. Signal fires on the first tick when a clock is assigned.
  2. Signal does NOT re-fire when the resolved clock is unchanged.
  3. Signal fires when the resolved clock changes (hour-boundary
     proxy — we move the cell assignment in the DB to simulate the
     same effect a real wall-clock hour rollover would produce).
  4. Signal emits sentinel ``(-1, "")`` when no clock is assigned to
     the current cell.
  5. Day rollover: switching to a different (dow, hour) cell with a
     different clock fires the signal with the new clock's data.
  6. ``current_active_clock()`` returns ``(None, "")`` pre-tick.
  7. Studio header bind: emitting the signal updates the header's
     active-clock state directly.

Mirror tests/test_scheduler_peek_next.py + test_studio_*_wiring.py
patterns — live Database fixture, prefixed test rows, try/finally
cleanup. Manipulates the auto_schedule cell to control which clock
the scheduler resolves for "now"; we only need the resolution path
itself, not real wall-clock advance.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine


# ── Helpers ─────────────────────────────────────────────────────────────


def _now_dow_hour() -> tuple[int, int]:
    """Current (weekday 0=Mon..6=Sun, hour). Used as the "now" cell
    we manipulate so the scheduler resolves a clock we control."""
    n = datetime.now()
    return int(n.weekday()), int(n.hour)


def _make_named_clock(db: Database, name: str) -> int:
    """Create a clock with a uniquely-prefixed test name and return its
    id. Caller is responsible for cleanup."""
    return int(db.create_clock(name))


def _drop_clock(db: Database, clock_id: int) -> None:
    """Best-effort cleanup of a test clock + its slot rows + any
    auto_schedule cells pointing at it."""
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


# ── Recording signal stand-in for cross-thread emit capture ─────────────


def _capture_signal(sig) -> list[tuple]:
    """Connect a list-appending callback to a pyqtSignal and return
    that list — every emit lands as a tuple. Synchronous because
    ``_check_active_clock_change`` runs on the calling thread when we
    invoke it directly (we never start the QThread in these tests)."""
    captured: list[tuple] = []
    sig.connect(lambda *args: captured.append(tuple(args)))
    return captured


# ── 1. Signal fires on first tick when a clock is assigned ──────────────


def test_active_clock_signal_fires_on_first_tick_when_clock_assigned(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    dow, hour = _now_dow_hour()
    name = f"_test_active_clock_{uuid.uuid4().hex[:8]}"
    cid = _make_named_clock(db, name)
    db.set_auto_schedule_cell(dow, hour, cid)
    captured = _capture_signal(sch.active_clock_changed)
    try:
        sch._check_active_clock_change()
        assert len(captured) == 1
        emitted_id, emitted_name = captured[0]
        assert emitted_id == cid
        assert emitted_name == name
    finally:
        db.clear_auto_schedule_cell(dow, hour)
        _drop_clock(db, cid)


# ── 2. Signal does NOT fire when unchanged ──────────────────────────────


def test_active_clock_signal_does_not_refire_when_unchanged(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    dow, hour = _now_dow_hour()
    name = f"_test_dedupe_{uuid.uuid4().hex[:8]}"
    cid = _make_named_clock(db, name)
    db.set_auto_schedule_cell(dow, hour, cid)
    captured = _capture_signal(sch.active_clock_changed)
    try:
        sch._check_active_clock_change()
        sch._check_active_clock_change()
        sch._check_active_clock_change()
        # Three calls but the cell didn't change — only the first
        # transition (None → cid) emits.
        assert len(captured) == 1
    finally:
        db.clear_auto_schedule_cell(dow, hour)
        _drop_clock(db, cid)


# ── 3. Signal fires when resolved clock changes ─────────────────────────


def test_active_clock_signal_fires_on_resolution_change(qtbot):
    """Hour-boundary proxy: at minute 00 of a new hour the resolved
    clock often changes (because the operator assigned a different
    clock to that cell). We simulate the same transition by swapping
    which clock the cell points at — the resolution path is identical."""
    db = Database()
    sch = SchedulerEngine(db=db)
    dow, hour = _now_dow_hour()
    name_a = f"_test_clock_a_{uuid.uuid4().hex[:8]}"
    name_b = f"_test_clock_b_{uuid.uuid4().hex[:8]}"
    cid_a = _make_named_clock(db, name_a)
    cid_b = _make_named_clock(db, name_b)
    captured = _capture_signal(sch.active_clock_changed)
    try:
        db.set_auto_schedule_cell(dow, hour, cid_a)
        sch._check_active_clock_change()
        # Now reassign the cell to clock B and re-tick
        db.set_auto_schedule_cell(dow, hour, cid_b)
        sch._check_active_clock_change()
        assert len(captured) == 2
        assert captured[0] == (cid_a, name_a)
        assert captured[1] == (cid_b, name_b)
    finally:
        db.clear_auto_schedule_cell(dow, hour)
        _drop_clock(db, cid_a)
        _drop_clock(db, cid_b)


# ── 4. Sentinel (-1, "") when no clock assigned ─────────────────────────


def test_active_clock_emits_sentinel_when_no_clock_assigned(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    dow, hour = _now_dow_hour()
    # Belt + suspenders: ensure the cell is empty
    db.clear_auto_schedule_cell(dow, hour)
    captured = _capture_signal(sch.active_clock_changed)
    sch._check_active_clock_change()
    assert len(captured) == 1
    emitted_id, emitted_name = captured[0]
    assert emitted_id == -1
    assert emitted_name == ""


# ── 5. Day rollover: different (dow, hour) cell picks different clock ───


def test_day_rollover_picks_correct_dow_cell(qtbot):
    """Simulate a Sunday→Monday rollover: assign DIFFERENT clocks to
    Sunday-23 and Monday-00, then have the scheduler resolve each via
    a passed-in ``now`` (we feed the cell directly through
    get_active_clock — the production path uses datetime.now() but
    the resolution logic is the same).

    The real production flow uses datetime.now().weekday() at tick
    time; this test verifies the underlying lookup works for arbitrary
    (dow, hour) pairs, which is what hour-boundary detection relies on."""
    db = Database()
    name_sun = f"_test_sun23_{uuid.uuid4().hex[:8]}"
    name_mon = f"_test_mon00_{uuid.uuid4().hex[:8]}"
    cid_sun = _make_named_clock(db, name_sun)
    cid_mon = _make_named_clock(db, name_mon)
    try:
        db.set_auto_schedule_cell(6, 23, cid_sun)   # Sunday 23:00
        db.set_auto_schedule_cell(0,  0, cid_mon)   # Monday  00:00

        sun_row = db.get_active_clock(6, 23)
        mon_row = db.get_active_clock(0, 0)

        assert sun_row is not None
        assert mon_row is not None
        assert int(sun_row["id"]) == cid_sun
        assert int(mon_row["id"]) == cid_mon
        assert int(sun_row["id"]) != int(mon_row["id"])
    finally:
        db.clear_auto_schedule_cell(6, 23)
        db.clear_auto_schedule_cell(0,  0)
        _drop_clock(db, cid_sun)
        _drop_clock(db, cid_mon)


# ── 6. current_active_clock() pre-tick ──────────────────────────────────


def test_current_active_clock_pre_tick(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    cid, name = sch.current_active_clock()
    assert cid is None
    assert name == ""


# ── 7. Studio header bind reflects the signal ──────────────────────────


def test_studio_header_active_clock_set_via_signal_path(qtbot):
    """Studio's _on_active_clock_changed pushes the name to the header.
    We don't need a real scheduler thread — invoking the handler
    directly with the signal payload is the contract test."""
    from ui.studio import Studio

    db = Database()
    s = Studio(db=db, engine=None, scheduler=None,
               instant_jingle_engine=None)
    qtbot.addWidget(s)

    s._on_active_clock_changed(42, "Morning Drive")
    assert s._header._active_clock_name == "Morning Drive"

    # Sentinel path — clock_id == -1 clears the indicator so the card
    # falls back to its location text.
    s._on_active_clock_changed(-1, "")
    assert s._header._active_clock_name == ""
