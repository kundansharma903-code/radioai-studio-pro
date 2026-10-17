"""
Clock Editor pickers + what the scheduler does with them (2026-10-16).

Operator: "scheduling clock ke andar songs, sweepar, spot, jingle sab
select hone par list dikhni chahiye. apply bhi hone chahiye."

Found and fixed together:
  A. Clock Editor saves a category pick as filter_json '{"sound_code":
     ...}' and "All Songs" as '{}'. The scheduler treated any non-empty
     filter_json string as an operator pin → Rotation AI never applied
     and "All Songs" drew from the first 240 rows only.
     core.slot_filter decides what is a REAL filter.
  B. Re-saving a clock dropped specific_song_id / specific_artist_id /
     energy / vocal / fallback / pin_to_time / ref_text.
  C. Song Tracks / Artists sub-tabs were "coming soon"; now pickers.
     The scheduler's artist pin also queried a songs.artist_id column
     that does not exist — the error was swallowed and artist pins
     never worked.
  D. Spot: a READ-ONLY list of the spots due in this clock's hours
     (operator: "sirf dikhaye").
"""

from __future__ import annotations

import os

import pytest

from core.database import Database
from core.slot_filter import effective_filter, sound_code_only
from ui.clock_editor import (
    ClockEditor, MODE_EDIT, MODE_NEW, _AvailableElementsCard)


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def card(qapp):
    c = _AvailableElementsCard()
    yield c
    c.deleteLater()


@pytest.fixture
def editor(qapp, db):
    s = ClockEditor(db=db, scheduler=None)
    s.load_for_mode(MODE_NEW)
    yield s
    s.deleteLater()


@pytest.fixture
def engine(db):
    from core.scheduler.engine import SchedulerEngine
    return SchedulerEngine(db=db)


def _playable_song(db):
    for r in db._conn().execute(
            "SELECT * FROM songs WHERE is_enabled = 1 ORDER BY id"):
        if r["file_path"] and os.path.exists(r["file_path"]):
            return r
    pytest.skip("no playable song")


# ── A. what counts as a real filter ─────────────────────────────────────


@pytest.mark.parametrize("fj", [None, "", "{}", '{"sound_code": "Pool 01"}',
                                '{"era": "(All)", "category_id": 3}',
                                "not json"])
def test_category_only_or_empty_filter_is_no_filter(fj):
    assert effective_filter({"filter_json": fj}) is None


def test_real_constraints_stay_a_filter():
    spec = effective_filter(
        {"filter_json": '{"sound_code": "Pool 01", "era": "90s"}'})
    assert spec == {"sound_code": "Pool 01", "era": "90s"}


def test_sound_code_only_name():
    assert sound_code_only(
        {"filter_json": '{"sound_code": "Pool 01"}'}) == "Pool 01"
    assert sound_code_only({"filter_json": '{"era": "90s"}'}) is None


def test_clock_editor_category_slot_skips_the_filter_query(engine,
                                                           monkeypatch):
    called = []
    monkeypatch.setattr(engine, "_songs_matching_filter_json",
                        lambda fj: called.append(fj) or [])
    cat = engine._db._conn().execute(
        "SELECT category_id FROM songs WHERE is_enabled = 1 "
        "AND category_id IS NOT NULL LIMIT 1").fetchone()
    if cat is None:
        pytest.skip("no categorised songs")
    name = engine._db._conn().execute(
        "SELECT name FROM categories WHERE id = ?", [cat[0]]).fetchone()[0]
    for fj in ("{}", f'{{"sound_code": "{name}"}}'):
        item = engine._pick_song({"slot_type": "song",
                                  "category_id": int(cat[0]),
                                  "filter_json": fj})
        assert item is not None
    assert called == [], "category-only filters must use the category path"
    engine._pick_song({"slot_type": "song", "category_id": int(cat[0]),
                       "filter_json": '{"era": "90s"}'})
    assert called, "a real filter still goes through the filter query"


def test_sound_code_without_category_id_resolves_by_name(engine):
    row = engine._db._conn().execute(
        "SELECT c.id, c.name FROM categories c WHERE EXISTS (SELECT 1 "
        "FROM songs s WHERE s.category_id = c.id AND s.is_enabled = 1) "
        "LIMIT 1").fetchone()
    if row is None:
        pytest.skip("no categorised songs")
    for _ in range(5):
        item = engine._pick_song({
            "slot_type": "song", "category_id": None,
            "filter_json": f'{{"sound_code": "{row[1]}"}}'})
        cat = engine._db._conn().execute(
            "SELECT category_id FROM songs WHERE id = ?",
            [item["item_id"]]).fetchone()[0]
        assert cat == row[0]


# ── C. artist pin really airs that artist ──────────────────────────────


def test_artist_pin_picks_that_artist(engine, db):
    song = _playable_song(db)
    aid = db.get_or_create_artist_id(song["artist"])
    assert aid and db.get_or_create_artist_id(song["artist"]) == aid, \
        "get-or-create must not duplicate"
    for _ in range(5):
        item = engine._pick_song({"slot_type": "song",
                                  "specific_artist_id": aid})
        assert item["artist"].lower() == song["artist"].lower()


def test_song_pin_picks_that_song(engine, db):
    song = _playable_song(db)
    item = engine._pick_song({"slot_type": "song",
                              "specific_song_id": int(song["id"])})
    assert item["item_id"] == int(song["id"])


# ── B. round-trip keeps settings the screen does not edit ──────────────


def test_load_save_round_trip_keeps_untouched_fields():
    row = {"slot_type": "song", "category_id": 3, "filter_json": None,
           "minute_position": 0, "duration_seconds": 200,
           "selection_mode": "random_from_category", "item_id": 0,
           "sweeper_position": None, "ref_text": "Morning VT",
           "specific_song_id": 55, "specific_artist_id": None,
           "energy_pref": "High", "vocal_pref": "Female",
           "priority_pref": "Normal", "separation_override": 90,
           "fallback_category_id": 4, "pin_to_time": 1,
           "cat_name": "X", "cat_color": None}
    els = ClockEditor._slots_to_elements([row])
    out = ClockEditor._elements_to_slot_payload(els)[0]
    for k in ("specific_song_id", "energy_pref", "vocal_pref",
              "separation_override", "fallback_category_id",
              "pin_to_time", "ref_text"):
        assert out[k] == row[k], k
    assert "specific_artist_id" not in out      # NULL stays NULL


# ── C. Song Tracks / Artists pickers ───────────────────────────────────


def test_tracks_and_artists_are_lists_not_placeholders(editor):
    lib = editor._lib
    lib._on_type_clicked("song")
    lib._on_subtab_clicked("tracks")
    assert lib._tracks_list.isVisibleTo(lib)
    assert lib._tracks_list.row_count() > 0
    lib._on_subtab_clicked("artists")
    assert lib._artists_list.isVisibleTo(lib)
    assert not lib._tracks_list.isVisibleTo(lib)
    assert lib._artists_list.row_count() > 0


def test_track_search_filters_the_list(editor, db):
    song = _playable_song(db)
    lib = editor._lib
    lib._on_type_clicked("song"); lib._on_subtab_clicked("tracks")
    lib._tracks_list._edit.setText(str(song["title"]))
    keys = [lib._tracks_list._list.item(i).data(0x0100)
            for i in range(lib._tracks_list._list.count())]
    assert int(song["id"]) in keys
    assert len(keys) < lib._tracks_list.row_count() or len(keys) == 1


def test_pinned_track_is_added_and_airs(editor, db, engine):
    song = _playable_song(db)
    lib = editor._lib
    lib._on_type_clicked("song"); lib._on_subtab_clicked("tracks")
    lib._tracks_list.select_key(int(song["id"]))
    editor._refresh_filter_results()
    assert editor._results._count == 1
    editor._on_add()
    el = editor._elements[-1]
    assert el["specific_song_id"] == int(song["id"])
    assert el["filter_json"] == {}
    assert song["title"] in editor._content_rows()[-1]["sub"]
    slot = ClockEditor._elements_to_slot_payload([el])[0]
    assert engine._pick_song(slot)["item_id"] == int(song["id"])


def test_pinned_artist_is_added_and_airs(editor, db, engine):
    song = _playable_song(db)
    lib = editor._lib
    lib._on_type_clicked("song"); lib._on_subtab_clicked("artists")
    lib._artists_list.select_key(str(song["artist"]).strip())
    editor._refresh_filter_results()
    assert editor._results._count >= 1
    editor._on_add()
    el = editor._elements[-1]
    assert el.get("specific_artist_id")
    assert "Artist:" in editor._content_rows()[-1]["sub"]
    slot = ClockEditor._elements_to_slot_payload([el])[0]
    item = engine._pick_song(slot)
    assert item["artist"].lower() == str(song["artist"]).lower()


def test_no_track_selected_disables_add(editor):
    lib = editor._lib
    lib._on_type_clicked("song"); lib._on_subtab_clicked("tracks")
    lib._tracks_list.clear_selection()
    editor._refresh_filter_results()
    assert editor._results._count == 0
    assert editor._actions._add._enabled is False
    lib._tracks_list._list.setCurrentRow(0)
    lib._tracks_list._list.item(0).setSelected(True)
    editor._refresh_filter_results()
    assert editor._actions._add._enabled is True


def test_song_subtabs_only_for_songs(card):
    card._on_type_clicked("song"); card._on_subtab_clicked("tracks")
    card._on_type_clicked("jingle")
    assert card.subtab() == "filters"
    assert not card._sub_tracks.isVisibleTo(card)
    assert not card._tracks_list.isVisibleTo(card)
    assert card._dd_jingle_pick.isVisibleTo(card)


# ── D. Spot list (view only) ───────────────────────────────────────────


def test_spot_list_shows_spots_due_in_the_clocks_hours(qapp, db):
    hit = None
    for dow in range(7):
        breaks = db.get_active_breaks_for_day(dow)
        for b in breaks:
            hr = int(str(b["break_time"]).split(":")[0])
            cell = db._conn().execute(
                "SELECT clock_id FROM auto_schedule WHERE day_of_week = ? "
                "AND hour_start = ?", [dow, hr]).fetchone()
            if cell is not None:
                hit = (int(cell[0]), b["campaign_name"])
                break
        if hit:
            break
    if hit is None:
        pytest.skip("no scheduled spot inside a grid-assigned hour")
    ed = ClockEditor(db=db, scheduler=None)
    try:
        ed.load_for_mode(MODE_EDIT, hit[0])
        ed._lib._on_type_clicked("spot")
        assert ed._lib._spot_list.isVisibleTo(ed._lib)
        labels = [ed._lib._spot_list._list.item(i).text()
                  for i in range(ed._lib._spot_list._list.count())]
        assert any(hit[1] in t for t in labels)
        assert ed._lib.spot_count() == len(labels)
        assert not ed._lib._spot_list._list.selectionMode().value, \
            "view-only list"
    finally:
        ed.deleteLater()


def test_spot_list_for_new_clock_explains_itself(editor):
    editor._lib._on_type_clicked("spot")
    assert editor._lib.spot_count() == 0
    assert editor._lib._spot_list._list.count() == 1
    assert "assign" in editor._lib._spot_list._list.item(0).text().lower()
