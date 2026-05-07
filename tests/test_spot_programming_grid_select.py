"""
Spot Programming — _BreakScheduleGrid multi-select interaction model.

Operator scenario (2026-05-07, requested by Kavish):
  In Spot Programming, plain clicks on timing cells should accumulate
  (toggle add/remove) so multiple times can be selected then "+ Add"
  applies them in one shot. Previously each plain click cleared prior
  selection, forcing one-cell-at-a-time + Add cycles.

Pinned semantics:
  • Plain click toggles a cell on (and a second click toggles it off).
  • Multiple plain clicks accumulate (no implicit clear).
  • Drag rectangle is additive — existing selection survives.
  • Esc clears the entire selection.
  • selection_changed signal fires on every release + on Esc clear.
"""

from __future__ import annotations

import pytest

from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent, QKeyEvent

from ui.dialogs.spot_programming_dialog import (
    _BreakScheduleGrid, TIME_COL_W, HEADER_H, CELL_H, GRID_H,
)


# ── Event synthesis helpers ─────────────────────────────────────────────────

def _cell_center(grid: _BreakScheduleGrid, day: int, slot: int) -> QPointF:
    col_w = grid._day_col_w()
    x = TIME_COL_W + day * col_w + col_w // 2
    y = HEADER_H + slot * CELL_H + CELL_H // 2
    return QPointF(float(x), float(y))


def _press(grid, day, slot, modifier=Qt.KeyboardModifier.NoModifier):
    pt = _cell_center(grid, day, slot)
    grid.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, pt, pt, pt,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, modifier))


def _release(grid, day, slot, modifier=Qt.KeyboardModifier.NoModifier):
    pt = _cell_center(grid, day, slot)
    grid.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, pt, pt, pt,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, modifier))


def _move(grid, day, slot, modifier=Qt.KeyboardModifier.NoModifier):
    pt = _cell_center(grid, day, slot)
    grid.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, pt, pt, pt,
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, modifier))


def _click(grid, day, slot, modifier=Qt.KeyboardModifier.NoModifier):
    """Press + release at same cell, no movement — counts as plain click."""
    _press(grid, day, slot, modifier)
    _release(grid, day, slot, modifier)


def _drag(grid, day_from, slot_from, day_to, slot_to):
    """Press, move to a different cell (triggers drag mode), release."""
    _press(grid, day_from, slot_from)
    _move(grid, day_to, slot_to)
    _release(grid, day_to, slot_to)


# ── Fixture ─────────────────────────────────────────────────────────────────

@pytest.fixture
def grid(qapp):
    g = _BreakScheduleGrid()
    # Pin width so col_w is deterministic (480 - 60) // 7 = 60.
    g.resize(480, GRID_H)
    return g


# ── Plain-click toggle ──────────────────────────────────────────────────────

def test_plain_click_adds_cell_to_selection(grid):
    _click(grid, 0, 0)
    assert grid.selection() == {(0, 0)}


def test_second_click_on_same_cell_toggles_off(grid):
    _click(grid, 0, 0)
    _click(grid, 0, 0)
    assert grid.selection() == set()


def test_multiple_plain_clicks_accumulate(grid):
    """Operator's mental model: click 9:10, click 9:20, click 9:30 →
    all three highlighted simultaneously. No clear between clicks."""
    _click(grid, 0, 0)
    _click(grid, 0, 1)
    _click(grid, 0, 2)
    assert grid.selection() == {(0, 0), (0, 1), (0, 2)}


def test_clicks_across_different_days_accumulate(grid):
    _click(grid, 0, 0)
    _click(grid, 3, 5)
    _click(grid, 6, 12)
    assert grid.selection() == {(0, 0), (3, 5), (6, 12)}


def test_toggle_off_one_keeps_others(grid):
    _click(grid, 0, 0)
    _click(grid, 0, 1)
    _click(grid, 0, 2)
    _click(grid, 0, 1)            # toggles middle off
    assert grid.selection() == {(0, 0), (0, 2)}


# ── Drag rectangle is additive ──────────────────────────────────────────────

def test_drag_alone_selects_rectangle(grid):
    _drag(grid, 1, 1, 2, 2)
    assert grid.selection() == {(1, 1), (1, 2), (2, 1), (2, 2)}


def test_drag_preserves_existing_click_selection(grid):
    _click(grid, 0, 0)             # pre-selected
    _drag(grid, 2, 5, 3, 6)        # rectangle elsewhere
    sel = grid.selection()
    assert (0, 0) in sel           # survived
    for d in (2, 3):
        for s in (5, 6):
            assert (d, s) in sel
    assert len(sel) == 5


def test_press_release_same_cell_after_drag_seeded_does_not_promote_to_drag(grid):
    """A press immediately followed by release at the same cell stays a
    click even if the grid had drag state from a prior interaction."""
    _drag(grid, 1, 1, 2, 2)         # 4 cells now selected
    _click(grid, 5, 10)             # plain toggle of one new cell
    sel = grid.selection()
    assert (5, 10) in sel
    assert len(sel) == 5            # drag's 4 + click's 1


# ── Esc clears ──────────────────────────────────────────────────────────────

def test_esc_clears_selection(grid):
    _click(grid, 0, 0)
    _click(grid, 0, 1)
    _click(grid, 0, 2)
    assert grid.selected_count() == 3

    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, int(Qt.Key.Key_Escape),
        Qt.KeyboardModifier.NoModifier))
    assert grid.selection() == set()


def test_esc_on_empty_selection_is_noop(grid):
    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, int(Qt.Key.Key_Escape),
        Qt.KeyboardModifier.NoModifier))
    assert grid.selection() == set()


# ── Signal emission ─────────────────────────────────────────────────────────

def test_selection_changed_emits_on_each_click_release(grid):
    counts: list[int] = []
    grid.selection_changed.connect(counts.append)

    _click(grid, 0, 0)
    _click(grid, 0, 1)
    _click(grid, 0, 2)

    # One emit per release.
    assert counts == [1, 2, 3]


def test_selection_changed_emits_zero_on_esc_clear(grid):
    _click(grid, 0, 0)
    counts: list[int] = []
    grid.selection_changed.connect(counts.append)

    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, int(Qt.Key.Key_Escape),
        Qt.KeyboardModifier.NoModifier))
    assert counts == [0]


# ── + Add path ──────────────────────────────────────────────────────────────

def test_schedule_at_selection_applies_all_clicked_cells(grid):
    """End-to-end: build multi-cell selection via clicks, then trigger the
    same path the "+ Add" button hits — every clicked cell becomes a
    scheduled break."""
    _click(grid, 0, 0)
    _click(grid, 0, 6)
    _click(grid, 0, 12)

    grid.schedule_at_selection()

    breaks = grid.get_breaks()
    assert (0, 0) in breaks
    assert (0, 6) in breaks
    assert (0, 12) in breaks
    # schedule_at_selection clears _selected after applying.
    assert grid.selection() == set()
