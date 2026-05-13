"""
Songs Library multi-select + drag-select tests.

Pinned behaviour:
  • Plain click replaces the selection with just that row.
  • Ctrl+click toggles a row in/out of the existing selection.
  • Shift+click extends a range from the anchor to the clicked row.
  • Drag (LMB-held mouse move) extends the selection from the drag-
    origin row to whichever row currently sits under the cursor.
  • Row release ends the drag but preserves the selection set so
    downstream batch ops (delete, edit categories) can read it.
"""

from __future__ import annotations

import pytest

from PyQt6.QtCore import Qt

from core.database import Database


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def songs_screen(qapp, db):
    from ui.songs_library import SongsLibrary
    s = SongsLibrary(db)
    # Force the layout to compute so rows have non-zero geometry —
    # the drag-select test maps body-local y back to a row index,
    # which requires real .geometry() values.
    s.show()
    qapp.processEvents()
    if s._table_layout is not None:
        s._table_layout.activate()
    qapp.processEvents()
    yield s
    s.deleteLater()


def _row_ids(s) -> list:
    return [r._song.get("id") for r in s._row_widgets]


# ── Single click ───────────────────────────────────────────────────────


def test_plain_click_replaces_selection(songs_screen):
    s = songs_screen
    ids = _row_ids(s)
    if len(ids) < 3:
        pytest.skip("Need at least 3 songs in the dev DB")
    s._select_song(ids[1])
    assert s._selected_ids == {ids[1]}
    s._select_song(ids[2])
    # Plain click replaced, didn't accumulate
    assert s._selected_ids == {ids[2]}
    assert s._selected_id == ids[2]


# ── Ctrl modifier ──────────────────────────────────────────────────────


def test_ctrl_click_toggles_row(songs_screen):
    s = songs_screen
    ids = _row_ids(s)
    if len(ids) < 3:
        pytest.skip("Need at least 3 songs")
    s._select_song(ids[0])
    s._select_song(ids[1], modifiers=Qt.KeyboardModifier.ControlModifier)
    assert s._selected_ids == {ids[0], ids[1]}
    # Toggle off the second one
    s._select_song(ids[1], modifiers=Qt.KeyboardModifier.ControlModifier)
    assert s._selected_ids == {ids[0]}


# ── Shift range ────────────────────────────────────────────────────────


def test_shift_click_range_selects(songs_screen):
    s = songs_screen
    ids = _row_ids(s)
    if len(ids) < 5:
        pytest.skip("Need at least 5 songs")
    # Anchor at index 1
    s._select_song(ids[1])
    # Shift to index 4 — should span 1..4
    s._select_song(ids[4], modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert s._selected_ids == set(ids[1:5])


# ── Drag mechanics ─────────────────────────────────────────────────────


def test_drag_extends_selection(songs_screen):
    s = songs_screen
    ids = _row_ids(s)
    if len(ids) < 4:
        pytest.skip("Need at least 4 songs")
    s._select_song(ids[0])
    # Drag origin armed by plain click
    assert s._drag_active is True
    assert s._drag_origin_idx == 0
    # Simulate a drag: pretend mouse landed on row index 2 (in body coords)
    target_row = s._row_widgets[2]
    # The row geometry is set by the layout — its center y in body coords
    target_y = target_row.geometry().y() + target_row.height() // 2
    # Fabricate a global point we can map back via _table_body.mapFromGlobal
    # by going the other way: mapToGlobal of a point at the row's y.
    from PyQt6.QtCore import QPoint
    body_pt = QPoint(20, target_y)
    global_pt = s._table_body.mapToGlobal(body_pt)
    s._on_row_dragged_to_global(global_pt)
    assert s._selected_ids == set(ids[0:3])


def test_release_clears_drag_but_keeps_selection(songs_screen):
    s = songs_screen
    ids = _row_ids(s)
    if len(ids) < 3:
        pytest.skip("Need at least 3 songs")
    s._select_song(ids[0])
    # Force a multi-select state
    s._selected_ids = {ids[0], ids[1]}
    s._on_row_released()
    assert s._drag_active is False
    assert s._drag_origin_idx is None
    # Selection survives release
    assert s._selected_ids == {ids[0], ids[1]}


def test_selected_song_ids_public_api(songs_screen):
    s = songs_screen
    ids = _row_ids(s)
    if len(ids) < 3:
        pytest.skip("Need at least 3 songs")
    s._selected_ids = {ids[0], ids[2]}
    out = s.selected_song_ids()
    assert set(out) == {ids[0], ids[2]}


# ── Multi-delete dialog wiring ─────────────────────────────────────────


def test_confirm_dialog_single_song_emits_list(qapp):
    """delete_confirmed signal now always emits a list — even for
    single-song deletions — so the consumer iterates either way."""
    from ui.dialogs.confirm_delete_dialog import ConfirmDeleteDialog
    received: list = []
    dlg = ConfirmDeleteDialog(
        song_data={"id": 42, "title": "Solo", "artist": "X"})
    dlg.delete_confirmed.connect(lambda ids: received.append(ids))
    dlg._on_confirm()
    assert received == [[42]]
    dlg.deleteLater()


def test_confirm_dialog_multi_songs_emits_full_list(qapp):
    from ui.dialogs.confirm_delete_dialog import ConfirmDeleteDialog
    received: list = []
    dlg = ConfirmDeleteDialog(song_data_list=[
        {"id": 1, "title": "A", "artist": "Q"},
        {"id": 2, "title": "B", "artist": "Q"},
        {"id": 3, "title": "C", "artist": "Q"},
    ])
    dlg.delete_confirmed.connect(lambda ids: received.append(ids))
    dlg._on_confirm()
    assert received == [[1, 2, 3]]
    dlg.deleteLater()


def test_delete_songs_confirmed_iterates_db_calls(qapp, db, monkeypatch):
    """_delete_songs_confirmed should call db.delete_song for every
    id in the batch + clear the selection state on success."""
    from ui.songs_library import SongsLibrary
    s = SongsLibrary(db)
    deleted: list = []
    monkeypatch.setattr(s._db, "delete_song",
                         lambda sid: deleted.append(int(sid)))
    s._selected_ids = {101, 202, 303}
    monkeypatch.setattr(s, "_load_songs", lambda: None)
    s._delete_songs_confirmed([101, 202, 303])
    assert set(deleted) == {101, 202, 303}
    assert s._selected_ids == set()
    assert s._selected_id is None
    s.deleteLater()
