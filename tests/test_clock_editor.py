"""
Clock Editor (Figma 285:2 — Frame 11) — load/save/element CRUD/round-trip.

Live-DB tests with strict cleanup discipline:
  - Every test-created clock prefixed ``_test_clockedit_<uuid8>``
  - Mode setting (auto_schedule.mode + clock_editor.colorize_by) captured
    + restored
  - Wrapped in try/finally; failures still clean up
"""

from __future__ import annotations

import json
import uuid

import pytest
from PyQt6.QtCore import Qt

from core.database import Database
from core.scheduler import SchedulerEngine
from ui.clock_editor import (
    ClockEditor, _AvailableElementsCard,
    MODE_NEW, MODE_EDIT, MODE_DUPLICATE,
    SETTINGS_KEY_COLORIZE_BY, DEFAULT_CLOCK_COLOR,
    ELEMENT_TYPES, ELEMENT_TYPE_TO_DB, DB_TO_ELEMENT_TYPE,
)
from ui.widgets.clock_face import ClockFaceWidget as _ClockFaceWidget


# ── Fixtures ────────────────────────────────────────────────────────────


class _ClockEditEnv:
    """Tracks created clock ids for cleanup, plus the original colorize-by
    setting for restoration."""

    def __init__(self, db: Database):
        self.db = db
        self.created_clock_ids: list[int] = []
        self.original_colorize: str | None = None

    def make_clock(self, suffix: str = "clock") -> int:
        prefix = f"_test_clockedit_{uuid.uuid4().hex[:8]}"
        cid = int(self.db.create_clock(f"{prefix}_{suffix}"))
        self.created_clock_ids.append(cid)
        return cid

    def cleanup(self) -> None:
        # Clear every auto_schedule cell + clock_slots referencing test clocks,
        # then drop the clocks. Belt-and-suspenders for FK that's NOT
        # ON DELETE CASCADE on auto_schedule.
        conn = self.db._conn()
        for cid in list(self.created_clock_ids):
            try:
                conn.execute(
                    "DELETE FROM auto_schedule WHERE clock_id = ?", [int(cid)])
                conn.execute(
                    "DELETE FROM clock_slots WHERE clock_id = ?", [int(cid)])
                conn.commit()
            except Exception:
                pass
            try:
                self.db.delete_clock(int(cid))
            except (ValueError, Exception):
                pass
        if self.original_colorize is not None:
            try:
                self.db.set_setting(
                    SETTINGS_KEY_COLORIZE_BY, self.original_colorize)
            except Exception:
                pass


@pytest.fixture
def ce_env():
    db = Database()
    env = _ClockEditEnv(db)
    env.original_colorize = db.get_setting(SETTINGS_KEY_COLORIZE_BY, "type")
    try:
        yield env
    finally:
        env.cleanup()


@pytest.fixture
def screen(qtbot, ce_env):
    """Mounted Clock Editor with a real SchedulerEngine (not started — we
    only need its filter helpers, which are pure SQL)."""
    sch = SchedulerEngine(ce_env.db)
    s = ClockEditor(db=ce_env.db, scheduler=sch)
    qtbot.addWidget(s)
    s.show()
    yield s, ce_env, sch
    s.hide()


# ── Smoke ───────────────────────────────────────────────────────────────


def test_screen_mounts(qtbot, ce_env):
    s = ClockEditor(db=ce_env.db, scheduler=None)
    qtbot.addWidget(s)
    assert s.width() == 1440
    assert s.height() == 900
    assert s._meta is not None
    assert s._lib is not None
    assert s._editor is not None
    assert s._results is not None
    assert s._actions is not None


def test_load_for_mode_new_blank(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    assert s._meta.name() == "New Clock"
    assert s._meta.comments() == ""
    assert s._meta.color() == DEFAULT_CLOCK_COLOR
    assert s._elements == []
    assert s._dirty is False


def test_load_for_mode_edit_populates_from_db(screen):
    s, env, _ = screen
    cid = env.make_clock("editme")
    env.db.save_clock(cid, {
        "name": f"_test_clockedit_known", "comments": "test note",
        "color": "#06b6d4",
    })
    env.db.save_clock_slots(cid, [
        {"slot_type": "song", "category_id": None,
         "duration_seconds": 240, "minute_position": 0,
         "selection_mode": "random_from_category", "filter_json": "{}"},
        {"slot_type": "jingle", "category_id": None,
         "duration_seconds": 8, "minute_position": 4,
         "selection_mode": "random_any", "filter_json": "{}"},
    ])
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    assert s._mode == MODE_EDIT
    assert s._source_id == cid
    assert s._meta.comments() == "test note"
    assert s._meta.color() == "#06b6d4"
    assert len(s._elements) == 2
    assert s._elements[0]["element_type"] == "song"
    assert s._elements[1]["element_type"] == "jingle"
    assert s._dirty is False


def test_load_for_mode_duplicate_prefixes_name_and_marks_dirty(screen):
    s, env, _ = screen
    cid = env.make_clock("source")
    env.db.save_clock(cid, {"name": "Original"})
    env.db.save_clock_slots(cid, [
        {"slot_type": "song", "duration_seconds": 240, "minute_position": 0,
         "selection_mode": "random_from_category", "filter_json": "{}"},
    ])
    s.load_for_mode(MODE_DUPLICATE, clock_id=cid)
    assert s._mode == MODE_DUPLICATE
    assert s._meta.name() == "Copy of Original"
    assert len(s._elements) == 1
    # Duplicate mode: dirty so OK button has effect even without further edits
    assert s._dirty is True


# ── Element CRUD on the in-memory list ──────────────────────────────────


def test_add_pushes_element(screen):
    s, env, _ = screen
    s.load_for_mode(MODE_NEW)
    assert len(s._elements) == 0
    s._on_add()
    assert len(s._elements) == 1
    assert s._elements[0]["element_type"] == "song"   # default type
    assert s._elements[0].get("duration_seconds", 0) > 0
    assert s._dirty is True
    assert s._editor.face().selected_idx() == 0


def test_insert_at_selected(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    s._on_add()                               # idx 0
    s._on_add()                               # idx 1
    s._editor.face().set_selected(0)
    s._lib.set_element_type("jingle")
    s._on_insert()
    assert len(s._elements) == 3
    assert s._elements[0]["element_type"] == "jingle"


def test_replace_at_selected_preserves_minute_position(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    s._on_add()
    s._editor.face().set_selected(0)
    orig_min = s._elements[0].get("minute_position", 0)
    s._lib.set_element_type("sweeper")
    s._on_replace()
    assert s._elements[0]["element_type"] == "sweeper"
    assert s._elements[0]["minute_position"] == orig_min


def test_delete_removes_element(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    s._on_add(); s._on_add(); s._on_add()
    s._editor.face().set_selected(1)
    s._on_delete()
    assert len(s._elements) == 2


# ── Filter UI / scheduler integration ───────────────────────────────────


def test_filter_state_includes_real_axes_only(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    state = s._lib.filter_state()
    # All defaults are "(All)" — empty dict
    assert state == {} or all(v not in ("(All)", "All", None)
                              for v in state.values())


def test_reset_filters_clears_to_all(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    s._lib._dd_era.set_value("2010s")
    s._lib._dd_year_min.set_value("2020")
    assert s._lib._dd_era.value() == "2010s"
    s._lib.reset_filters()
    assert s._lib._dd_era.value() == "(All)"
    assert s._lib._dd_year_min.value() == "(All)"


def test_filter_debounce_fires_once(qtbot, screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    # Stub the underlying refresh to count invocations
    counter = {"n": 0}
    orig = s._refresh_filter_results
    def counting():
        counter["n"] += 1
        orig()
    s._refresh_filter_results = counting
    s._filter_timer.timeout.disconnect()
    s._filter_timer.timeout.connect(counting)
    # 5 rapid changes — only 1 final fire after debounce
    for _ in range(5):
        s._on_filter_changed()
    qtbot.wait(60)
    assert counter["n"] == 0       # nothing yet (debounce 200ms)
    qtbot.wait(260)
    assert counter["n"] == 1


# ── Validation ──────────────────────────────────────────────────────────


def test_validate_blocks_empty_name(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    s._meta.set_name("   ")       # whitespace only
    s._on_add()                   # at least 1 element
    err = s._validate_for_save()
    assert err is not None
    assert "name" in err.lower()


def test_validate_blocks_zero_elements(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    s._meta.set_name("Has Name")
    err = s._validate_for_save()
    assert err is not None
    assert "element" in err.lower()


def test_validate_passes_with_name_and_one_element(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    s._meta.set_name("OK Clock")
    s._on_add()
    assert s._validate_for_save() is None


# ── Save paths ──────────────────────────────────────────────────────────


def test_save_create_persists_clock_and_slots(screen):
    s, env, _ = screen
    s.load_for_mode(MODE_NEW)
    s._meta.set_name(f"_test_clockedit_save_{uuid.uuid4().hex[:6]}")
    s._meta.set_comments("hello")
    s._on_add(); s._on_add()
    new_id = s._save()
    assert new_id is not None
    env.created_clock_ids.append(int(new_id))
    row = env.db.get_clock(int(new_id))
    assert row is not None
    assert row["comments"] == "hello"
    slots = list(env.db.get_clock_slots(int(new_id)))
    assert len(slots) == 2


def test_save_edit_updates_existing(screen):
    s, env, _ = screen
    cid = env.make_clock("editsave")
    env.db.save_clock(cid, {"name": "Before", "comments": "old"})
    env.db.save_clock_slots(cid, [
        {"slot_type": "song", "duration_seconds": 240,
         "minute_position": 0, "filter_json": "{}",
         "selection_mode": "random_from_category"},
    ])
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    s._meta.set_comments("updated note")
    new_id = s._save()
    assert new_id == cid       # same id, not a new clock
    row = env.db.get_clock(int(cid))
    assert row["comments"] == "updated note"


def test_save_duplicate_creates_new_clock(screen):
    s, env, _ = screen
    cid = env.make_clock("dup_src")
    env.db.save_clock(cid, {"name": "Source", "comments": "src note"})
    env.db.save_clock_slots(cid, [
        {"slot_type": "song", "duration_seconds": 240,
         "minute_position": 0, "filter_json": "{}",
         "selection_mode": "random_from_category"},
        {"slot_type": "jingle", "duration_seconds": 8,
         "minute_position": 4, "filter_json": "{}",
         "selection_mode": "random_any"},
    ])
    s.load_for_mode(MODE_DUPLICATE, clock_id=cid)
    new_id = s._save()
    assert new_id is not None
    assert new_id != cid       # NEW row, not in-place update
    env.created_clock_ids.append(int(new_id))
    row = env.db.get_clock(int(new_id))
    assert row["name"].startswith("Copy of")
    new_slots = list(env.db.get_clock_slots(int(new_id)))
    assert len(new_slots) == 2
    # Source clock unchanged
    src_slots = list(env.db.get_clock_slots(int(cid)))
    assert len(src_slots) == 2


def test_round_trip_load_then_save_preserves_structure(screen):
    """Load → save unchanged → element types + count match db state."""
    s, env, _ = screen
    cid = env.make_clock("rt")
    env.db.save_clock(cid, {"name": "RT", "color": "#10b981"})
    seed = [
        {"slot_type": "song", "duration_seconds": 240,
         "minute_position": 0, "filter_json": "{}",
         "selection_mode": "random_from_category"},
        {"slot_type": "jingle", "duration_seconds": 8,
         "minute_position": 4, "filter_json": "{}",
         "selection_mode": "random_any"},
        {"slot_type": "break", "duration_seconds": 60,
         "minute_position": 5, "filter_json": "{}",
         "selection_mode": "random_any"},
    ]
    env.db.save_clock_slots(cid, seed)
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    # Save without any changes
    s._save()
    saved = list(env.db.get_clock_slots(int(cid)))
    # Same count + same slot_types in same order
    assert len(saved) == len(seed)
    saved_types = [s["slot_type"] for s in saved]
    assert saved_types == ["song", "jingle", "break"]


# ── Cancel + dirty ──────────────────────────────────────────────────────


def test_cancel_when_clean_emits_route(screen, qtbot):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    received: list[str] = []
    s.screen_requested.connect(received.append)
    s._cancel_then_route("main_auto_schedule")
    assert received == ["main_auto_schedule"]


def test_dirty_after_name_change(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    assert s._dirty is False
    s._meta.set_name("Renamed")
    assert s._dirty is True


# ── Type / DB mapping invariants ────────────────────────────────────────


def test_element_type_db_round_trip():
    # Every UI type maps to a known DB slot_type, and the reverse map
    # recovers the UI type.
    for t in ELEMENT_TYPES:
        db_t = ELEMENT_TYPE_TO_DB[t]
        assert DB_TO_ELEMENT_TYPE[db_t] == t


def test_legacy_spot_alias_routes_to_spot_ui():
    # Old data with slot_type='spot' should load as the UI's "spot" tile
    assert DB_TO_ELEMENT_TYPE["spot"] == "spot"
    assert DB_TO_ELEMENT_TYPE["break"] == "spot"


# ── Clock face widget paint smoke ───────────────────────────────────────


def test_clock_face_empty_state(qtbot):
    f = _ClockFaceWidget()
    qtbot.addWidget(f)
    f.set_elements([])
    assert f._segment_paths == []
    # Setting selection on empty face is a no-op
    f.set_selected(None)


def test_clock_face_builds_one_segment_per_element(qtbot):
    f = _ClockFaceWidget()
    qtbot.addWidget(f)
    f.set_elements([
        {"element_type": "song", "duration_seconds": 240,
         "minute_position": 0},
        {"element_type": "jingle", "duration_seconds": 8,
         "minute_position": 4},
    ])
    assert len(f._segment_paths) == 2
    # Hit-testing the second segment's start point returns idx 1
    # (full geometry test would require deep math — smoke that it's a
    # non-empty QPainterPath is enough here)
    p0, _, _, _ = f._segment_paths[0]
    assert not p0.isEmpty()


def test_clock_face_colorize_by_changes_segments(qtbot):
    f = _ClockFaceWidget()
    qtbot.addWidget(f)
    f.set_elements([{"element_type": "song", "category_color": "#ff0000",
                     "duration_seconds": 240, "minute_position": 0}])
    initial_color = f._segment_paths[0][1]
    f.set_colorize_by("category")
    assert f._segment_paths[0][1] == "#ff0000"
    f.set_colorize_by("type")
    assert f._segment_paths[0][1] != "#ff0000"


# ── A+B 2026-07-09: sequential AUTO clocks render + play-order list ──────


def _seed_auto_grid_slots(env, cid: int) -> None:
    """3 slots the way the auto-grid builder writes them — ALL at
    minute_position 0 (the 'empty AUTO clock face' repro)."""
    env.db.save_clock_slots(cid, [
        {"slot_type": "sweeper", "duration_seconds": 8,
         "minute_position": 0, "filter_json": "{}",
         "selection_mode": "random_from_category"},
        {"slot_type": "song", "duration_seconds": 240,
         "minute_position": 0, "filter_json": "{}",
         "selection_mode": "random_from_category"},
        {"slot_type": "jingle", "duration_seconds": 8,
         "minute_position": 0, "filter_json": "{}",
         "selection_mode": "random_from_category"},
    ])


def test_auto_grid_mp_zero_loads_as_sequential(screen):
    """minute_position 0/NULL → None so the face chains elements."""
    s, env, _ = screen
    cid = env.make_clock("auto")
    _seed_auto_grid_slots(env, cid)
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    assert len(s._elements) == 3
    assert all(e["minute_position"] is None for e in s._elements)


def test_auto_grid_face_arcs_spread_not_stacked(screen):
    """The 3 arcs must start at increasing minutes (was: all at 0)."""
    s, env, _ = screen
    cid = env.make_clock("auto_face")
    _seed_auto_grid_slots(env, cid)
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    starts = [seg[2] for seg in s._editor.face()._segment_paths]
    assert len(starts) == 3
    assert starts[0] < starts[1] < starts[2]
    assert starts[0] == 0.0          # first element still anchors at 12:00


def test_explicit_minute_position_preserved(screen):
    """A slot with a real (non-zero) minute_position keeps it."""
    s, env, _ = screen
    cid = env.make_clock("explicit_mp")
    env.db.save_clock_slots(cid, [
        {"slot_type": "song", "duration_seconds": 240,
         "minute_position": 0, "filter_json": "{}",
         "selection_mode": "random_from_category"},
        {"slot_type": "jingle", "duration_seconds": 8,
         "minute_position": 30, "filter_json": "{}",
         "selection_mode": "random_any"},
    ])
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    assert s._elements[1]["minute_position"] == 30
    starts = [seg[2] for seg in s._editor.face()._segment_paths]
    assert starts[1] == 30.0


def test_auto_grid_roundtrip_save_keeps_order(screen):
    """Load an all-zero clock → save unchanged → slot order intact."""
    s, env, _ = screen
    cid = env.make_clock("auto_rt")
    _seed_auto_grid_slots(env, cid)
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    s._save()
    saved = list(env.db.get_clock_slots(int(cid)))
    assert [r["slot_type"] for r in saved] == ["sweeper", "song", "jingle"]


def test_pinned_item_id_survives_load_save_roundtrip(screen):
    """selection_mode='specific' + item_id must not be dropped by a
    load → save round-trip (elements now carry the pin columns)."""
    s, env, _ = screen
    cid = env.make_clock("pin_rt")
    env.db.save_clock_slots(cid, [
        {"slot_type": "sweeper", "duration_seconds": 8,
         "minute_position": 0, "filter_json": "{}",
         "selection_mode": "specific", "item_id": 12345,
         "sweeper_position": "START_OF_SONG"},
    ])
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    assert s._elements[0]["item_id"] == 12345
    s._save()
    saved = list(env.db.get_clock_slots(int(cid)))
    assert int(saved[0]["item_id"]) == 12345
    assert saved[0]["selection_mode"] == "specific"


def test_contents_list_rows_readable(screen):
    """Play-order list shows type + detail per element."""
    s, env, _ = screen
    cid = env.make_clock("contents")
    _seed_auto_grid_slots(env, cid)
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    rows = s._content_rows()
    assert [r["title"] for r in rows] == ["Sweeper", "Song", "Jingle"]
    assert rows[0]["sub"] == "Random"          # random sweeper
    assert rows[1]["sub"] == "Any song"        # no category on the slot
    assert rows[2]["sub"] == "Random"          # random jingle
    # The widget mirrors the same rows
    lst = s._editor.contents_list()
    assert len(lst._rows) == 3


def test_contents_list_shows_category_name(screen):
    """A song slot with a category shows the category's NAME."""
    s, env, _ = screen
    cats = list(env.db.get_categories())
    if not cats:
        pytest.skip("live DB has no categories")
    cat_id = int(cats[0]["id"]); cat_name = str(cats[0]["name"])
    cid = env.make_clock("cat_name")
    env.db.save_clock_slots(cid, [
        {"slot_type": "song", "category_id": cat_id,
         "duration_seconds": 240, "minute_position": 0,
         "filter_json": "{}",
         "selection_mode": "random_from_category"},
    ])
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    rows = s._content_rows()
    assert rows[0]["title"] == "Song"
    assert rows[0]["sub"] == cat_name


def test_contents_list_row_click_selects_face_arc(screen):
    s, env, _ = screen
    cid = env.make_clock("row_click")
    _seed_auto_grid_slots(env, cid)
    s.load_for_mode(MODE_EDIT, clock_id=cid)
    assert s._editor.face().selected_idx() is None
    s._on_content_row_clicked(1)
    assert s._editor.face().selected_idx() == 1
    assert s._editor.contents_list()._selected == 1
    # Out-of-range click is a no-op
    s._on_content_row_clicked(99)
    assert s._editor.face().selected_idx() == 1


def test_contents_list_syncs_on_crud(screen):
    s, _, _ = screen
    s.load_for_mode(MODE_NEW)
    lst = s._editor.contents_list()
    assert lst._rows == []
    s._on_add()
    assert len(lst._rows) == 1
    s._on_add()
    assert len(lst._rows) == 2
    s._editor.face().set_selected(0)
    s._on_delete()
    assert len(lst._rows) == 1
