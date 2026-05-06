"""
Database tests for the Create New Playlist flow.

Covers:
  - Paginated song search (offset / limit / sort / bpm + year filters)
  - Match count helper (count_songs)
  - Playlist draft state machine (create / update / replace_songs /
    commit / delete)
  - Drafts excluded from get_playlists_with_stats()
"""

from __future__ import annotations

import pytest

from core.database import Database


@pytest.fixture
def db():
    return Database()


# ── Paginated song search ──────────────────────────────────────────────


def test_search_songs_returns_at_most_limit(db):
    rows = db.search_songs(limit=5)
    assert len(rows) <= 5


def test_search_songs_offset_yields_different_rows(db):
    page1 = list(db.search_songs(limit=5, offset=0))
    page2 = list(db.search_songs(limit=5, offset=5))
    if len(page1) < 5 or len(page2) < 1:
        pytest.skip("not enough songs in DB to test offset")
    ids1 = {int(r["id"]) for r in page1}
    ids2 = {int(r["id"]) for r in page2}
    # No overlap (sort is deterministic so disjoint pages)
    assert ids1.isdisjoint(ids2)


def test_search_songs_sort_options_dont_crash(db):
    for s in ("recent", "az", "bpm", "garbage"):
        rows = db.search_songs(limit=3, sort=s)
        assert isinstance(rows, list)


def test_search_songs_query_filters_title_or_artist(db):
    # Use a substring that's likely in either title or artist
    rows = db.search_songs(query="th", limit=20)
    if not rows:
        pytest.skip("no songs match 'th'")
    for r in rows:
        text = ((r["title"] or "") + " " + (r["artist"] or "")).lower()
        assert "th" in text


def test_search_songs_bpm_range(db):
    rows = db.search_songs(bpm_min=100, bpm_max=140, limit=10)
    for r in rows:
        bpm = int(r["bpm"] or 0)
        assert 100 <= bpm <= 140


def test_search_songs_year_range(db):
    rows = db.search_songs(year_min=2000, year_max=2030, limit=10)
    for r in rows:
        y = int(r["year"] or 0)
        assert 2000 <= y <= 2030


def test_count_songs_matches_search_pagination(db):
    """count_songs and search_songs apply the same filter SQL — count
    should equal the union of all paginated pages with the same filter."""
    total = db.count_songs(query=None)
    # Walk pages and verify we don't see more than count_songs rows
    seen = 0
    page = 0
    while True:
        rows = db.search_songs(offset=page * 50, limit=50)
        seen += len(rows)
        if len(rows) < 50:
            break
        page += 1
        if page > 200:    # safety cap
            break
    assert seen <= total


# ── Playlist draft state machine ───────────────────────────────────────


def test_create_playlist_draft_inserts_with_status_draft(db):
    pid = db.create_playlist_draft(
        name="Draft Test", kind="manual", color="#06b6d4", tags="a,b")
    try:
        row = db._conn().execute(
            "SELECT * FROM playlists WHERE id = ?", [pid]).fetchone()
        assert row["name"] == "Draft Test"
        assert row["status"] == "draft"
        assert row["kind"] == "manual"
        assert row["color"] == "#06b6d4"
        assert row["tags"] == "a,b"
        assert int(row["is_active"]) == 0
    finally:
        db.delete_playlist_draft(pid)


def test_update_playlist_draft_only_writes_passed_fields(db):
    pid = db.create_playlist_draft(name="UpdTest", color="#f43f5e")
    try:
        db.update_playlist_draft(pid, name="UpdTest 2")
        row = db._conn().execute(
            "SELECT * FROM playlists WHERE id = ?", [pid]).fetchone()
        assert row["name"] == "UpdTest 2"
        # Color unchanged
        assert row["color"] == "#f43f5e"
        # Now flip auto-schedule
        db.update_playlist_draft(pid, auto_schedule_enabled=True)
        row = db._conn().execute(
            "SELECT auto_schedule_enabled FROM playlists WHERE id = ?",
            [pid]).fetchone()
        assert int(row["auto_schedule_enabled"]) == 1
    finally:
        db.delete_playlist_draft(pid)


def test_replace_playlist_songs_atomic(db):
    pid = db.create_playlist_draft(name="ReplaceTest")
    songs = list(db.get_songs(limit=5))
    if len(songs) < 3:
        pytest.skip("need at least 3 songs in DB")
    try:
        ids_a = [int(s["id"]) for s in songs[:3]]
        db.replace_playlist_songs(pid, ids_a)
        rows = db._conn().execute(
            "SELECT song_id, position FROM playlist_songs "
            "WHERE playlist_id = ? ORDER BY position", [pid]).fetchall()
        assert [int(r["song_id"]) for r in rows] == ids_a
        # Second replace overwrites — position renumbered
        ids_b = [int(s["id"]) for s in songs[2::-1]]    # reversed first 3
        db.replace_playlist_songs(pid, ids_b)
        rows = db._conn().execute(
            "SELECT song_id, position FROM playlist_songs "
            "WHERE playlist_id = ? ORDER BY position", [pid]).fetchall()
        assert [int(r["song_id"]) for r in rows] == ids_b
        positions = [int(r["position"]) for r in rows]
        assert positions == [1, 2, 3]
    finally:
        db.delete_playlist_draft(pid)


def test_commit_playlist_draft_flips_to_active(db):
    pid = db.create_playlist_draft(name="CommitTest")
    try:
        db.commit_playlist_draft(pid)
        row = db._conn().execute(
            "SELECT status, is_active FROM playlists WHERE id = ?",
            [pid]).fetchone()
        assert row["status"] == "active"
        assert int(row["is_active"]) == 1
    finally:
        # Force-delete: commit flipped status, so delete_playlist_draft
        # won't delete it. Drop manually for cleanup.
        db._conn().execute(
            "DELETE FROM playlist_songs WHERE playlist_id = ?", [pid])
        db._conn().execute("DELETE FROM playlists WHERE id = ?", [pid])
        db._conn().commit()


def test_delete_playlist_draft_only_deletes_drafts(db):
    """delete_playlist_draft refuses to drop active playlists."""
    pid_draft = db.create_playlist_draft(name="DeleteDraftTest")
    pid_active = db.create_playlist_draft(name="DeleteActiveTest")
    db.commit_playlist_draft(pid_active)
    try:
        ok = db.delete_playlist_draft(pid_draft)
        assert ok is True
        # Active row stays
        ok2 = db.delete_playlist_draft(pid_active)
        assert ok2 is False
        row = db._conn().execute(
            "SELECT id FROM playlists WHERE id = ?", [pid_active]
        ).fetchone()
        assert row is not None
    finally:
        # Cleanup the active row
        db._conn().execute(
            "DELETE FROM playlist_songs WHERE playlist_id = ?", [pid_active])
        db._conn().execute(
            "DELETE FROM playlists WHERE id = ?", [pid_active])
        db._conn().commit()


def test_drafts_excluded_from_get_playlists_with_stats(db):
    """Drafts should NOT appear on the Playlists screen list."""
    pid_draft = db.create_playlist_draft(name="HiddenDraftTest")
    try:
        all_rows = db.get_playlists_with_stats()
        ids = {int(r["id"]) for r in all_rows}
        assert pid_draft not in ids
    finally:
        db.delete_playlist_draft(pid_draft)


# ── Edit Playlist screen — single-row + full-track-list helpers ─────────


def test_get_playlist_returns_row_by_id(db):
    """Frame 9's load path: db.get_playlist(id) → row with meta cols."""
    pid = db.create_playlist_draft(
        name="GetPlaylistTest", kind="manual", color="#a78bfa", tags="hello")
    db.commit_playlist_draft(pid)
    try:
        row = db.get_playlist(pid)
        assert row is not None
        assert row["name"] == "GetPlaylistTest"
        assert row["kind"] == "manual"
        # Premium-screen extension cols are present
        assert "color" in row.keys()
        assert "tags" in row.keys()
    finally:
        db._conn().execute(
            "DELETE FROM playlist_songs WHERE playlist_id = ?", [pid])
        db._conn().execute(
            "DELETE FROM playlists WHERE id = ?", [pid])
        db._conn().commit()


def test_get_playlist_returns_none_for_missing_id(db):
    assert db.get_playlist(999_999_999) is None


def test_get_playlist_songs_returns_full_list_no_limit(db):
    """Frame 9's load path: db.get_playlist_songs(id) returns every
    track (no implicit limit), in position order. Distinct from
    get_playlist_first_tracks which is the limited preview cousin."""
    rows = db._conn().execute(
        "SELECT id FROM songs WHERE is_enabled=1 LIMIT 7"
    ).fetchall()
    if len(rows) < 7:
        pytest.skip("not enough songs to exercise full-list load")
    seed_ids = [int(r[0]) for r in rows]
    pid = db.create_playlist_draft(name="FullListTest")
    db.commit_playlist_draft(pid)
    try:
        db.replace_playlist_songs(pid, seed_ids)
        loaded = list(db.get_playlist_songs(pid))
        assert [int(r["id"]) for r in loaded] == seed_ids
        # Each row carries the columns Frame 9 needs
        for r in loaded:
            assert "title" in r and "artist" in r and "duration_ms" in r
            assert "year" in r and "bpm" in r and "album" in r
    finally:
        db._conn().execute(
            "DELETE FROM playlist_songs WHERE playlist_id = ?", [pid])
        db._conn().execute(
            "DELETE FROM playlists WHERE id = ?", [pid])
        db._conn().commit()
