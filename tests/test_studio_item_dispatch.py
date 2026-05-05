"""
Phase F-Final S3 — Studio item-type dispatch.

Studio's _compute_next_song now consumes scheduler.pick_next_item which
can return any rotation type. These tests verify the helper functions
that translate the item dict into Studio's display + log_play shape.

Full end-to-end audio playback is verified manually in NIGHT_LOG_4.md.
"""

from __future__ import annotations

from core.database import Database
from ui.studio import Studio


def test_tags_for_item_type_covers_full_set():
    for t, expected_label in [
        ("jingle",      "Jingle"),
        ("sweeper",     "Sweeper"),
        ("station_id",  "Station ID"),
        ("voice_track", "Voice Track"),
        ("spot",        "Ad Break"),
    ]:
        tags = Studio._tags_for_item_type(t)
        assert isinstance(tags, list)
        assert any(expected_label in tag for tag in tags), \
            f"item_type {t!r} missing tag {expected_label!r}"


def test_tags_for_song_is_empty_so_derive_uses_category_energy():
    """song-typed items don't pre-populate tags — _derive_tags falls
    through to the category + energy path."""
    assert Studio._tags_for_item_type("song") == []


def test_derive_tags_prefers_existing_tags():
    song = {"tags": ["Custom Badge"], "category": "Hot Currents"}
    assert Studio._derive_tags(song) == ["Custom Badge"]


def test_derive_tags_falls_back_to_category_energy():
    song = {"category": "Hot Currents", "energy": "High"}
    tags = Studio._derive_tags(song)
    assert "Hot Currents" in tags
    assert "High Energy" in tags


def test_log_play_records_non_song_item_type(qtbot):
    """log_play is now item_type-agnostic. A jingle entry round-trips
    with entry_type='jingle' and song_id=NULL."""
    db = Database()
    db.log_play(
        entry_type="jingle",
        song_id=None,
        duration_ms=12000,
        deck="A",
        was_manual=0,
        clock_id=None,
        slot_idx=3,
    )
    row = db._conn().execute(
        "SELECT entry_type, song_id, slot_idx FROM broadcast_log "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["entry_type"] == "jingle"
    assert row["song_id"] is None
    assert int(row["slot_idx"]) == 3
