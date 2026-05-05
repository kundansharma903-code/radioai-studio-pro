"""
Clock Editor schema + DB CRUD tests — Phase F-Final C3 rewrite (ref 225:5).

The full-screen ui/clock_editor.py was deleted; the editor is now a
modal QDialog (ui/dialogs/clock_editor_dialog.py). The mutation /
slot-pill / per-type-page tests that this file used to host are no
longer applicable — the modal uses Add / Insert / Replace / Delete
on a circular face, exercised by tests/test_clock_editor_dialog.py.

This file retains only the schema-migration + clock-CRUD tests that
are paradigm-agnostic.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.dialogs.clock_editor_dialog import (
    SLOT_TYPE_COLOR, SLOT_TYPES,
)


def test_slot_type_palette_has_six_canonical_types():
    """Modal Clock Editor exposes 5 canonical types (Song / Jingle /
    Spot / Voice Track / Sweeper) from the ref 225:5 icon row.
    'Break' / 'Station ID' from the F2.3 set live in scheduler/picker
    code; UI-side these condense down to Spot."""
    assert len(SLOT_TYPES) == 5
    for t in SLOT_TYPES:
        assert t in SLOT_TYPE_COLOR
        assert SLOT_TYPE_COLOR[t].startswith("#")


def test_save_clock_slots_migrates_columns(qtbot):
    """First call ensures fallback_category_id + pin_to_time +
    duration_seconds + ref_text + selection_mode +
    filter_json + specific_song_id + specific_artist_id +
    minute_position all exist on clock_slots. Idempotent."""
    db = Database()
    db._ensure_clock_slots_columns()
    db._ensure_clock_slots_columns()
    cols = {r[1] for r in db._conn().execute(
        "PRAGMA table_info(clock_slots)").fetchall()}
    for expected in ("fallback_category_id", "pin_to_time",
                     "duration_seconds", "ref_text", "selection_mode",
                     "filter_json", "specific_song_id",
                     "specific_artist_id", "minute_position"):
        assert expected in cols, f"missing {expected!r}"


def test_save_clock_migrates_columns(qtbot):
    """clocks gains the C3 columns (comments / color / backup_song_filter
    / loop_cycle_enabled / show_only_descriptions)."""
    db = Database()
    db._ensure_clocks_columns()
    db._ensure_clocks_columns()
    cols = {r[1] for r in db._conn().execute(
        "PRAGMA table_info(clocks)").fetchall()}
    for expected in ("comments", "color", "backup_song_filter",
                     "loop_cycle_enabled", "show_only_descriptions"):
        assert expected in cols, f"missing {expected!r}"


def test_clock_crud_round_trip(qtbot):
    """db.create_clock / save_clock / get_clock / duplicate_clock /
    delete_clock all still work after the C3 schema additions."""
    db = Database()
    cid = db.create_clock("Mutations Test")
    assert cid > 0
    # Save with new C3 fields
    db.save_clock(cid, {
        "name":     "Renamed Mutations Test",
        "comments": "test comment",
        "color":    "#10b981",
    })
    row = db.get_clock(cid)
    assert row["name"]     == "Renamed Mutations Test"
    assert row["comments"] == "test comment"
    assert row["color"]    == "#10b981"
    # Duplicate
    new_id = db.duplicate_clock(cid)
    assert new_id != cid
    # Cleanup
    db.delete_clock(new_id)
    db._conn().execute("DELETE FROM broadcast_log WHERE clock_id = ?", [cid])
    db._conn().commit()
    try:
        db.delete_clock(cid)
    except (ValueError, Exception):
        pass


def test_save_clock_slots_round_trips_filter_json(qtbot):
    """C3 filter_json / minute_position / specific_song_id round-trip
    through save_clock_slots."""
    db = Database()
    cid = db.create_clock("Filter Persist Test")
    slots = [{
        "slot_type": "Song", "category_id": None,
        "energy_pref": "Any", "vocal_pref": "Any",
        "priority_pref": "Normal", "is_break": 0, "item_id": 0,
        "filter_json": '{"sound_code": "Hot", "bpm_min": 100, "bpm_max": 130}',
        "minute_position": 12,
        "selection_mode": "random_from_category",
    }]
    db.save_clock_slots(cid, slots)
    rows = list(db.get_clock_slots(cid))
    assert len(rows) == 1
    r = rows[0]
    assert r["filter_json"] is not None
    assert "Hot" in r["filter_json"]
    assert int(r["minute_position"]) == 12
    # Cleanup
    db.delete_clock(cid)
