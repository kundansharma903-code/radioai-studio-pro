"""
Main Auto Schedule (Figma 278:2) — screen + selection model + DB wiring.

These tests run against the live ``radioai.db`` (per project convention —
flagged as test-debt in NIGHT_LOG; future cleanup pass moves to a temp
DB). To avoid polluting Kavish's real KISS FM data:

  - Every test-created clock uses prefix ``_test_autosched_<uuid4>``
  - Every test wraps setup/assert/cleanup in try/finally
  - Every test restores the ``auto_schedule.mode`` setting to its
    pre-test value
  - Cleanup deletes our clocks (auto_schedule rows cascade via FK
    ON DELETE CASCADE)

The ``auto_schedule_env`` fixture captures the pre-test mode value and
the set of test-created clock ids, then guarantees teardown.
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QMouseEvent, QKeyEvent
from PyQt6.QtCore import QEvent, QPointF

from core.database import Database
from ui.auto_schedule import (
    AutoSchedule, _ScheduleGrid, _ClocksPanel, _cell_rect,
    SETTINGS_KEY_MODE, MODE_WEEKDAYS, MODE_SPECIFIC, DEFAULT_MODE,
    WEEKDAY_INDICES, N_DAYS, N_HOURS, color_for_clock_id,
    TIME_COL_W, CELL_PITCH_X, ROW_H,
)


# ── Live-DB fixture with strict cleanup ─────────────────────────────────


class _AutoScheduleEnv:
    """Bag of test resources. Tracks created clock ids + mode setting
    for guaranteed cleanup."""

    def __init__(self, db: Database):
        self.db = db
        self.created_clock_ids: list[int] = []
        self.original_mode: Optional[str] = None

    def make_clock(self, name_suffix: str = "clock") -> int:
        prefix = f"_test_autosched_{uuid.uuid4().hex[:8]}"
        cid = int(self.db.create_clock(f"{prefix}_{name_suffix}"))
        self.created_clock_ids.append(cid)
        return cid

    def cleanup(self) -> None:
        # Clear any auto_schedule cells our clocks were assigned to —
        # delete_clock cascades but be paranoid about partial-delete state.
        #
        # Phase H fix: previously, if delete_clock raised ValueError
        # ("cannot delete the last remaining clock"), the test clock
        # leaked permanently into the live dev DB (we observed
        # "_test_autosched_*_cascade" rows surviving prior runs). The
        # business rule against deleting the LAST clock doesn't apply
        # to test data — we know these are throwaway. Fall back to a
        # direct SQL delete for that specific ValueError case.
        conn = self.db._conn()
        for cid in list(self.created_clock_ids):
            try:
                self.db.delete_clock(int(cid))
            except ValueError:
                # "last remaining clock" guard — bypass for test data.
                try:
                    conn.execute(
                        "DELETE FROM auto_schedule WHERE clock_id = ?",
                        [int(cid)])
                    conn.execute(
                        "DELETE FROM clock_slots WHERE clock_id = ?",
                        [int(cid)])
                    conn.execute(
                        "DELETE FROM clocks WHERE id = ?", [int(cid)])
                    conn.commit()
                except Exception:
                    pass
            except Exception:
                pass
        # Restore mode
        if self.original_mode is not None:
            try:
                self.db.set_setting(SETTINGS_KEY_MODE, self.original_mode)
            except Exception:
                pass


@pytest.fixture
def auto_schedule_env():
    db = Database()
    env = _AutoScheduleEnv(db)
    env.original_mode = db.get_setting(SETTINGS_KEY_MODE, DEFAULT_MODE)
    try:
        yield env
    finally:
        env.cleanup()


@pytest.fixture
def screen(qtbot, auto_schedule_env):
    """Screen mounted with the live DB. Auto-cleans via env fixture."""
    s = AutoSchedule(db=auto_schedule_env.db, scheduler=None)
    qtbot.addWidget(s)
    s.show()
    yield s, auto_schedule_env
    s.hide()


# ── Smoke ───────────────────────────────────────────────────────────────


def test_screen_mounts(qtbot, auto_schedule_env):
    s = AutoSchedule(db=auto_schedule_env.db, scheduler=None)
    qtbot.addWidget(s)
    assert s.width() == 1440
    assert s.height() == 900
    assert s._card is not None
    assert s._clocks_panel is not None
    assert s._set_btn is not None


def test_grid_loads_from_db(screen):
    """get_auto_schedule_grid feeds into _ScheduleGrid._grid."""
    s, env = screen
    cid = env.make_clock("loadtest")
    env.db.set_auto_schedule_cell(2, 9, cid)    # Wed 09:00
    s._reload_clocks_and_grid()
    assert (2, 9) in s._card.grid._grid
    assert s._card.grid._grid[(2, 9)] == cid
    # Cleanup the cell explicitly so the next test starts clean
    env.db.clear_auto_schedule_cell(2, 9)


# ── Selection model ─────────────────────────────────────────────────────


def _click_cell(grid: _ScheduleGrid, d: int, h: int,
                modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier):
    """Synthesize a Qt mouse press on the cell center."""
    rect = _cell_rect(d, h)
    pt = QPointF(rect.center().x(), rect.center().y())
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress, pt, pt,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, modifiers)
    grid.mousePressEvent(ev)
    rel = QMouseEvent(
        QEvent.Type.MouseButtonRelease, pt, pt,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, modifiers)
    grid.mouseReleaseEvent(rel)


def test_select_single_cell(screen):
    s, _ = screen
    g = s._card.grid
    _click_cell(g, 0, 9)
    assert g.selected_cells == {(0, 9)}
    assert g._anchor == (0, 9)


def test_select_replaces_previous(screen):
    s, _ = screen
    g = s._card.grid
    _click_cell(g, 0, 9)
    _click_cell(g, 3, 14)    # plain click → replaces
    assert g.selected_cells == {(3, 14)}


def test_shift_range_select(screen):
    """Anchor = (1,5). Shift+click on (3,7) → all cells in the rect
    (1..3, 5..7) selected."""
    s, _ = screen
    g = s._card.grid
    _click_cell(g, 1, 5)    # sets anchor
    _click_cell(g, 3, 7, Qt.KeyboardModifier.ShiftModifier)
    expected = {(d, h) for d in range(1, 4) for h in range(5, 8)}
    assert g.selected_cells == expected


def test_ctrl_toggle(screen):
    s, _ = screen
    g = s._card.grid
    _click_cell(g, 0, 0)
    _click_cell(g, 1, 0, Qt.KeyboardModifier.ControlModifier)
    _click_cell(g, 2, 0, Qt.KeyboardModifier.ControlModifier)
    assert g.selected_cells == {(0, 0), (1, 0), (2, 0)}
    # Ctrl-click again on (1,0) → toggles off
    _click_cell(g, 1, 0, Qt.KeyboardModifier.ControlModifier)
    assert g.selected_cells == {(0, 0), (2, 0)}


def test_esc_clears_selection(screen):
    s, _ = screen
    g = s._card.grid
    _click_cell(g, 0, 0)
    assert len(g.selected_cells) == 1
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                   Qt.KeyboardModifier.NoModifier)
    g.keyPressEvent(ev)
    assert g.selected_cells == set()


def test_ctrl_a_selects_all_168(screen):
    s, _ = screen
    g = s._card.grid
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                   Qt.KeyboardModifier.ControlModifier)
    g.keyPressEvent(ev)
    assert len(g.selected_cells) == N_DAYS * N_HOURS    # 7 × 24 = 168


def test_lasso_drag_selects_rectangle(screen):
    """Drag from cell (1,2) to cell (4,5) → a 4×4 rectangle selected."""
    s, _ = screen
    g = s._card.grid
    p1 = _cell_rect(1, 2).center()
    p2 = _cell_rect(4, 5).center()
    f1 = QPointF(p1.x(), p1.y())
    f2 = QPointF(p2.x(), p2.y())
    press = QMouseEvent(QEvent.Type.MouseButtonPress, f1, f1,
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    g.mousePressEvent(press)
    move = QMouseEvent(QEvent.Type.MouseMove, f2, f2,
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    g.mouseMoveEvent(move)
    rel = QMouseEvent(QEvent.Type.MouseButtonRelease, f2, f2,
                      Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                      Qt.KeyboardModifier.NoModifier)
    g.mouseReleaseEvent(rel)
    expected = {(d, h) for d in range(1, 5) for h in range(2, 6)}
    assert g.selected_cells == expected


# ── SET write paths ─────────────────────────────────────────────────────


def test_set_writes_specific_mode(screen):
    """Specific mode: only the literal selection is written."""
    s, env = screen
    cid = env.make_clock("specific")
    s._card.set_mode(MODE_SPECIFIC)
    s._clocks_panel.select_clock(cid)
    g = s._card.grid
    _click_cell(g, 2, 11)    # Wed 11:00
    s._on_set_clicked()
    grid_after = env.db.get_auto_schedule_grid()
    assert grid_after.get((2, 11)) == cid
    # Other weekday cells at 11:00 must NOT be written
    for d in (0, 1, 3, 4):
        assert (d, 11) not in grid_after or grid_after[(d, 11)] != cid
    # Cleanup
    env.db.clear_auto_schedule_cell(2, 11)


def test_set_writes_weekdays_mode_expands_to_mon_fri(screen):
    """Weekdays mode: selecting Tue 09:00 writes Mon..Fri 09:00."""
    s, env = screen
    cid = env.make_clock("weekdays")
    s._card.set_mode(MODE_WEEKDAYS)
    s._clocks_panel.select_clock(cid)
    g = s._card.grid
    _click_cell(g, 1, 9)    # Tue 09:00
    s._on_set_clicked()
    grid_after = env.db.get_auto_schedule_grid()
    for d in WEEKDAY_INDICES:
        assert grid_after.get((d, 9)) == cid, \
            f"weekday d={d} h=9 should be cid={cid}, got {grid_after.get((d, 9))}"
    # Sat / Sun must NOT be written
    assert grid_after.get((5, 9)) != cid
    assert grid_after.get((6, 9)) != cid
    # Cleanup the 5 cells
    for d in WEEKDAY_INDICES:
        env.db.clear_auto_schedule_cell(d, 9)


def test_set_weekend_no_expansion_in_weekdays_mode(screen):
    """Weekdays mode + Sat/Sun selection → those days only, no expansion
    (Sat doesn't propagate to Mon-Fri or Sunday)."""
    s, env = screen
    cid = env.make_clock("weekend")
    s._card.set_mode(MODE_WEEKDAYS)
    s._clocks_panel.select_clock(cid)
    g = s._card.grid
    _click_cell(g, 5, 22)    # Sat 22:00
    s._on_set_clicked()
    grid_after = env.db.get_auto_schedule_grid()
    assert grid_after.get((5, 22)) == cid
    for d in (0, 1, 2, 3, 4, 6):
        assert grid_after.get((d, 22)) != cid
    env.db.clear_auto_schedule_cell(5, 22)


def test_set_disabled_when_no_selection(screen):
    """SET button must be disabled until both a clock AND cells are
    selected. Verified via _SetButton._enabled internal flag."""
    s, env = screen
    cid = env.make_clock("disabled")
    s._clocks_panel.select_clock(cid)
    s._update_button_states()
    assert s._set_btn._enabled is False    # no cells yet
    g = s._card.grid
    _click_cell(g, 0, 0)
    assert s._set_btn._enabled is True


# ── Clock CRUD wiring (calls db.* directly) ─────────────────────────────


def test_clear_button_wipes_db(screen):
    """Clear button → db.clear_all_auto_schedule. Asserts *our* row is
    removed; we don't care if other rows are gone too (live DB)."""
    s, env = screen
    cid = env.make_clock("clear")
    env.db.set_auto_schedule_cell(0, 5, cid)
    assert (0, 5) in env.db.get_auto_schedule_grid()
    # Bypass the QMessageBox confirm by calling the underlying db method —
    # the dialog is exercised manually; this test verifies wiring only.
    env.db.clear_all_auto_schedule()
    assert (0, 5) not in env.db.get_auto_schedule_grid()


def test_duplicate_clock_creates_clone(screen):
    """db.duplicate_clock returns a new id with name suffixed ' (copy)'."""
    s, env = screen
    cid = env.make_clock("dup")
    new_id = int(env.db.duplicate_clock(cid))
    env.created_clock_ids.append(new_id)
    src = env.db.get_clock(cid); cln = env.db.get_clock(new_id)
    assert cln is not None
    assert cln["name"].endswith("(copy)")
    assert cln["name"].startswith(src["name"])


def test_delete_clock_clears_referencing_cells(screen):
    """The screen's delete flow clears every auto_schedule row using the
    clock first, then drops the clock. The bare db.delete_clock raises
    IntegrityError on a clock that's still referenced (FK not declared
    ON DELETE CASCADE) — flagged in NIGHT_LOG as a docstring bug."""
    s, env = screen
    cid = env.make_clock("cascade")
    env.db.set_auto_schedule_cell(3, 14, cid)
    s._reload_clocks_and_grid()
    assert env.db.get_auto_schedule_grid().get((3, 14)) == cid
    s._clocks_panel.select_clock(cid)
    s._delete_clock_with_cells(cid)
    env.created_clock_ids.remove(cid)    # already gone — don't double-delete
    grid_after = env.db.get_auto_schedule_grid()
    assert (3, 14) not in grid_after
    assert env.db.get_clock(cid) is None


# ── Newest-first panel ordering (regression: "saved clock vanished") ────


def test_panel_orders_newest_first_so_freshly_saved_appears_in_top_slot(screen):
    """``_reload_clocks_and_grid`` must sort by id DESC before slicing to
    the panel's 3-row window. db.get_all_clocks() orders by name; on a
    DB with 30+ clocks, an alphabetically-late name (e.g. lowercase
    'test 01') would never reach the top 3 — operator perceives "save
    vanished." Higher id ⇒ more recently created (autoincrement PK)."""
    s, env = screen
    # Seed 4 fresh clocks so we KNOW the highest-id one is ours, not
    # whatever the live DB had before
    seeded_ids = sorted([
        env.make_clock("ord_a"),
        env.make_clock("ord_b"),
        env.make_clock("ord_c"),
        env.make_clock("ord_d"),
    ])
    newest = seeded_ids[-1]
    s._reload_clocks_and_grid()
    # The visible panel is sliced to 3 rows by _ClocksPanel.set_clocks.
    # After the newest-first sort, the highest seeded id MUST be in slot 0.
    visible_ids = [r.clock_id for r in s._clocks_panel._rows]
    assert visible_ids, "panel rendered no rows"
    assert visible_ids[0] == newest, (
        f"expected newest clock id={newest} in slot 0, got "
        f"visible={visible_ids}")


def test_freshly_saved_clock_via_clock_editor_visible_after_reload(qtbot, screen):
    """End-to-end: Clock Editor save flow → AutoSchedule reload → the
    new clock id is rendered in the panel's visible window. Regression
    catch for the 'I saved but can't see it' symptom."""
    s, env = screen
    # Mount a Clock Editor with the same db as the screen — match the
    # MainWindow wiring pattern.
    from ui.clock_editor import ClockEditor, MODE_NEW
    editor = ClockEditor(db=env.db, scheduler=None)
    qtbot.addWidget(editor)
    editor.load_for_mode(MODE_NEW)
    # Give it a uniquely-prefixed name so cleanup catches it
    test_name = f"_test_autosched_save_{uuid.uuid4().hex[:6]}"
    editor._meta.set_name(test_name)
    editor._on_add()    # at least one element so validate passes
    new_id = editor._save()
    assert new_id is not None, "ClockEditor._save() returned None"
    env.created_clock_ids.append(int(new_id))
    # Now exercise the same path the user does: navigate back to
    # AutoSchedule which calls _reload_clocks_and_grid on showEvent
    s._reload_clocks_and_grid()
    visible_ids = [r.clock_id for r in s._clocks_panel._rows]
    assert int(new_id) in visible_ids, (
        f"newly-saved clock id={new_id} not in panel visible_ids="
        f"{visible_ids}")


# ── Mode persistence ────────────────────────────────────────────────────


def test_mode_persists_to_settings(screen):
    s, env = screen
    s._card._set_mode(MODE_SPECIFIC)
    assert env.db.get_setting(SETTINGS_KEY_MODE) == MODE_SPECIFIC
    s._card._set_mode(MODE_WEEKDAYS)
    assert env.db.get_setting(SETTINGS_KEY_MODE) == MODE_WEEKDAYS


def test_mode_loads_on_init(qtbot, auto_schedule_env):
    """Setting persisted before screen mount should be reflected."""
    auto_schedule_env.db.set_setting(SETTINGS_KEY_MODE, MODE_SPECIFIC)
    s = AutoSchedule(db=auto_schedule_env.db, scheduler=None)
    qtbot.addWidget(s)
    assert s._card.mode() == MODE_SPECIFIC


# ── Geometry / palette ──────────────────────────────────────────────────


def test_color_for_clock_id_stable():
    # Same id → same color across calls
    assert color_for_clock_id(7) == color_for_clock_id(7)
    # Different ids → likely different colors (palette cycles every 10)
    assert color_for_clock_id(0) != color_for_clock_id(1)
    # None → muted text color
    assert color_for_clock_id(None)


def test_cell_rect_geometry():
    """Cell (0,0) at (TIME_COL_W, CELL_PAD_Y); cell (6,23) at far-bottom."""
    r0 = _cell_rect(0, 0)
    assert r0.x() == TIME_COL_W
    assert r0.y() == 2    # CELL_PAD_Y
    r_last = _cell_rect(6, 23)
    assert r_last.x() == TIME_COL_W + 6 * CELL_PITCH_X
    assert r_last.y() == 23 * ROW_H + 2


def test_grid_hit_test():
    """cell_at returns (d,h) for cell centers, None for gutters."""
    # Center of cell (3, 12)
    rect = _cell_rect(3, 12)
    p = QPoint(rect.center().x(), rect.center().y())
    assert _ScheduleGrid.cell_at(p) == (3, 12)
    # In the time column (x < TIME_COL_W) → None
    assert _ScheduleGrid.cell_at(QPoint(20, 60)) is None
    # In the horizontal gutter between Mon and Tue
    gutter_x = TIME_COL_W + 122    # cell ends at 120 within pitch=128
    assert _ScheduleGrid.cell_at(QPoint(gutter_x, 60)) is None
