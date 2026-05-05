"""
Phase F-Final Subphase 1 — schema + seed for the rotation engine.

Verifies that:
 - voice_tracks table exists (or is created idempotently)
 - clock_slots gains selection_mode column (idempotent)
 - seed_rotation_test_data populates 3 sweepers + 2 station IDs +
   2 voice tracks when each table is empty, and is a no-op on second
   call
 - Lookup methods return rows
"""

from __future__ import annotations

from core.database import Database


def test_voice_tracks_table_exists_after_ensure(qtbot):
    db = Database()
    db._ensure_voice_tracks_table()
    db._ensure_voice_tracks_table()    # idempotence
    cols = {r[1] for r in db._conn().execute(
        "PRAGMA table_info(voice_tracks)").fetchall()}
    for expected in ("id", "name", "file_path", "duration_ms",
                     "valid_from", "valid_to", "label", "is_active"):
        assert expected in cols


def test_clock_slots_selection_mode_column_present(qtbot):
    db = Database()
    db._ensure_clock_slots_columns()
    db._ensure_clock_slots_columns()
    cols = {r[1] for r in db._conn().execute(
        "PRAGMA table_info(clock_slots)").fetchall()}
    assert "selection_mode" in cols


def test_seed_rotation_test_data_runs_idempotently(qtbot):
    db = Database()
    # First seed — may insert rows or be no-op if data already present.
    first = db.seed_rotation_test_data()
    assert isinstance(first, dict)
    # Tables now have data
    n_sw = db._conn().execute("SELECT COUNT(*) FROM sweepers").fetchone()[0]
    n_st = db._conn().execute(
        "SELECT COUNT(*) FROM jingles WHERE category = 'Station ID'"
    ).fetchone()[0]
    n_vt = db._conn().execute("SELECT COUNT(*) FROM voice_tracks").fetchone()[0]
    assert n_sw >= 3
    assert n_st >= 2
    assert n_vt >= 2

    # Second call — every count is 0 (idempotent).
    second = db.seed_rotation_test_data()
    assert second == {"sweepers": 0, "station_ids": 0, "voice_tracks": 0}


def test_lookup_methods_return_rows(qtbot):
    db = Database()
    db.seed_rotation_test_data()
    assert len(list(db.get_sweepers_active()))    >= 3
    assert len(list(db.get_station_ids_active())) >= 2
    assert len(list(db.get_voice_tracks()))       >= 2
