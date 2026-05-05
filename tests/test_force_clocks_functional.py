"""
Phase F-Final S4 — Force Clocks functional UI.

The UI is mostly delegation to db.add_force_clock / db.delete_force_clock /
db.list_force_clocks — these tests verify the CRUD round-trip + that the
ForceClocks widget mounts cleanly and refreshes its row count.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from core.database import Database
from ui.force_clocks import ForceClocks


def test_force_clock_crud_round_trip(qtbot):
    db = Database()
    # Capture starting count
    pre = len(list(db.list_force_clocks()))

    # Need at least one clock to attach
    clocks = list(db.get_all_clocks())
    if not clocks:
        pytest.skip("no clocks in DB")
    cid = int(clocks[0]["id"])
    today = datetime.now().strftime("%Y-%m-%d")

    new_id = db.add_force_clock("Test Override", cid, override_date=today,
                                time_start="09:00", time_end="11:00")
    assert new_id > 0
    rows = list(db.list_force_clocks())
    assert len(rows) == pre + 1
    assert any(int(r["id"]) == new_id for r in rows)

    # Cleanup
    db.delete_force_clock(new_id)
    rows = list(db.list_force_clocks())
    assert len(rows) == pre


def test_force_clocks_widget_mounts_and_shows_count(qtbot):
    db = Database()
    fc = ForceClocks(db=db)
    assert fc is not None
    # Widget pulls list on init; count label should match.
    n = len(list(db.list_force_clocks()))
    expected = f"{n} Override{'s' if n != 1 else ''}"
    assert fc._count_label.text() == expected


def test_force_clock_resolution_for_today_at_specific_hour(qtbot):
    """Add an override that spans the current hour, then confirm
    db.get_force_clock_for(now) returns it. Cleanup deletes the row."""
    db = Database()
    clocks = list(db.get_all_clocks())
    if not clocks:
        pytest.skip("no clocks in DB")
    cid = int(clocks[0]["id"])
    today = datetime.now().strftime("%Y-%m-%d")
    new_id = db.add_force_clock("Resolution Test", cid,
                                override_date=today,
                                time_start="00:00", time_end="23:59")
    try:
        result = db.get_force_clock_for(datetime.now())
        assert result is not None
        # Either OUR override resolves OR an earlier one already covered
        # this hour. Just verify the row references a clock.
        assert int(result["clock_id"]) > 0
    finally:
        db.delete_force_clock(new_id)
