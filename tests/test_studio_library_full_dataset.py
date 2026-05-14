"""
Studio v3 → Libraries panel: full-library data source + category menu.

Pinned behaviour after the Songs-library rewire:
  • On mount, the Libraries panel's Songs view is seeded from
    db.get_songs(category_id=None) — NOT self._queue_songs. So the
    table row count reflects the operator's total library, not the
    current scheduler queue.
  • _LibCategoryDropdown emits a `clicked` signal on left mousePress
    so the host can pop a category menu. The widget itself owns no
    DB handle.
  • _LibrariesPanel.set_songs attaches the source dict to each row's
    .data payload so selected_song_data() resolves the rich record
    even when a search filter has trimmed the visible table.
  • set_category_label updates the dropdown label + per-scope count
    independently of set_songs — the host can flip "All Songs" ↔
    "Bollywood Hits" without rebuilding rows.
  • Studio._load_library_songs(category_id):
      None → all enabled songs, label "All Songs"
      int  → that category's songs, label = category name
  • Studio.showEvent re-fetches the library when the Songs tile is
    the active type — picks up DB changes from Songs Library mutations
    without an app restart.
  • Search filter searches the FULL library now; previously it
    searched the 12-row queue (operator-blocker for "find a song,
    add it").

Mocks: minimal _FakeIJE (Studio __init__ touches it).
"""

from __future__ import annotations

import pytest

from PyQt6.QtCore import Qt, QEvent, QPointF
from PyQt6.QtGui import QMouseEvent

from core.database import Database
from ui.studio import (
    Studio, _LibrariesPanel, _LibCategoryDropdown, _LibSongRow,
)


class _RecordingSignal:
    def __init__(self): self._slots: list = []
    def connect(self, slot): self._slots.append(slot)
    def disconnect(self, _slot=None): self._slots.clear()
    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _FakeIJE:
    def __init__(self):
        self.pad_started = _RecordingSignal()
        self.pad_ended = _RecordingSignal()
        self.pad_stopped = _RecordingSignal()
    def play_pad(self, *a, **k): return True
    def stop_pad(self, _id): return True
    def stop_all(self): return 0
    def is_playing(self, _id): return False


@pytest.fixture
def db():
    return Database()


# ── _LibCategoryDropdown — emits `clicked` on left mousePress ───────────


def test_dropdown_emits_clicked_on_left_mouse_press(qapp):
    d = _LibCategoryDropdown()
    received = []
    d.clicked.connect(lambda: received.append(True))
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10), QPointF(10, 10),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    d.mousePressEvent(ev)
    assert received == [True]
    d.deleteLater()


def test_dropdown_ignores_right_mouse_press(qapp):
    """Right-click shouldn't open the menu — keeps the gesture
    available for future context menus."""
    d = _LibCategoryDropdown()
    received = []
    d.clicked.connect(lambda: received.append(True))
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10), QPointF(10, 10),
        Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    d.mousePressEvent(ev)
    assert received == []
    d.deleteLater()


# ── _LibSongRow — carries optional data payload ────────────────────────


def test_lib_song_row_carries_data_payload():
    r = _LibSongRow(artist="Arijit Singh", title="Tum Hi Ho",
                    data={"id": 42, "file_path": "/tmp/x.mp3"})
    assert r.artist == "Arijit Singh"
    assert r.title == "Tum Hi Ho"
    assert r.data == {"id": 42, "file_path": "/tmp/x.mp3"}


def test_lib_song_row_data_defaults_to_none():
    r = _LibSongRow(artist="a", title="t")
    assert r.data is None


# ── _LibrariesPanel — set_songs attaches dict; selected_song_data ───────


def test_set_songs_attaches_data_to_rows(qapp):
    p = _LibrariesPanel()
    songs = [
        {"id": 1, "title": "Tum Hi Ho", "artist": "Arijit Singh",
         "file_path": "/tmp/a.mp3"},
        {"id": 2, "title": "Channa Mereya", "artist": "Arijit Singh"},
    ]
    p.set_songs(songs, len(songs))
    assert len(p._all_rows) == 2
    assert p._all_rows[0].data == songs[0]
    assert p._all_rows[1].data == songs[1]
    p.deleteLater()


def test_selected_song_data_returns_filtered_row(qapp):
    """The critical regression-guard: when a search filter is active,
    selected_song_data() must return the dict for the VISIBLE selected
    row, not whatever sits at that index in the unfiltered cache."""
    p = _LibrariesPanel()
    songs = [
        {"id": 1, "title": "Tum Hi Ho",     "artist": "Arijit Singh"},
        {"id": 2, "title": "Channa Mereya", "artist": "Arijit Singh"},
        {"id": 3, "title": "Bohemian Rhapsody", "artist": "Queen"},
    ]
    p.set_songs(songs, len(songs))
    # Filter to "queen" — should leave only row id=3
    p._search.setText("queen")
    p._apply_search_filter()
    p._on_row_selected(0)
    picked = p.selected_song_data()
    assert picked is not None
    assert picked["id"] == 3
    assert picked["title"] == "Bohemian Rhapsody"
    p.deleteLater()


def test_selected_song_data_returns_none_when_unselected(qapp):
    p = _LibrariesPanel()
    p.set_songs(
        [{"id": 1, "title": "x", "artist": "y"}], 1)
    assert p.selected_song_data() is None
    p.deleteLater()


def test_set_category_label_updates_dropdown(qapp):
    p = _LibrariesPanel()
    p.set_category_label("Bollywood Hits", 127)
    assert p._cat_dropdown._label == "Bollywood Hits"
    assert p._cat_dropdown._count == 127
    p.deleteLater()


def test_set_songs_does_not_touch_dropdown_label(qapp):
    """Regression-guard: set_songs used to also write the dropdown
    label, which coupled the table source and the visible label. Now
    they're separate — operator's "Bollywood" label survives a
    set_songs([bollywood_rows]) call from outside."""
    p = _LibrariesPanel()
    p.set_category_label("Bollywood Hits", 100)
    p.set_songs([{"id": 1, "title": "a", "artist": "b"}], 1)
    # Label should still say Bollywood Hits, not flip to "All Songs"
    assert p._cat_dropdown._label == "Bollywood Hits"
    p.deleteLater()


# ── Studio.__init__ seeds the panel with the FULL library ──────────────


def test_studio_mounts_with_full_library_not_queue(qtbot, db, engine):
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    # The library panel's row count should match the DB's enabled-song
    # count, NOT len(_queue_songs).
    library_count = len(s._libraries._all_rows)
    db_count = len(list(db.get_songs()))
    assert library_count == db_count
    # And the dropdown should default to "All Songs"
    assert s._libraries._cat_dropdown._label == "All Songs"
    assert s._libraries._cat_dropdown._count == db_count


def test_studio_library_dropdown_label_changes_with_category(
        qtbot, db, engine):
    """_load_library_songs(category_id) updates both the data source
    and the dropdown label in one shot."""
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    # Pick a category with at least 1 song
    cats = list(db.get_categories())
    chosen = None
    for c in cats:
        if int(c["song_count"] or 0) > 0:
            chosen = c; break
    if chosen is None:
        pytest.skip("Dev DB needs ≥1 category with songs")
    cid = int(chosen["id"])
    cname = (chosen["name"] or "").strip()
    cat_song_count = int(chosen["song_count"])
    s._load_library_songs(cid)
    assert s._libraries._cat_dropdown._label == cname
    assert s._libraries._cat_dropdown._count == cat_song_count
    assert len(s._libraries._all_rows) == cat_song_count
    assert s._library_current_category_id == cid


def test_studio_library_loads_all_songs_when_none(qtbot, db, engine):
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    # First load a specific category, then reset back
    cats = list(db.get_categories())
    chosen = next((c for c in cats
                    if int(c["song_count"] or 0) > 0), None)
    if chosen is None:
        pytest.skip("Dev DB needs ≥1 category with songs")
    s._load_library_songs(int(chosen["id"]))
    s._load_library_songs(None)
    assert s._libraries._cat_dropdown._label == "All Songs"
    assert s._library_current_category_id is None


def test_studio_library_rows_carry_item_type_song(qtbot, db, engine):
    """Library rows must carry _item_type='song' so the DELETE id+
    type tuple match works for songs added via library → queue."""
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    if not s._libraries._all_rows:
        pytest.skip("Dev DB has no enabled songs")
    s._libraries._on_row_selected(0)
    data = s._libraries.selected_song_data()
    assert data is not None
    assert data.get("_item_type") == "song"


def test_studio_library_search_finds_real_library_song(
        qtbot, db, engine):
    """The operator's actual workflow: type a song name in the search
    box, find it in the library, then ADD. Today's broken version
    only searched _queue_songs (12 rows); this test pins the fix."""
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    if not s._libraries._all_rows:
        pytest.skip("Dev DB has no enabled songs")
    # Pick a song name from the full library that's UNLIKELY to be in
    # the scheduler's 12-row preview — use the LAST row's title.
    library_songs = list(db.get_songs())
    if len(library_songs) < 50:
        pytest.skip("Need ≥50 songs to demonstrate library vs queue")
    target_title = library_songs[-1]["title"] or ""
    if not target_title:
        pytest.skip("Last library song has no title")
    s._libraries._search.setText(target_title)
    s._libraries._apply_search_filter()
    # The filter result must contain at least one row matching by title
    matched = [r for r in s._libraries._rows
               if (r.title or "").lower() == target_title.lower()]
    assert matched, (
        f"Search filter could not find {target_title!r} in library — "
        f"panel may still be sourcing from queue not library")
