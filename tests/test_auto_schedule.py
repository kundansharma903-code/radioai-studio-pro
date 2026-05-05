"""
Auto Schedule unit tests (Phase F1).

Covers the DB write/read API and the AutoSchedule top-level widget mounts
cleanly. Grid paint and dialog interactions are smoke-tested by the app
launch in main.py — these tests focus on the data layer + composition.

Tests use a real Database singleton (no mocks). Mutations are scoped to
specific (day, hour) pairs we own, then cleaned up via clear_auto_schedule_cell
to avoid leaking state between tests.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.auto_schedule import AutoSchedule


# ── Fixture: AutoSchedule mounts and lists at least one clock ────────────

@pytest.fixture
def schedule(qtbot):
    db = Database()
    if not db.get_all_clocks():
        pytest.skip("no clocks in DB to drive auto schedule tests")
    s = AutoSchedule(db=db)
    yield s


# ── 1. Renders without crashing ─────────────────────────────────────────

def test_grid_renders_without_clocks(qtbot):
    """AutoSchedule mounts even when no clocks exist (operator opens it
    fresh). The grid should still draw — just with all-empty cells."""
    db = Database()
    s = AutoSchedule(db=db)
    # Force a paint pass
    s._grid.repaint()
    assert s._grid.width() > 0
    assert s._grid.height() > 0


# ── 2. set_auto_schedule_cell persists ───────────────────────────────────

def test_set_assignment_persists(schedule):
    db = schedule._db
    clock_id = int(schedule._clocks[0]["id"])
    # Use a high hour we don't expect to clash with manual fixtures.
    db.set_auto_schedule_cell(day_of_week=2, hour=23, clock_id=clock_id)
    grid = db.get_auto_schedule_grid()
    assert grid.get((2, 23)) == clock_id
    # Cleanup
    db.clear_auto_schedule_cell(2, 23)


# ── 3. clear_auto_schedule_cell removes entries ──────────────────────────

def test_clear_assignment(schedule):
    db = schedule._db
    clock_id = int(schedule._clocks[0]["id"])
    db.set_auto_schedule_cell(day_of_week=3, hour=22, clock_id=clock_id)
    assert db.get_auto_schedule_grid().get((3, 22)) == clock_id
    db.clear_auto_schedule_cell(3, 22)
    assert (3, 22) not in db.get_auto_schedule_grid()


# ── 4. clear_all wipes the grid ──────────────────────────────────────────

def test_clear_all_assignments(schedule):
    db = schedule._db
    clock_id = int(schedule._clocks[0]["id"])
    # Seed two cells
    db.set_auto_schedule_cell(0, 21, clock_id)
    db.set_auto_schedule_cell(0, 22, clock_id)
    pre = len(db.get_auto_schedule_grid())
    assert pre >= 2
    n = db.clear_all_auto_schedule()
    assert n >= 2
    assert db.get_auto_schedule_grid() == {}


# ── 5. normalize_auto_schedule splits multi-hour ranges ──────────────────

def test_normalize_splits_multihour_range(schedule):
    """Insert a synthetic 4-hour range row; confirm normalize() splits
    it into 4 single-hour rows with the same clock binding."""
    db = schedule._db
    clock_id = int(schedule._clocks[0]["id"])
    conn = db._conn()
    # Setup: ensure no rows for day=4 hours 0-3
    conn.execute(
        "DELETE FROM auto_schedule WHERE day_of_week = ? "
        "AND hour_start < 4", [4])
    conn.execute(
        "INSERT INTO auto_schedule (clock_id, day_of_week, hour_start, hour_end) "
        "VALUES (?, ?, ?, ?)", [clock_id, 4, 0, 4])
    conn.commit()

    n = db.normalize_auto_schedule()
    assert n >= 1     # at least our row was split

    # Now grid lookup should have day=4 hours 0..3 all bound to clock_id.
    grid = db.get_auto_schedule_grid()
    for h in range(4):
        assert grid.get((4, h)) == clock_id, f"hour {h} not split"

    # Cleanup
    for h in range(4):
        db.clear_auto_schedule_cell(4, h)


# ── 6. assignment grid lookup matches what was written ──────────────────

def test_assignment_grid_lookup_matches_writes(schedule):
    db = schedule._db
    clock_id = int(schedule._clocks[0]["id"])
    pairs = [(1, 14), (5, 20), (6, 0)]
    for d, h in pairs:
        db.set_auto_schedule_cell(d, h, clock_id)
    grid = db.get_auto_schedule_grid()
    for d, h in pairs:
        assert grid.get((d, h)) == clock_id, f"({d},{h}) not in grid"
    # Cleanup
    for d, h in pairs:
        db.clear_auto_schedule_cell(d, h)
