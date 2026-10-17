"""
broadcast_log must never lose a play because its clock vanished
(2026-10-16).

delete_clock() NULLs clock_id on rows that are ALREADY in broadcast_log,
but the scheduler can still hand out an item carrying the deleted id (it
was picked a moment before the operator deleted the clock in the Clock
Editor). log_play() then hit a FOREIGN KEY failure and the caller logged
a warning — the airtime record, which Spot reports and Play History are
built from, was simply gone.

log_play() now retries without clock_id on that specific failure. The
song / campaign links are kept, and any other integrity error still
raises.
"""

from __future__ import annotations

import sqlite3

import pytest

from core.database import Database


@pytest.fixture
def db():
    return Database()


def _missing_clock_id(db) -> int:
    row = db._conn().execute("SELECT COALESCE(MAX(id), 0) FROM clocks"
                             ).fetchone()
    return int(row[0]) + 100_000


def _fk_enforced(db) -> bool:
    return bool(db._conn().execute("PRAGMA foreign_keys").fetchone()[0])


def _last(db, entry_type):
    return db._conn().execute(
        "SELECT * FROM broadcast_log WHERE entry_type = ? "
        "ORDER BY id DESC LIMIT 1", [entry_type]).fetchone()


def test_play_with_deleted_clock_is_still_logged(db):
    if not _fk_enforced(db):
        pytest.skip("foreign keys not enforced on this connection")
    conn = db._conn()
    before = conn.execute("SELECT COUNT(*) FROM broadcast_log").fetchone()[0]
    db.log_play(entry_type="sweeper", duration_ms=9000,
                clock_id=_missing_clock_id(db), slot_idx=4)
    after = conn.execute("SELECT COUNT(*) FROM broadcast_log").fetchone()[0]
    assert after == before + 1, "the play was dropped"
    row = _last(db, "sweeper")
    assert row["clock_id"] is None          # dangling link removed
    assert int(row["slot_idx"]) == 4         # the rest of the record kept
    assert int(row["duration_ms"]) == 9000
    conn.execute("DELETE FROM broadcast_log WHERE id = ?", [row["id"]])
    conn.commit()


def test_valid_clock_is_kept(db):
    row = db._conn().execute("SELECT id FROM clocks LIMIT 1").fetchone()
    if row is None:
        pytest.skip("no clocks in this database")
    cid = int(row["id"])
    db.log_play(entry_type="jingle", duration_ms=5000, clock_id=cid,
                slot_idx=2)
    last = _last(db, "jingle")
    assert int(last["clock_id"]) == cid
    db._conn().execute("DELETE FROM broadcast_log WHERE id = ?", [last["id"]])
    db._conn().commit()


def test_other_integrity_errors_still_raise(db):
    """Only the clock link is forgiven — a dangling song is still an
    error the caller must see."""
    if not _fk_enforced(db):
        pytest.skip("foreign keys not enforced on this connection")
    bad_song = int(db._conn().execute(
        "SELECT COALESCE(MAX(id), 0) FROM songs").fetchone()[0]) + 100_000
    with pytest.raises(sqlite3.IntegrityError):
        db.log_play(entry_type="song", song_id=bad_song, duration_ms=1000)
