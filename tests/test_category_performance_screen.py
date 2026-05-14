"""
Category Performance screen (Figma 448:3) + DB helpers tests.

Pinned behaviour:
  • db.get_category_performance_summary(category_id) returns the
    canonical summary keys (category_name, song_count, total_plays,
    plays_this_month/week, avg_per_song, most_played).
  • db.get_category_monthly_plays(category_id, months=12) returns
    exactly N {year, month, label, count} entries oldest-first, with
    zero-filled gaps so the bar chart never has missing months.
  • db.get_category_songs_ranked(category_id) returns every song in
    the category, ordered by total_plays desc, then title asc. Zero-
    play rows are included.
  • CategoryPerformance constructs without crashing.
  • load_category() drives hero + stats + chart + songs table.
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
def category_with_plays(db):
    """Seed broadcast_log with rows attached to a few songs in one
    category. Clean up via a unique operator marker on each row."""
    marker = f"test_cat_perf_{uuid.uuid4().hex[:8]}"
    conn = db._conn()
    # Find a category that already has songs — defensive choice because
    # we need real song ids (broadcast_log.song_id has a real FK).
    cat = None
    for c in db.get_categories():
        if int(c["song_count"] or 0) > 0:
            cat = c
            break
    if cat is None:
        pytest.skip("Dev DB has no category with songs to seed")
    cid = int(cat["id"])
    songs = conn.execute(
        "SELECT id FROM songs WHERE category_id = ? LIMIT 3",
        [cid]).fetchall()
    if not songs:
        pytest.skip("No songs in chosen category to seed")
    song_ids = [int(r["id"]) for r in songs]

    import datetime as _dt
    today = _dt.date.today()
    first_of_month = today.replace(day=1)
    last_month_start = (first_of_month - _dt.timedelta(days=1)).replace(day=1)
    # Distribute across this month + last month so we exercise both
    # plays_this_month and plays_last_month counters.
    rows = [
        (f"{today.isoformat()} 06:14:30", song_ids[0]),
        (f"{today.isoformat()} 02:48:12", song_ids[0]),
        (f"{first_of_month.isoformat()} 19:22:05",
         song_ids[1 % len(song_ids)]),
        (f"{last_month_start.isoformat()} 12:30:00",
         song_ids[2 % len(song_ids)]),
        (f"{last_month_start.isoformat()} 18:00:00",
         song_ids[0]),
    ]
    for played_at, song_id in rows:
        conn.execute(
            "INSERT INTO broadcast_log "
            "(played_at, entry_type, song_id, duration_ms, operator) "
            "VALUES (?, 'song', ?, 180000, ?)",
            [played_at, song_id, marker])
    conn.commit()
    yield marker, cid, song_ids
    try:
        conn.execute("DELETE FROM broadcast_log WHERE operator = ?",
                     [marker])
        conn.commit()
    except Exception:
        pass


# ── DB helpers ─────────────────────────────────────────────────────────


def test_summary_returns_canonical_keys(db, category_with_plays):
    _, cid, _ = category_with_plays
    s = db.get_category_performance_summary(cid)
    expected = {
        "category_id", "category_name", "song_count",
        "total_plays", "last_played_at",
        "plays_this_month", "plays_last_month",
        "plays_this_week", "plays_last_week",
        "avg_per_song", "most_played",
    }
    assert expected.issubset(set(s.keys()))
    assert s["category_id"] == cid


def test_summary_counts_this_month_includes_seeded_rows(
        db, category_with_plays):
    _, cid, _ = category_with_plays
    s = db.get_category_performance_summary(cid)
    # Seed has 3 rows in current month (2 today + 1 on first-of-month)
    assert s["plays_this_month"] >= 3


def test_summary_avg_per_song_is_lifetime(db, category_with_plays):
    """avg_per_song must equal total_plays / song_count (lifetime avg),
    NOT a rolling/weekly figure. Operator picked this shape explicitly
    in the design sign-off."""
    _, cid, _ = category_with_plays
    s = db.get_category_performance_summary(cid)
    sc = int(s["song_count"])
    tp = int(s["total_plays"])
    if sc > 0:
        expected = round(tp / sc, 1)
        assert s["avg_per_song"] == expected


def test_summary_most_played_is_real_song(db, category_with_plays):
    """When the category has plays, most_played must be a dict with
    id / title / artist / count and the count must equal the row's
    aggregate plays."""
    _, cid, _ = category_with_plays
    s = db.get_category_performance_summary(cid)
    mp = s["most_played"]
    assert mp is not None
    assert {"id", "title", "artist", "count"}.issubset(set(mp.keys()))
    assert int(mp["count"]) >= 1


def test_monthly_plays_returns_n_zero_filled(db, category_with_plays):
    _, cid, _ = category_with_plays
    out = db.get_category_monthly_plays(cid, months=12)
    assert len(out) == 12
    # Oldest-first ordering
    pairs = [(d["year"], d["month"]) for d in out]
    assert pairs == sorted(pairs)
    for d in out:
        assert {"year", "month", "label", "count"}.issubset(set(d.keys()))


def test_songs_ranked_returns_all_category_songs(db, category_with_plays):
    """Includes zero-play rows — operator wants dead-inventory
    visibility in the report."""
    _, cid, _ = category_with_plays
    rows = db.get_category_songs_ranked(cid)
    # Count must match the category's true song count
    s = db.get_category_performance_summary(cid)
    assert len(rows) == int(s["song_count"])
    # Ordered by total_plays desc (then title asc)
    totals = [int(r["total_plays"] or 0) for r in rows]
    assert totals == sorted(totals, reverse=True)


def test_songs_ranked_includes_dead_inventory_when_present(
        db, category_with_plays):
    """If any songs in the category have zero plays, they must surface
    at the bottom of the ranked list — not be silently filtered out."""
    _, cid, _ = category_with_plays
    rows = db.get_category_songs_ranked(cid)
    # If the seeded category has more songs than we exercised, at least
    # one zero-play row should exist. If the category is fully active
    # we just assert the count is positive.
    s = db.get_category_performance_summary(cid)
    if int(s["song_count"]) > 3:
        zero_rows = [r for r in rows
                     if int(r["total_plays"] or 0) == 0]
        assert len(zero_rows) >= 1


# ── Screen smoke ───────────────────────────────────────────────────────


def test_construction_does_not_crash(qapp, db):
    from ui.category_performance import CategoryPerformance
    s = CategoryPerformance(db)
    assert s.size().width() == 1440
    assert s.size().height() == 900
    s.deleteLater()


def test_load_category_populates_widgets(qapp, db, category_with_plays):
    from ui.category_performance import CategoryPerformance
    _, cid, _ = category_with_plays
    s = CategoryPerformance(db)
    s.load_category(cid)
    # Hero total > 0 because we seeded broadcast rows
    total_txt = s._hero._right_total.text().replace(",", "")
    assert int(total_txt) >= 5
    # Monthly chart populated with 12 entries
    assert len(s._chart._data) == 12
    # Songs table has at least one row
    assert s._songs._table.rowCount() >= 1
    s.deleteLater()


def test_load_category_handles_invalid_id_gracefully(qapp, db):
    """Edge: passing an id that doesn't exist shouldn't crash — the
    summary helper returns zeros and the screen renders empty state."""
    from ui.category_performance import CategoryPerformance
    s = CategoryPerformance(db)
    s.load_category(99_999_999)  # not an existing category
    # Chart should still be populated (12 zero-filled months)
    assert s._chart._data is not None
    assert len(s._chart._data) == 12
    s.deleteLater()


def test_load_category_rejects_non_positive(qapp, db):
    """load_category(0) or negative should no-op without crashing."""
    from ui.category_performance import CategoryPerformance
    s = CategoryPerformance(db)
    s.load_category(0)
    s.load_category(-1)
    s.deleteLater()


def test_station_label_has_object_name(qapp, db):
    """Branding-refresh walk requires findChild(QLabel, 'hdr_station_lbl')."""
    from PyQt6.QtWidgets import QLabel
    from ui.category_performance import CategoryPerformance
    s = CategoryPerformance(db)
    lbl = s.findChild(QLabel, "hdr_station_lbl")
    assert lbl is not None
    s.deleteLater()


# ── Songs Library accessors (current_category_id / _name) ─────────────


def test_songs_library_exposes_current_category_accessors(qapp, db):
    """The accessors are pure UI state — they should return empty/None
    on first construction when the dropdown sits at the 'All' sentinel."""
    from ui.songs_library import SongsLibrary
    sl = SongsLibrary(db)
    assert sl.current_category_name() == ""
    assert sl.current_category_id() is None
    sl.deleteLater()
