"""
Clock Editor mutation unit tests (Phase F2.2).

5 tests covering the in-memory working-copy mutations on ClockEditor:
  1. Add appends a new Song slot, selects it, marks dirty
  2. Insert at selected index pushes others down
  3. Delete removes selected, picks neighbor as new selection
  4. Move Up swaps with previous; idx 0 is no-op
  5. Move Down swaps with next; last index is no-op

Tests use a real Database singleton (no mocks) and construct a fresh
ClockEditor per test. The QApplication fixture from conftest is enough
to bring up Qt object lifecycle; we never call show() so widgets are
offscreen for speed.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.clock_editor import ClockEditor


@pytest.fixture
def editor(qtbot):
    """Fresh ClockEditor, real DB. No show() — widgets stay offscreen."""
    db = Database()
    e = ClockEditor(db=db)
    if e._current_clock_id is None:
        pytest.skip("no DB clock available for mutation tests")
    yield e


def _new_slots_count(e: ClockEditor) -> int:
    return len(e._slots)


# ── Test 1: Add appends + selects + marks dirty ────────────────────────

def test_add_appends_new_song_slot(editor):
    pre = _new_slots_count(editor)
    assert editor._is_dirty is False

    editor._on_add_slot()

    assert _new_slots_count(editor) == pre + 1
    assert editor._selected_slot_idx == pre   # newly-added is selected
    new_slot = editor._slots[-1]
    assert new_slot["slot_type"] == "Song"     # Q1 default
    assert new_slot["energy_pref"] == "Any"
    assert editor._is_dirty is True


# ── Test 2: Insert at selected index pushes others down ────────────────

def test_insert_at_selection_pushes_others_down(editor):
    # Ensure we have at least 2 slots so we can verify push-down
    while len(editor._slots) < 2:
        editor._on_add_slot()
    pre_len = len(editor._slots)

    # Select index 0 — track its identity so we can confirm it moved
    editor._selected_slot_idx = 0
    original_first = editor._slots[0]
    original_first_marker = id(original_first)

    editor._on_insert_slot()

    # Length grew by 1, new slot is at index 0, original first is now at 1
    assert len(editor._slots) == pre_len + 1
    assert editor._selected_slot_idx == 0
    assert id(editor._slots[1]) == original_first_marker
    assert editor._is_dirty is True


# ── Test 3: Delete removes + picks neighbor ────────────────────────────

def test_delete_removes_and_picks_neighbor(editor):
    # Make sure we have at least 3 slots
    while len(editor._slots) < 3:
        editor._on_add_slot()
    pre_len = len(editor._slots)

    # Select middle slot, capture id of slot at index+1 (becomes the new
    # idx 1 after removal — but algorithm picks idx-1 i.e. the previous
    # neighbor, so what was at idx 0 stays as the selection target).
    editor._selected_slot_idx = 1
    expected_new_selected_obj = editor._slots[0]    # idx-1

    editor._on_delete_slot()

    assert len(editor._slots) == pre_len - 1
    assert editor._selected_slot_idx == 0
    assert editor._slots[0] is expected_new_selected_obj
    assert editor._is_dirty is True


# ── Test 4: Move Up swaps with previous; idx 0 is no-op ────────────────

def test_move_up_swaps_with_previous(editor):
    while len(editor._slots) < 2:
        editor._on_add_slot()

    editor._selected_slot_idx = 1
    a = editor._slots[0]
    b = editor._slots[1]

    editor._on_move_up()

    assert editor._slots[0] is b
    assert editor._slots[1] is a
    assert editor._selected_slot_idx == 0
    assert editor._is_dirty is True

    # Reset dirty before testing no-op behavior
    editor._is_dirty = False
    editor._selected_slot_idx = 0
    state_before = list(editor._slots)
    editor._on_move_up()    # no-op at idx 0
    assert editor._slots == state_before
    assert editor._is_dirty is False


# ── Test 5: Move Down swaps with next; last is no-op ───────────────────

def test_move_down_swaps_with_next(editor):
    while len(editor._slots) < 2:
        editor._on_add_slot()

    editor._selected_slot_idx = 0
    a = editor._slots[0]
    b = editor._slots[1]

    editor._on_move_down()

    assert editor._slots[0] is b
    assert editor._slots[1] is a
    assert editor._selected_slot_idx == 1
    assert editor._is_dirty is True

    # Last index is no-op
    editor._is_dirty = False
    editor._selected_slot_idx = len(editor._slots) - 1
    state_before = list(editor._slots)
    editor._on_move_down()
    assert editor._slots == state_before
    assert editor._is_dirty is False


# ── F2.2.1 (Figma 59:2 groundwork) — color palette + schema migration ──

def test_slot_type_colors_cover_figma_59_2_set():
    """All 6 slot types from Figma 59:2 legend resolve to a real color.

    Phase F2.2.1 extended SLOT_TYPE_COLORS so the eventual 59:2 timeline
    paint code can look up Break / Station ID / Voice Track without
    hitting the TEXT_MUTED fallback. Legacy keys (Spot) stay populated
    so the F2.1+F2.2 list view doesn't regress.
    """
    from ui.clock_editor import SLOT_TYPE_COLORS, _slot_type_color

    for canonical in ("Song", "Break", "Jingle", "Station ID",
                      "Sweeper", "Voice Track"):
        assert canonical in SLOT_TYPE_COLORS, f"missing color for {canonical!r}"
        assert _slot_type_color(canonical).startswith("#")

    # Spot is the F2.1+F2.2 legacy entry — still resolvable.
    assert _slot_type_color("Spot").startswith("#")


def test_save_clock_slots_migrates_new_columns(qtbot):
    """save_clock_slots is the migration entry point — first call ensures
    fallback_category_id + pin_to_time exist on clock_slots. Idempotent:
    calling twice is safe."""
    db = Database()
    conn = db._conn()

    # Run the migration twice (idempotence check).
    db._ensure_clock_slots_columns()
    db._ensure_clock_slots_columns()

    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(clock_slots)").fetchall()}
    assert "fallback_category_id" in cols
    assert "pin_to_time" in cols
