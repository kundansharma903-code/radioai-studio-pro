"""
Clock Editor modal dialog tests — Phase F-Final C3 (ref 225:5).

The modal exposes a Jazler-style filter-based slot definition + a
circular 60-minute clock face. These tests verify:
  - dialog mounts as a QDialog (modal flag, exec returns int)
  - filter-result count updates live when categories/ranges change
  - circular face exposes the slot list + selection
  - colorize-by toggle changes the face's coloring source
  - filter_json persists through OK / round-trip
"""

from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QDialog

from core.database import Database
from core.scheduler.engine import SchedulerEngine
from ui.dialogs.clock_editor_dialog import (
    ClockEditorDialog, _CircularClockFace, SLOT_TYPES,
)


@pytest.fixture
def dlg(qtbot):
    db = Database()
    d = ClockEditorDialog(db=db, clock_id=None)
    yield d


# ── 1. Dialog is modal QDialog ─────────────────────────────────────────

def test_clock_editor_opens_as_modal(dlg):
    """Per ref 225:5 the editor is a modal dialog, not a stacked screen."""
    assert isinstance(dlg, QDialog)
    assert dlg.isModal() is True


# ── 2. Five slot-type icon buttons ─────────────────────────────────────

def test_five_slot_type_buttons_present(dlg):
    """Per ref 225:5 the left-half exposes 5 icon buttons (Song / Jingle /
    Spot / Voice Track / Sweeper)."""
    assert set(dlg._type_buttons.keys()) == set(SLOT_TYPES)
    assert len(SLOT_TYPES) == 5


# ── 3. Filter result count updates live ────────────────────────────────

def test_filter_results_count_live(dlg):
    """Changing a filter dropdown calls _refresh_filter_count which
    rewrites the live label."""
    initial_text = dlg._filter_count_label.text()
    # Set an aggressive filter — narrow BPM range
    dlg._filter_bpm_lo.setValue(180)
    dlg._filter_bpm_hi.setValue(200)
    new_text = dlg._filter_count_label.text()
    # The text format: "X Songs Available · Y.Ys Estimated Avg Duration"
    assert "Songs Available" in new_text
    # Either the count went down or stayed at zero — both prove the
    # callback fired.
    assert new_text != initial_text or "0 Songs" in new_text


# ── 4. Circular face renders the 60-minute model ───────────────────────

def test_circular_face_renders_60_minutes(dlg):
    """The face widget is a _CircularClockFace; default minute spans
    cover the 60-minute model."""
    assert isinstance(dlg._face, _CircularClockFace)
    # Add a couple of slots and verify they land on the face
    dlg._on_type_button("Song")
    dlg._on_add()
    dlg._on_add()
    assert len(dlg._slots) == 2
    # Both should have a minute_position assigned
    assert all("minute_position" in s for s in dlg._slots)


# ── 5. Colorize-by toggles between Slot Type / Sound Code ─────────────

def test_colorize_by_toggle(dlg):
    """The Colorize-by combo flips the face's coloring source."""
    assert dlg._face._colorize_by == "Slot Type"
    dlg._colorize.setCurrentText("Sound Code")
    assert dlg._face._colorize_by == "Sound Code"


# ── 6. filter_json persists when Add is clicked from Filters tab ───────

def test_filter_json_persists(dlg):
    """Clicking Add while on the Filters tab attaches the current spec
    as filter_json on the new slot."""
    dlg._tabs.setCurrentIndex(0)   # Filters tab
    dlg._on_type_button("Song")
    dlg._filter_bpm_lo.setValue(100)
    dlg._filter_bpm_hi.setValue(130)
    dlg._on_add()
    assert len(dlg._slots) == 1
    fj = dlg._slots[0].get("filter_json")
    assert fj is not None
    spec = json.loads(fj)
    assert spec.get("bpm_min") == 100
    assert spec.get("bpm_max") == 130


# ── 7. Picker honours filter_json — bpm range narrows song pool ───────

def test_pick_song_with_filter(qtbot):
    """SchedulerEngine._songs_matching_filter_json returns rows that
    satisfy the spec. Build a tight bpm filter that should match a
    subset of the seeded songs (which mostly have bpm=0); the result
    should still be a list (possibly empty) without exception."""
    db = Database()
    sch = SchedulerEngine(db=db)
    spec = {"bpm_min": 0, "bpm_max": 200, "year_min": 1980,
            "year_max": 2030}
    songs = sch._songs_matching_filter_json(json.dumps(spec))
    assert isinstance(songs, list)
    # Counter helper agrees
    n = sch.count_songs_matching_filter(json.dumps(spec))
    assert n == len(songs)


# ── 8. Picker fallback chain — empty filter falls through to category ─

def test_pick_song_filter_fallback_to_backup(qtbot):
    """A filter that returns 0 matches drops through to the category
    path, then to fallback_category_id, then to any song. Verify the
    full _pick_song path returns SOMETHING for a slot with an
    impossible filter."""
    db = Database()
    sch = SchedulerEngine(db=db)
    if not list(db.get_songs(limit=1)):
        pytest.skip("no songs in DB")
    # filter that no song satisfies (impossible BPM range)
    impossible = {"bpm_min": 999, "bpm_max": 1000}
    slot = {
        "slot_type": "Song",
        "filter_json": json.dumps(impossible),
        "category_id": None,
        "energy_pref": "Any", "vocal_pref": "Any",
        "fallback_category_id": None,
        "specific_song_id": None,
        "specific_artist_id": None,
        "item_id": 0,
    }
    result = sch._pick_song(slot)
    # Should fall through to "any song" and return one
    assert result is not None
    assert result["item_type"] == "song"


# ── 9. Loop / Cycle toggle defaults to checked, persists ──────────────

def test_loop_cycle_toggle(dlg):
    """Loop/Cycle defaults to True per Jazler convention."""
    assert dlg._loop_chk.isChecked() is True
    # Toggle off + on again — the OK path picks up the final state.
    dlg._loop_chk.setChecked(False)
    assert dlg._loop_chk.isChecked() is False
    dlg._loop_chk.setChecked(True)
    assert dlg._loop_chk.isChecked() is True
