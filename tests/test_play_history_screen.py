"""
Play History screen (Figma 437:3) + DB helpers tests.

Pinned behaviour:
  • db.get_song_play_history_summary(song_id) returns the canonical
    summary keys (total_plays / added_at / plays_this_month / week /
    avg_per_week / last_played_at).
  • db.get_song_monthly_plays(song_id, months=12) returns exactly the
    requested number of {year, month, label, count} entries oldest-
    first, zero-fills missing months.
  • db.get_song_recent_plays(song_id, limit) returns most-recent-first
    rows with clock_name joined.
  • PlayHistory constructs without crashing.
  • load_song() drives the hero card + stats + chart + recent table.
  • Header station label opts into the branding-refresh walk.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import Database


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def marked_log_rows(db):
    """Seed broadcast_log with rows for an arbitrary song id 1 across
    several months. Clean up via a unique operator marker."""
    marker = f"test_play_hist_{uuid.uuid4().hex[:8]}"
    conn = db._conn()
    # Find a real song id we can attach plays to — defensive choice
    # because broadcast_log.song_id has a real FK.
    srow = conn.execute(
        "SELECT id FROM songs LIMIT 1").fetchone()
    if srow is None:
        pytest.skip("Dev DB has no songs to attach plays to")
    sid = int(srow["id"])
    # Seed rows: 3 this month, 2 last month, 1 last week, 1 today
    import datetime as _dt
    today = _dt.date.today()
    first_of_month = today.replace(day=1)
    last_month_start = (first_of_month - _dt.timedelta(days=1)).replace(day=1)
    rows = [
        (f"{today.isoformat()} 06:14:30", sid),
        (f"{today.isoformat()} 02:48:12", sid),
        (f"{first_of_month.isoformat()} 19:22:05", sid),
        (f"{last_month_start.isoformat()} 12:30:00", sid),
        (f"{last_month_start.isoformat()} 18:00:00", sid),
    ]
    for played_at, song_id in rows:
        conn.execute(
            "INSERT INTO broadcast_log "
            "(played_at, entry_type, song_id, duration_ms, operator) "
            "VALUES (?, 'song', ?, 180000, ?)",
            [played_at, song_id, marker])
    conn.commit()
    yield marker, sid
    try:
        conn.execute("DELETE FROM broadcast_log WHERE operator = ?",
                     [marker])
        conn.commit()
    except Exception:
        pass


# ── DB helpers ─────────────────────────────────────────────────────────


def test_summary_returns_canonical_keys(db, marked_log_rows):
    marker, sid = marked_log_rows
    s = db.get_song_play_history_summary(sid)
    expected = {
        "song_id", "added_at", "total_plays",
        "last_played_at",
        "plays_this_month", "plays_last_month",
        "plays_this_week", "plays_last_week",
        "avg_per_week",
    }
    assert expected.issubset(set(s.keys()))
    assert s["song_id"] == sid


def test_summary_counts_this_month_includes_seeded_rows(
        db, marked_log_rows):
    _, sid = marked_log_rows
    s = db.get_song_play_history_summary(sid)
    # Seed has 3 rows in current month (2 today + 1 on first-of-month)
    assert s["plays_this_month"] >= 3


def test_monthly_plays_returns_n_zero_filled(db, marked_log_rows):
    _, sid = marked_log_rows
    out = db.get_song_monthly_plays(sid, months=12)
    assert len(out) == 12
    # Oldest-first ordering
    pairs = [(d["year"], d["month"]) for d in out]
    assert pairs == sorted(pairs)
    # Schema
    for d in out:
        assert {"year", "month", "label", "count"}.issubset(set(d.keys()))


def test_recent_plays_returns_most_recent_first(db, marked_log_rows):
    _, sid = marked_log_rows
    rows = db.get_song_recent_plays(sid, limit=10)
    assert len(rows) >= 1
    # Newest first
    played = [r["played_at"] for r in rows]
    assert played == sorted(played, reverse=True)


# ── Screen smoke ───────────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    from ui.play_history import PlayHistory
    s = PlayHistory(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    s.deleteLater()


def test_load_song_populates_widgets(qapp, db, marked_log_rows):
    from ui.play_history import PlayHistory
    _, sid = marked_log_rows
    s = PlayHistory(db)
    s.load_song(sid)
    # Hero total > 0 because we seeded broadcast rows
    assert int(s._hero._right_total.text().replace(",", "")) >= 5
    # Monthly chart populated with 12 entries
    assert len(s._chart._data) == 12
    # Recent plays table has rows
    assert s._recent._table.rowCount() >= 1
    s.deleteLater()


def test_load_song_handles_unknown_id_gracefully(qapp, db):
    """Edge: passing a non-existent song id shouldn't crash — the
    screen renders zeros + empty placeholders."""
    from ui.play_history import PlayHistory
    s = PlayHistory(db)
    s.load_song(99_999_999)  # very unlikely to exist
    assert s._chart._data is not None
    s.deleteLater()


def test_station_label_has_object_name(qapp, db):
    """Branding-refresh walk requires findChild(QLabel, 'hdr_station_lbl')."""
    from PyQt6.QtWidgets import QLabel
    from ui.play_history import PlayHistory
    s = PlayHistory(db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()
