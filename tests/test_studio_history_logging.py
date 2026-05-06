"""
Studio v3 — History panel + broadcast_log pipeline tests.

History panel was missing data because:
  1. _on_queue_song_play gated log_play behind ``if clock_id is not None:``,
     so manual plays (Live-Assist, library double-clicks, ▶ Play from
     idle) never wrote to broadcast_log.
  2. _refresh_history fired only on spot-EOS — songs starting/ending
     and spots starting didn't refresh the panel.

This file verifies the post-fix contract:
  - Every song play writes a broadcast_log row (manual or scheduler-driven).
  - was_manual flag distinguishes the two cases for downstream reports.
  - History panel refreshes immediately on every play-start (song or spot).

Real DB + AudioEngine fixtures from conftest. Test rows are cleaned up
in finally blocks so the live ``radioai.db`` stays tidy.
"""

from __future__ import annotations

import os
import uuid

import pytest

from core.database import Database
from ui.studio import Studio


@pytest.fixture
def studio(qtbot, engine):
    """Studio with shared engine + fresh Database, no scheduler. Studio's
    in-memory queue is loaded from the live DB by _load_queue_from_db,
    so it always has playable songs in this fixture."""
    db = Database()
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=None)
    if not s._queue_songs:
        pytest.skip("queue needs at least 1 playable DB song for history tests")
    yield s
    if s._playback_cid is not None:
        try:
            engine.cleanup(s._playback_cid)
        except Exception:
            pass


def _broadcast_log_count(db: Database) -> int:
    row = db._conn().execute(
        "SELECT COUNT(*) FROM broadcast_log").fetchone()
    return int(row[0] if row else 0)


def _latest_broadcast_log_row(db: Database) -> dict:
    row = db._conn().execute(
        "SELECT * FROM broadcast_log ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else {}


# ── 1. Manual song play (no scheduler attribution) writes to log ──────


def test_manual_song_play_writes_to_broadcast_log(qtbot, studio):
    """Pre-fix: manual plays without _clock_id were silently skipped.
    Post-fix: every play lands in broadcast_log so History reflects it."""
    db = studio._db
    song = dict(studio._queue_songs[0])
    # Strip any scheduler attribution to simulate a manual play
    song.pop("_clock_id", None)
    song.pop("_slot_idx", None)
    song.pop("_item_type", None)

    pre_count = _broadcast_log_count(db)
    pre_id = db._conn().execute(
        "SELECT MAX(id) FROM broadcast_log").fetchone()[0] or 0

    studio._on_queue_song_play(song)
    qtbot.wait(50)

    post_count = _broadcast_log_count(db)
    assert post_count == pre_count + 1, (
        "manual song play must write exactly one broadcast_log row")

    latest = _latest_broadcast_log_row(db)
    assert latest.get("entry_type") == "song"
    assert latest.get("song_id") == song.get("id")
    assert latest.get("clock_id") is None, (
        "manual play has no scheduler attribution → clock_id NULL")
    assert latest.get("was_manual") == 1, (
        "manual play must set was_manual=1 to distinguish from auto plays")

    # Cleanup — drop the row we just inserted so we don't pollute the DB
    try:
        db._conn().execute(
            "DELETE FROM broadcast_log WHERE id > ?", [int(pre_id)])
        db._conn().commit()
    except Exception:
        pass


# ── 2. History panel refresh fires on song play-start ──────────────────


def test_song_play_refreshes_history_panel(qtbot, studio):
    """Operator should see the just-started song appear in the History
    panel immediately. Pre-fix: panel only refreshed on spot-EOS."""
    db = studio._db
    song = dict(studio._queue_songs[0])
    song.pop("_clock_id", None)

    refresh_count = {"n": 0}
    original = studio._refresh_history

    def _counting_refresh():
        refresh_count["n"] += 1
        original()

    studio._refresh_history = _counting_refresh

    pre_id = db._conn().execute(
        "SELECT MAX(id) FROM broadcast_log").fetchone()[0] or 0

    studio._on_queue_song_play(song)
    qtbot.wait(50)

    assert refresh_count["n"] >= 1, (
        "_refresh_history must fire at least once after _on_queue_song_play")

    try:
        db._conn().execute(
            "DELETE FROM broadcast_log WHERE id > ?", [int(pre_id)])
        db._conn().commit()
    except Exception:
        pass


# ── 3. Spot dispatch refreshes history panel on play-start ────────────


def test_spot_dispatch_refreshes_history_panel(qtbot, studio):
    """The spot's broadcast_log row is written at play-start; History
    must reflect it within the same call so the operator sees the spot
    appear in the panel as soon as it goes on air, not when it ends."""
    db = studio._db

    # Stage a real campaign + spot file using a real on-disk audio file
    rows = db._conn().execute(
        "SELECT file_path FROM songs WHERE file_path IS NOT NULL "
        "AND file_path != '' ORDER BY id LIMIT 5"
    ).fetchall()
    real_path = next(
        (r[0] for r in rows if r[0] and os.path.exists(r[0])), None)
    if real_path is None:
        pytest.skip("no real on-disk audio path to use as spot file")

    name = f"_test_history_spot_{uuid.uuid4().hex[:8]}"
    cid = db.add_campaign({"name": name, "is_active": 1, "priority": 5})
    fid = db.add_spot_file(cid, {
        "filename":    f"{name}.mp3",
        "file_path":   real_path,
        "duration_ms": 5_000,
        "is_active":   1,
    })

    refresh_count = {"n": 0}
    original = studio._refresh_history

    def _counting_refresh():
        refresh_count["n"] += 1
        original()

    studio._refresh_history = _counting_refresh

    pre_id = db._conn().execute(
        "SELECT MAX(id) FROM broadcast_log").fetchone()[0] or 0

    try:
        studio._do_scheduler_spot_due(int(cid))
        qtbot.wait(50)

        assert refresh_count["n"] >= 1, (
            "_refresh_history must fire after _do_scheduler_spot_due")

        # Also verify the row landed with the right metadata
        latest = _latest_broadcast_log_row(db)
        assert latest.get("entry_type") == "spot"
        assert latest.get("campaign_id") == int(cid)
    finally:
        try:
            db.delete_spot_file(fid)
            db._conn().execute(
                "DELETE FROM campaigns WHERE id = ?", [int(cid)])
            db._conn().execute(
                "DELETE FROM broadcast_log WHERE id > ?", [int(pre_id)])
            db._conn().commit()
        except Exception:
            pass
