"""
Clock Editor — sweeper-type slot configuration (Phase 3 of sweeper
ecosystem wiring).

Operator scenario: when building a clock pattern, the broadcaster wants
to pin a specific sweeper to a slot ("KISS Open Bridge @ Bridge at End"),
not just take a random pick from the sweepers library every cycle.

Pinned behaviour:
  • _AvailableElementsCard exposes a sweeper picker + position picker
    that's only visible when element_type='sweeper'.
  • set_sweepers populates the picker with each sweeper's name + id;
    "Random (any)" is always the leading option.
  • selected_sweeper_id() returns None for "Random (any)" and the
    sweeper id for any specific pick.
  • _build_element_from_filters routes sweeper-type elements through
    the sweeper picker (selection_mode='specific' + item_id) when
    a sweeper is picked, falls back to random_from_category otherwise.
  • _elements_to_slot_payload forwards item_id + sweeper_position into
    the clock_slots row, so SchedulerEngine._pick_sweeper sees the
    pin via clock_slots.item_id.
  • Visibility toggle: sweeper type → song-filter widgets hidden,
    sweeper widgets visible. Switching back to song → reverse.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import Database
from ui.clock_editor import (
    ClockEditor, _AvailableElementsCard, MODE_NEW,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded_sweepers(db):
    """Insert 2 active sweepers so the picker has real options."""
    prefix = f"_test_clock_swp_{uuid.uuid4().hex[:8]}_"
    conn = db._conn()
    ids = []
    rows = [
        (prefix + "Bridge",  "Station", 8000, "Bridge at End", 1),
        (prefix + "Opener",  "Station", 6000, "Start of Song", 1),
    ]
    try:
        for name, cat, dur, pos, en in rows:
            cur = conn.execute(
                "INSERT INTO sweepers (name, category, file_path, "
                "duration_ms, position, is_enabled) VALUES "
                "(?, ?, 'x.mp3', ?, ?, ?)",
                [name, cat, dur, pos, en])
            ids.append(int(cur.lastrowid))
        conn.commit()
        yield prefix, ids
    finally:
        for sid in ids:
            conn.execute("DELETE FROM sweepers WHERE id = ?", [sid])
        conn.commit()


# ── _AvailableElementsCard widget contract ─────────────────────────────────

def test_card_exposes_sweeper_pickers(qapp):
    card = _AvailableElementsCard()
    # Pickers exist
    assert hasattr(card, "_dd_sweeper_pick")
    assert hasattr(card, "_dd_sweeper_position")
    # Hidden by default (element_type starts at 'song')
    assert card._dd_sweeper_pick.isVisibleTo(card) is False
    assert card._dd_sweeper_position.isVisibleTo(card) is False
    card.deleteLater()


def test_set_sweepers_populates_picker_with_random_first(qapp):
    card = _AvailableElementsCard()
    card.set_sweepers([
        {"id": 5,  "name": "KISS Energy"},
        {"id": 12, "name": "Drop the Beat"},
    ])
    labels = card._dd_sweeper_pick._options
    assert labels[0] == "Random (any)"
    assert any("KISS Energy" in l and "(#5)" in l for l in labels)
    assert any("Drop the Beat" in l and "(#12)" in l for l in labels)
    # Selection defaults to Random (no specific pin)
    assert card.selected_sweeper_id() is None
    card.deleteLater()


def test_selected_sweeper_id_returns_id_for_specific_pick(qapp):
    card = _AvailableElementsCard()
    card.set_sweepers([{"id": 7, "name": "Sweep7"}])
    # Force the picker to the specific entry (set_value via internal API)
    target_label = next(l for l in card._dd_sweeper_pick._options
                        if "Sweep7" in l)
    card._dd_sweeper_pick._value = target_label
    assert card.selected_sweeper_id() == 7
    card.deleteLater()


def test_visibility_toggles_with_element_type(qapp):
    card = _AvailableElementsCard()
    # Default = 'song' → song-filter widgets visible, sweeper widgets hidden
    assert card._dd_sound_code.isVisibleTo(card) is True
    assert card._dd_sweeper_pick.isVisibleTo(card) is False
    # Switch to sweeper → flip
    card.set_element_type("sweeper")
    assert card._dd_sound_code.isVisibleTo(card) is False
    assert card._dd_sweeper_pick.isVisibleTo(card) is True
    assert card._dd_sweeper_position.isVisibleTo(card) is True
    # Back to song
    card.set_element_type("song")
    assert card._dd_sound_code.isVisibleTo(card) is True
    assert card._dd_sweeper_pick.isVisibleTo(card) is False
    card.deleteLater()


# ── Element-build integration ───────────────────────────────────────────────

def test_build_sweeper_element_with_specific_pick(qapp, db, seeded_sweepers):
    prefix, ids = seeded_sweepers
    editor = ClockEditor(db)
    editor.load_for_mode(MODE_NEW)
    editor._lib.set_element_type("sweeper")
    # Pick the first seeded sweeper (selected_sweeper_id should return its id)
    target_label = next(
        l for l in editor._lib._dd_sweeper_pick._options
        if prefix + "Bridge" in l)
    editor._lib._dd_sweeper_pick._value = target_label
    editor._lib._dd_sweeper_position._value = "Bridge at End"

    el = editor._build_element_from_filters()

    assert el["element_type"] == "sweeper"
    assert el["selection_mode"] == "specific"
    assert el["item_id"] == ids[0]   # the "Bridge" seeded sweeper
    assert el["sweeper_position"] == "Bridge at End"
    editor.deleteLater()


def test_build_sweeper_element_with_random_pick(qapp, db, seeded_sweepers):
    editor = ClockEditor(db)
    editor.load_for_mode(MODE_NEW)
    editor._lib.set_element_type("sweeper")
    # Default = "Random (any)"
    assert editor._lib.selected_sweeper_id() is None

    el = editor._build_element_from_filters()
    assert el["element_type"] == "sweeper"
    assert el["selection_mode"] == "random_from_category"
    assert el["item_id"] is None
    # Position still surfaces — defaults to "Bridge at End"
    assert el["sweeper_position"] == "Bridge at End"
    editor.deleteLater()


def test_build_song_element_does_not_emit_sweeper_fields(qapp, db):
    editor = ClockEditor(db)
    editor.load_for_mode(MODE_NEW)
    editor._lib.set_element_type("song")
    el = editor._build_element_from_filters()
    assert el["element_type"] == "song"
    assert el["selection_mode"] == "random_from_category"
    # sweeper-only fields stay None for non-sweeper types
    assert el["item_id"] is None
    assert el["sweeper_position"] is None
    editor.deleteLater()


# ── Slot persistence shape ──────────────────────────────────────────────────

def test_slot_payload_forwards_item_id_for_sweeper(qapp, db):
    editor = ClockEditor(db)
    elements = [{
        "element_type":     "sweeper",
        "slot_type_db":     "sweeper",
        "category_id":      None,
        "duration_seconds": 8,
        "selection_mode":   "specific",
        "item_id":          42,
        "sweeper_position": "Before End",
        "filter_json":      {},
    }]
    payload = editor._elements_to_slot_payload(elements)
    assert payload[0]["slot_type"] == "sweeper"
    assert payload[0]["item_id"] == 42
    assert payload[0]["sweeper_position"] == "Before End"
    assert payload[0]["selection_mode"] == "specific"
    editor.deleteLater()


def test_slot_payload_omits_item_id_for_random_sweeper(qapp, db):
    editor = ClockEditor(db)
    elements = [{
        "element_type":     "sweeper",
        "slot_type_db":     "sweeper",
        "category_id":      None,
        "duration_seconds": 8,
        "selection_mode":   "random_from_category",
        "item_id":          None,
        "sweeper_position": "Bridge at End",
        "filter_json":      {},
    }]
    payload = editor._elements_to_slot_payload(elements)
    # Random → item_id is NOT injected (would force a NULL/0 column)
    assert "item_id" not in payload[0]
    # Position still flows through
    assert payload[0]["sweeper_position"] == "Bridge at End"
    editor.deleteLater()
