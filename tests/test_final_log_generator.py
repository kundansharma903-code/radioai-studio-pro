"""
Phase F-Final S5 — Final Log generator.

Verifies the 24-hour pre-compute path: clock resolution (force_clocks
override → auto_schedule), per-slot picker dispatch, persistence in
final_log_entries.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine


def _build_clock_with_song(db: Database, name: str = "FL Test") -> int:
    cid = db.create_clock(name)
    db.save_clock_slots(cid, [
        {"slot_type": "Song", "selection_mode": "random_any",
         "category_id": None, "energy_pref": "Any", "vocal_pref": "Any",
         "priority_pref": "Normal", "is_break": 0, "item_id": 0},
    ])
    return cid


def test_generate_final_log_no_assignments_yields_empty_log(qtbot):
    """If auto_schedule is empty AND no force_clocks for the date, every
    hour falls in the 'empty' bucket and zero entries land."""
    db = Database()
    sch = SchedulerEngine(db=db)
    # Pick a date well in the past so it's unlikely to have assignments.
    target = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
    result = db.generate_final_log(target, sch)
    assert result["entry_count"] == 0
    assert result["hours_resolved"] == 0
    assert result["hours_empty"] == 24
    db.delete_final_log(target)


def test_generate_final_log_creates_entries_for_assigned_hours(qtbot):
    """Assign a Song clock to one hour of the target date's day-of-week,
    generate, expect at least one entry attributed to that hour."""
    db = Database()
    db.seed_rotation_test_data()
    if not list(db.get_songs(limit=1)):
        pytest.skip("no songs in DB")
    sch = SchedulerEngine(db=db)

    # Use a date whose weekday corresponds to (Mon, hour=12)
    today = datetime.now()
    days_to_mon = (-today.weekday()) % 7 or 7    # next Monday
    target = (today + timedelta(days=days_to_mon)).strftime("%Y-%m-%d")
    cid = _build_clock_with_song(db)
    db.set_auto_schedule_cell(0, 12, cid)
    try:
        result = db.generate_final_log(target, sch)
        assert result["entry_count"] >= 1
        assert result["hours_resolved"] >= 1
        # Entries readback
        log_row = db.get_final_log(target)
        assert log_row is not None
        entries = list(db.get_final_log_entries(int(log_row["id"])))
        # All entries fall on hour 12 (since only one cell is assigned)
        for e in entries:
            assert e["scheduled_time"].startswith("12:")
    finally:
        db.delete_final_log(target)
        db.clear_auto_schedule_cell(0, 12)
        db._conn().execute("DELETE FROM broadcast_log WHERE clock_id = ?", [cid])
        db._conn().commit()
        try:
            db.delete_clock(cid)
        except (ValueError, Exception):
            pass


def test_generate_final_log_replaces_existing(qtbot):
    """Calling generator twice for the same date doesn't double — the
    older log row is dropped first (idempotent)."""
    db = Database()
    sch = SchedulerEngine(db=db)
    target = "2099-01-01"
    db.generate_final_log(target, sch)
    first = db.get_final_log(target)
    assert first is not None
    db.generate_final_log(target, sch)
    second = db.get_final_log(target)
    assert second is not None
    assert int(second["id"]) != int(first["id"])
    db.delete_final_log(target)


def test_delete_final_log_cascades_entries(qtbot):
    """Delete drops the row + every entry under it."""
    db = Database()
    db.seed_rotation_test_data()
    sch = SchedulerEngine(db=db)
    target = "2099-02-02"
    db.generate_final_log(target, sch)
    db.delete_final_log(target)
    assert db.get_final_log(target) is None
    # And no orphan entries remain (count via a generic select).
    n = db._conn().execute(
        "SELECT COUNT(*) FROM final_log_entries WHERE log_id NOT IN "
        "(SELECT id FROM final_logs)").fetchone()[0]
    assert int(n) == 0
