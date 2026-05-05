"""
Phase F-Final Subphase 2 — picker function tests.

Each picker returns the standardized item shape:
  {item_type, item_id, file_path, title, artist, duration_ms}

Tests cover both the dispatch path (pick_next_item) and individual
pickers in isolation. Cleanup is per-test — auto_schedule + temporary
clocks are rolled back at the end of each test.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine


def _now_at(weekday: int, hour: int) -> datetime:
    base = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
    delta = (weekday - base.weekday()) % 7
    return base + timedelta(days=delta)


def _build_clock(db: Database, slots_spec: list[dict],
                 name: str = "Picker Test Clock") -> int:
    cid = db.create_clock(name)
    db.save_clock_slots(cid, slots_spec)
    return cid


@pytest.fixture
def seeded_db(qtbot):
    """Database with rotation seed + at least one song. Test classes
    that need a specific clock create their own and clean up."""
    db = Database()
    db.seed_rotation_test_data()
    if not list(db.get_songs(limit=1)):
        pytest.skip("no songs in DB to drive picker tests")
    return db


# ── Jingle picker ──────────────────────────────────────────────────────


def test_pick_jingle_random_any(seeded_db):
    """Random_any (no category, no specific) returns the first jingle
    pad with a populated file_path."""
    sch = SchedulerEngine(db=seeded_db)
    pads = list(seeded_db.get_jingle_pads_active())
    if not pads:
        pytest.skip("no jingle pads with file_path in DB")
    slot = {"slot_type": "Jingle", "selection_mode": "random_any",
            "item_id": 0, "category_id": None}
    result = sch._pick_jingle(slot)
    assert result is not None
    assert result["item_type"] == "jingle"
    assert result["item_id"] is not None


def test_pick_jingle_specific_returns_that_pad(seeded_db):
    """selection_mode='specific' resolves to the row with item_id."""
    sch = SchedulerEngine(db=seeded_db)
    pads = list(seeded_db.get_jingle_pads_active())
    if not pads:
        pytest.skip("no jingle pads in DB")
    target = pads[0]
    slot = {"slot_type": "Jingle", "selection_mode": "specific",
            "item_id": int(target["id"]), "category_id": None}
    result = sch._pick_jingle(slot)
    assert result is not None
    assert result["item_id"] == int(target["id"])


# ── Sweeper picker ─────────────────────────────────────────────────────


def test_pick_sweeper_random(seeded_db):
    sch = SchedulerEngine(db=seeded_db)
    slot = {"slot_type": "Sweeper", "selection_mode": "random_any",
            "item_id": 0, "category_id": None}
    result = sch._pick_sweeper(slot)
    assert result is not None
    assert result["item_type"] == "sweeper"


# ── Station ID picker ─────────────────────────────────────────────────


def test_pick_station_id(seeded_db):
    sch = SchedulerEngine(db=seeded_db)
    slot = {"slot_type": "Station ID", "selection_mode": "random_any",
            "item_id": 0, "category_id": None}
    result = sch._pick_station_id(slot)
    assert result is not None
    assert result["item_type"] == "station_id"


# ── Voice track picker ────────────────────────────────────────────────


def test_pick_voice_track_in_window(seeded_db):
    """Seeded voice tracks have NULL valid_from/to → always valid."""
    sch = SchedulerEngine(db=seeded_db)
    slot = {"slot_type": "Voice Track", "selection_mode": "random_any",
            "item_id": 0, "category_id": None}
    result = sch._pick_voice_track(slot)
    assert result is not None
    assert result["item_type"] == "voice_track"


def test_pick_voice_track_out_of_window_returns_none(seeded_db):
    """Insert a voice track that's only valid in the past, then deactivate
    the seeded ones. Picker should return None."""
    db = seeded_db
    conn = db._conn()
    conn.execute("UPDATE voice_tracks SET is_active = 0")
    past = "1990-01-01"
    conn.execute(
        "INSERT INTO voice_tracks (name, file_path, duration_ms, "
        "valid_from, valid_to, is_active) VALUES "
        "('past only', '', 30000, ?, ?, 1)", [past, past])
    conn.commit()
    sch = SchedulerEngine(db=db)
    slot = {"slot_type": "Voice Track", "selection_mode": "random_any",
            "item_id": 0, "category_id": None}
    result = sch._pick_voice_track(slot)
    assert result is None
    # Restore: reactivate the seeded ones, drop the past-only one
    conn.execute("UPDATE voice_tracks SET is_active = 1 "
                 "WHERE valid_from IS NULL")
    conn.execute("DELETE FROM voice_tracks WHERE valid_from = ?", [past])
    conn.commit()


# ── Break picker ──────────────────────────────────────────────────────


def test_pick_break_returns_none_with_no_campaigns(seeded_db):
    """No campaign in current hour → picker returns None (skip slot)."""
    sch = SchedulerEngine(db=seeded_db)
    slot = {"slot_type": "Break"}
    # Use a wildly-future hour that no campaign should target.
    result = sch._pick_break(slot, _now_at(0, 4))
    # Result is None UNLESS the test DB happens to have a campaign at
    # Mon 04:00 — accept either, but if not None it must be a spot dict.
    assert result is None or result.get("item_type") == "spot"


# ── Separation rules ──────────────────────────────────────────────────


def test_separation_helpers_return_sets(seeded_db):
    """Recent-artist and recent-song-id helpers return sets (possibly
    empty). They never raise."""
    sch = SchedulerEngine(db=seeded_db)
    artists = sch._recent_artists(60)
    songs = sch._recent_song_ids(240)
    assert isinstance(artists, set)
    assert isinstance(songs, set)


def test_separation_skips_recent_song(seeded_db):
    """Log a song play with played_at = now, then call _pick_song with
    that song's category — picker should still return SOMETHING (either
    a different song or fall back if it's the only candidate). The
    function shouldn't crash and the returned dict has the standard
    item shape."""
    db = seeded_db
    sch = SchedulerEngine(db=db)
    songs = list(db.get_songs(limit=5))
    if not songs:
        pytest.skip("no songs in DB")
    target = songs[0]
    db.log_play(entry_type="song", song_id=int(target["id"]),
                duration_ms=180000, deck="A", was_manual=0,
                clock_id=None, slot_idx=None)
    slot = {"slot_type": "Song", "selection_mode": "random_from_category",
            "category_id": target["category_id"] if "category_id" in target.keys() else None,
            "energy_pref": "Any", "vocal_pref": "Any",
            "item_id": 0, "fallback_category_id": None}
    result = sch._pick_song(slot)
    assert result is not None
    assert result["item_type"] == "song"
    assert "item_id" in result and result["item_id"] is not None


# ── Force-clocks override + dispatch ──────────────────────────────────


def test_force_clock_overrides_auto_schedule(seeded_db):
    """An active force_clock for today × current hour wins over
    auto_schedule. Cleanup deletes the override row."""
    db = seeded_db
    sch = SchedulerEngine(db=db)

    # Build two clocks: one from auto_schedule, one from force_clocks.
    cid_auto = _build_clock(db, [
        {"slot_type": "Song", "category_id": None, "energy_pref": "Any",
         "vocal_pref": "Any", "priority_pref": "Normal",
         "is_break": 0, "item_id": 0,
         "selection_mode": "random_any"},
    ], name="Auto-driven")
    cid_force = _build_clock(db, [
        {"slot_type": "Song", "category_id": None, "energy_pref": "Any",
         "vocal_pref": "Any", "priority_pref": "Normal",
         "is_break": 0, "item_id": 0,
         "selection_mode": "random_any"},
    ], name="Force-driven")

    # Set up: auto_schedule for (Mon, 13) → cid_auto
    db.set_auto_schedule_cell(0, 13, cid_auto)
    when = _now_at(0, 13)
    # Force override for that exact date
    fc_id = db.add_force_clock(
        "Test Override", cid_force,
        override_date=when.strftime("%Y-%m-%d"),
        time_start="00:00", time_end="23:59")

    try:
        result = sch.pick_next_item(when)
        assert result is not None
        assert result["clock_id"] == cid_force, \
            f"force_clock should win, got {result['clock_id']}"
    finally:
        db.delete_force_clock(fc_id)
        db.clear_auto_schedule_cell(0, 13)
        # Best-effort cleanup of the test clocks (last-clock guard handles None)
        for c in (cid_auto, cid_force):
            db._conn().execute("DELETE FROM broadcast_log WHERE clock_id = ?", [c])
            db._conn().commit()
            try:
                db.delete_clock(c)
            except (ValueError, Exception):
                pass


# ── Mixed-slot dispatch end-to-end ────────────────────────────────────


def test_pick_next_item_dispatches_through_mixed_slots(seeded_db):
    """A clock with [Song, Jingle, Sweeper] dispatches to each picker on
    successive calls; cursor advances correctly."""
    db = seeded_db
    sch = SchedulerEngine(db=db)
    cid = _build_clock(db, [
        {"slot_type": "Song",    "selection_mode": "random_any",
         "category_id": None, "energy_pref": "Any", "vocal_pref": "Any",
         "priority_pref": "Normal", "is_break": 0, "item_id": 0},
        {"slot_type": "Jingle",  "selection_mode": "random_any",
         "category_id": None, "energy_pref": "Any", "vocal_pref": "Any",
         "priority_pref": "Normal", "is_break": 0, "item_id": 0},
        {"slot_type": "Sweeper", "selection_mode": "random_any",
         "category_id": None, "energy_pref": "Any", "vocal_pref": "Any",
         "priority_pref": "Normal", "is_break": 0, "item_id": 0},
    ], name="Mixed Slots")
    db.set_auto_schedule_cell(0, 14, cid)
    when = _now_at(0, 14)
    try:
        a = sch.pick_next_item(when)
        b = sch.pick_next_item(when)
        c = sch.pick_next_item(when)
        types = [x["item_type"] for x in (a, b, c) if x]
        assert "song" in types
        # At least one of jingle / sweeper appears (depending on which
        # rotation tables are non-empty in this DB).
        assert any(t in ("jingle", "sweeper") for t in types)
    finally:
        db.clear_auto_schedule_cell(0, 14)
        db._conn().execute("DELETE FROM broadcast_log WHERE clock_id = ?", [cid])
        db._conn().commit()
        try:
            db.delete_clock(cid)
        except (ValueError, Exception):
            pass
