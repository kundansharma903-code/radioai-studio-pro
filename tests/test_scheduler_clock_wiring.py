"""
Scheduler ↔ Clock wiring (Phase F2 / P2).

Covers SchedulerEngine.pick_next_song and the broadcast_log clock_id /
slot_idx columns. Studio's _compute_next_song integration is smoke-tested
via the app launch — these unit tests focus on the data layer.

Each test that mutates auto_schedule cleans up after itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine


# ── Helpers ─────────────────────────────────────────────────────────────


def _ensure_test_clock_with_song(db: Database) -> int:
    """Create or reuse a clock with at least one Song slot at index 0.
    Returns the clock id."""
    # Pick the first existing clock — F2.3 ensures at least 'New Clock' exists
    clocks = list(db.get_all_clocks())
    if not clocks:
        cid = db.create_clock("Wiring Test Clock")
    else:
        cid = int(clocks[0]["id"])
    # Ensure slot 0 is a Song slot.
    slots = [dict(r) for r in db.get_clock_slots(cid)]
    if not slots or (slots[0].get("slot_type") or "").lower() != "song":
        slots = [{
            "slot_type": "Song",
            "category_id": None,
            "energy_pref": "Any",
            "vocal_pref": "Any",
            "priority_pref": "Normal",
            "separation_override": None,
            "is_break": 0,
            "sweeper_position": None,
            "item_id": 0,
            "fallback_category_id": None,
            "pin_to_time": 0,
            "duration_seconds": None,
            "ref_text": None,
        }] + (slots or [])
        db.save_clock_slots(cid, slots)
    return cid


def _now_at(weekday: int, hour: int) -> datetime:
    """Return a datetime with weekday() == weekday and hour == hour.
    Used to make pick_next_song select a deterministic (day, hour) cell."""
    # Find a date in current week with the wanted weekday.
    base = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
    delta = (weekday - base.weekday()) % 7
    return base.replace(day=base.day) + (
        __import__("datetime").timedelta(days=delta))


# ── 1. No assignment → returns None ─────────────────────────────────────

def test_pick_next_song_returns_none_with_no_assignment(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    # Pick a (day, hour) cell we know is empty
    db.clear_auto_schedule_cell(6, 4)
    assert sch.pick_next_song(_now_at(6, 4)) is None


# ── 2. Picks a Song slot when assignment + slots are present ───────────

def test_pick_next_song_picks_from_assigned_clock(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    cid = _ensure_test_clock_with_song(db)
    db.set_auto_schedule_cell(0, 5, cid)
    try:
        result = sch.pick_next_song(_now_at(0, 5))
        if result is None:
            pytest.skip("no songs in DB to feed the picker")
        assert result["clock_id"] == cid
        assert isinstance(result["slot_idx"], int)
        assert "song" in result and result["song"].get("id")
    finally:
        db.clear_auto_schedule_cell(0, 5)


# ── 3. Successive picks rotate through slots ────────────────────────────

def test_slot_cursor_advances_across_calls(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    cid = _ensure_test_clock_with_song(db)
    # Need ≥ 2 Song slots for rotation. Add a second one if missing.
    slots = [dict(r) for r in db.get_clock_slots(cid)]
    n_song = sum(1 for s in slots
                 if (s.get("slot_type") or "").lower() == "song")
    if n_song < 2:
        slots.append({
            "slot_type": "Song",
            "category_id": None,
            "energy_pref": "Any", "vocal_pref": "Any",
            "priority_pref": "Normal",
            "is_break": 0, "item_id": 0,
        })
        db.save_clock_slots(cid, slots)

    db.set_auto_schedule_cell(1, 6, cid)
    try:
        a = sch.pick_next_song(_now_at(1, 6))
        b = sch.pick_next_song(_now_at(1, 6))
        if a is None or b is None:
            pytest.skip("no songs in DB to test rotation")
        # Cursor must have advanced — slot indices differ (or wrapped).
        assert a["slot_idx"] != b["slot_idx"] or len(slots) == 1
    finally:
        db.clear_auto_schedule_cell(1, 6)


# ── 4. Hour rollover resets cursor to 0 ─────────────────────────────────

def test_hour_rollover_resets_cursor(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    cid = _ensure_test_clock_with_song(db)
    db.set_auto_schedule_cell(2, 7, cid)
    db.set_auto_schedule_cell(2, 8, cid)
    try:
        first_at_7 = sch.pick_next_song(_now_at(2, 7))
        if first_at_7 is None:
            pytest.skip("no songs in DB")
        # Advance a few times in hour 7
        sch.pick_next_song(_now_at(2, 7))
        sch.pick_next_song(_now_at(2, 7))
        # Move to hour 8 — cursor should reset to 0
        first_at_8 = sch.pick_next_song(_now_at(2, 8))
        if first_at_8 is None:
            pytest.skip("no songs in DB")
        # Both first picks should target slot 0 of their respective hour.
        assert first_at_7["slot_idx"] == 0
        assert first_at_8["slot_idx"] == 0
    finally:
        db.clear_auto_schedule_cell(2, 7)
        db.clear_auto_schedule_cell(2, 8)


# ── 5. Non-Song slots are skipped at this layer ─────────────────────────

def test_pick_next_song_skips_non_song_slots(qtbot):
    """Build a clock whose slot 0 is a Break — pick_next_song should
    skip it and find slot 1's Song."""
    db = Database()
    sch = SchedulerEngine(db=db)
    cid = _ensure_test_clock_with_song(db)

    slots = [
        {"slot_type": "Break", "is_break": 1, "duration_seconds": 60,
         "category_id": None, "energy_pref": "Any", "vocal_pref": "Any",
         "priority_pref": "Normal", "item_id": 0},
        {"slot_type": "Song",  "is_break": 0,
         "category_id": None, "energy_pref": "Any", "vocal_pref": "Any",
         "priority_pref": "Normal", "item_id": 0},
    ]
    db.save_clock_slots(cid, slots)
    db.set_auto_schedule_cell(3, 9, cid)
    try:
        result = sch.pick_next_song(_now_at(3, 9))
        if result is None:
            pytest.skip("no songs in DB")
        # Should have skipped the Break (slot 0) and picked the Song (slot 1).
        assert result["slot_idx"] == 1
    finally:
        db.clear_auto_schedule_cell(3, 9)


# ── 6. broadcast_log gains clock_id + slot_idx columns ─────────────────

def test_broadcast_log_columns_migrate(qtbot):
    """First log_play call ensures clock_id + slot_idx exist on
    broadcast_log. Idempotent."""
    db = Database()
    db._ensure_broadcast_log_columns()
    db._ensure_broadcast_log_columns()
    cols = {r[1] for r in db._conn().execute(
        "PRAGMA table_info(broadcast_log)").fetchall()}
    assert "clock_id" in cols
    assert "slot_idx" in cols


# ── 7. log_play records the clock attribution end-to-end ───────────────

def test_log_play_with_clock_attribution_persists(qtbot):
    db = Database()
    cid = _ensure_test_clock_with_song(db)
    # Write a synthetic broadcast_log entry attributed to this clock.
    db.log_play(
        entry_type="song",
        song_id=None,
        duration_ms=180000,
        deck="A",
        was_manual=0,
        clock_id=cid,
        slot_idx=2,
    )
    # Pull most recent row and check the attribution columns landed.
    row = db._conn().execute(
        "SELECT clock_id, slot_idx FROM broadcast_log "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert int(row["clock_id"]) == cid
    assert int(row["slot_idx"]) == 2
