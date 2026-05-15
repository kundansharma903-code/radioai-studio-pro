"""
Phase C — Rotation engine DB layer tests.

Covers:
  • _ensure_ai_rotation_tables idempotent migration (re-runs are no-ops)
  • Sister group create / delete / add / remove / get / pool lookups
  • Cap enforcement (5 max, 2 min, no double-membership)
  • Validation (unknown category id, duplicate input)
  • Cascade behavior (delete group → members go; delete category → row goes)
  • Auto-delete when group falls below 2 members
  • AI rotation plan envelope CRUD (get_or_create, reset, approve/discard/auto-apply)
  • Decision row insert + clock-scoped fetch + date-scoped fetch with joins
  • Plan stats aggregation
  • purge_old_rotation_decisions cleanup
  • get_song_last_played_in_hour returns correct date or None
  • Time-Slot Freshness weekday-agnostic (D2 = b)

No engine code touched yet — Phase D builds on this in next session.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from core.database import Database


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def cats(db):
    """Create 5 throwaway categories, yield their ids, clean up after.

    All Phase C tests need real category ids because sister_group_members
    FK-references categories.id. Using uuid suffixes avoids collisions
    with other tests' fixtures.

    Teardown: deleting categories cascades sister_group_members rows,
    but the sister_groups parent envelope is NOT auto-cascaded (it's
    the parent side of the FK). Without an explicit orphan wipe these
    tests leaked ~14 sister_groups rows per run into the live dev DB.
    Phase G fix: snapshot existing group ids before the test, then on
    teardown delete any NEW groups that now have zero members."""
    conn = db._conn()
    # Snapshot pre-test sister_groups so we never touch foreign rows
    pre_group_ids = {int(r[0]) for r in conn.execute(
        "SELECT id FROM sister_groups").fetchall()}

    names = [f"phaseC-{uuid.uuid4().hex[:8]}" for _ in range(5)]
    ids = []
    for n in names:
        cur = conn.execute(
            "INSERT INTO categories (name, color) VALUES (?, ?)",
            [n, "#06b6d4"])
        ids.append(int(cur.lastrowid))
    conn.commit()
    yield ids
    # Cleanup — cascade wipes sister_group_members + ungroups via CASCADE
    for cid in ids:
        conn.execute("DELETE FROM categories WHERE id = ?", [cid])
    # Wipe any sister_groups created during THIS test that now have
    # zero members (cascade orphans). Skip any group that pre-dated
    # the test so we don't touch concurrent fixtures.
    orphans = conn.execute(
        "SELECT id FROM sister_groups WHERE id NOT IN ("
        "SELECT DISTINCT group_id FROM sister_group_members)"
    ).fetchall()
    for r in orphans:
        gid = int(r[0])
        if gid not in pre_group_ids:
            conn.execute(
                "DELETE FROM sister_groups WHERE id = ?", [gid])
    conn.commit()


@pytest.fixture
def a_clock(db):
    """Create a throwaway clock and yield its id."""
    name = f"phaseC-clock-{uuid.uuid4().hex[:8]}"
    cur = db._conn().execute(
        "INSERT INTO clocks (name, is_active) VALUES (?, 1)",
        [name])
    db._conn().commit()
    cid = int(cur.lastrowid)
    yield cid
    db._conn().execute("DELETE FROM clocks WHERE id = ?", [cid])
    db._conn().commit()


# ── Migration idempotency ─────────────────────────────────────────────────


def test_ensure_tables_idempotent(db):
    """Calling _ensure_ai_rotation_tables twice must not raise — every
    Phase C helper triggers it on first call."""
    db._ensure_ai_rotation_tables()
    db._ensure_ai_rotation_tables()    # 2nd call should be cheap no-op
    for t in ("sister_groups", "sister_group_members",
              "ai_rotation_plans", "ai_rotation_decisions"):
        row = db._conn().execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = ?", [t]).fetchone()
        assert row is not None, f"{t} missing after migration"


# ── Sister group: create ──────────────────────────────────────────────────


def test_create_sister_group_happy_path(db, cats):
    gid = db.create_sister_group([cats[0], cats[1], cats[2]])
    assert isinstance(gid, int) and gid > 0
    groups = db.get_sister_groups()
    target = [g for g in groups if g["id"] == gid]
    assert len(target) == 1
    members = sorted(c["id"] for c in target[0]["categories"])
    assert members == sorted([cats[0], cats[1], cats[2]])


def test_create_sister_group_rejects_below_min(db, cats):
    with pytest.raises(ValueError, match="at least 2"):
        db.create_sister_group([cats[0]])
    with pytest.raises(ValueError, match="at least 2"):
        db.create_sister_group([])


def test_create_sister_group_rejects_above_max(db, cats):
    """Operator's Q-A cap = 5 categories per group."""
    # We only have 5 cats fixture; create 1 more to exceed
    extra = db._conn().execute(
        "INSERT INTO categories (name) VALUES (?)",
        [f"phaseC-extra-{uuid.uuid4().hex[:8]}"]).lastrowid
    db._conn().commit()
    try:
        with pytest.raises(ValueError, match="capped at"):
            db.create_sister_group([cats[0], cats[1], cats[2],
                                      cats[3], cats[4], int(extra)])
    finally:
        db._conn().execute(
            "DELETE FROM categories WHERE id = ?", [int(extra)])
        db._conn().commit()


def test_create_sister_group_rejects_duplicates_in_input(db, cats):
    with pytest.raises(ValueError, match="duplicate"):
        db.create_sister_group([cats[0], cats[0], cats[1]])


def test_create_sister_group_rejects_unknown_category(db, cats):
    with pytest.raises(ValueError, match="unknown category"):
        db.create_sister_group([cats[0], 9_999_999])


def test_create_sister_group_rejects_already_grouped(db, cats):
    db.create_sister_group([cats[0], cats[1]])
    with pytest.raises(ValueError, match="already in group"):
        db.create_sister_group([cats[1], cats[2]])


def test_create_sister_group_rolls_back_on_failure(db, cats):
    """If validation fails partway, no half-created group survives."""
    db.create_sister_group([cats[0], cats[1]])
    before_count = int(db._conn().execute(
        "SELECT COUNT(*) FROM sister_groups").fetchone()[0])
    with pytest.raises(ValueError):
        db.create_sister_group([cats[2], cats[1]])    # cats[1] reused
    after_count = int(db._conn().execute(
        "SELECT COUNT(*) FROM sister_groups").fetchone()[0])
    assert after_count == before_count


# ── Sister group: delete ─────────────────────────────────────────────────


def test_delete_sister_group_cascades_members(db, cats):
    gid = db.create_sister_group([cats[0], cats[1], cats[2]])
    db.delete_sister_group(gid)
    members = db._conn().execute(
        "SELECT COUNT(*) FROM sister_group_members WHERE group_id = ?",
        [gid]).fetchone()[0]
    assert members == 0
    # And the group itself is gone
    assert db._conn().execute(
        "SELECT id FROM sister_groups WHERE id = ?", [gid]
    ).fetchone() is None


def test_delete_sister_group_idempotent(db):
    """Deleting a non-existent group is a no-op."""
    db.delete_sister_group(99_999_999)    # no exception


# ── Sister group: add / remove members ────────────────────────────────────


def _group_by_id(db, gid):
    """Helper — pull just the group with the given id from
    get_sister_groups(). Other tests may have left groups behind in
    the live DB, so we can't assume index [0] is ours."""
    return next(g for g in db.get_sister_groups() if g["id"] == gid)


def test_add_category_to_group_happy(db, cats):
    gid = db.create_sister_group([cats[0], cats[1]])
    db.add_category_to_sister_group(gid, cats[2])
    members = _group_by_id(db, gid)["categories"]
    assert len(members) == 3
    assert cats[2] in [c["id"] for c in members]


def test_add_category_to_group_idempotent(db, cats):
    """Adding a category already in this group is a no-op."""
    gid = db.create_sister_group([cats[0], cats[1]])
    db.add_category_to_sister_group(gid, cats[0])
    members = _group_by_id(db, gid)["categories"]
    assert len(members) == 2    # not duplicated


def test_add_category_rejects_when_in_another_group(db, cats):
    g1 = db.create_sister_group([cats[0], cats[1]])
    g2 = db.create_sister_group([cats[2], cats[3]])
    with pytest.raises(ValueError, match="already in sister group"):
        db.add_category_to_sister_group(g1, cats[2])


def test_add_category_rejects_unknown_group(db, cats):
    with pytest.raises(ValueError, match="does not exist"):
        db.add_category_to_sister_group(99_999_999, cats[0])


def test_add_category_rejects_unknown_category(db, cats):
    gid = db.create_sister_group([cats[0], cats[1]])
    with pytest.raises(ValueError, match="does not exist"):
        db.add_category_to_sister_group(gid, 99_999_999)


def test_add_category_enforces_5_cap(db, cats):
    """Group full at 5 → new add is rejected."""
    extra = db._conn().execute(
        "INSERT INTO categories (name) VALUES (?)",
        [f"phaseC-extra-{uuid.uuid4().hex[:8]}"]).lastrowid
    db._conn().commit()
    try:
        gid = db.create_sister_group(
            [cats[0], cats[1], cats[2], cats[3], cats[4]])
        with pytest.raises(ValueError, match="full"):
            db.add_category_to_sister_group(gid, int(extra))
    finally:
        db._conn().execute(
            "DELETE FROM categories WHERE id = ?", [int(extra)])
        db._conn().commit()


def test_remove_category_above_min(db, cats):
    gid = db.create_sister_group([cats[0], cats[1], cats[2]])
    db.remove_category_from_sister_group(gid, cats[0])
    members = _group_by_id(db, gid)["categories"]
    assert len(members) == 2
    assert cats[0] not in [c["id"] for c in members]


def test_remove_category_auto_deletes_group_below_min(db, cats):
    """Group falls to 1 member → auto-delete (1-member group is
    meaningless)."""
    gid = db.create_sister_group([cats[0], cats[1]])
    db.remove_category_from_sister_group(gid, cats[0])
    # cats[1] dropped from membership AND group itself deleted
    assert db._conn().execute(
        "SELECT id FROM sister_groups WHERE id = ?", [gid]
    ).fetchone() is None
    # cats[1] is now ungrouped, available for re-grouping
    assert db.get_sister_group_for_category(cats[1]) is None


# ── Sister pool lookup ──────────────────────────────────────────────────


def test_pool_returns_self_for_ungrouped_category(db, cats):
    assert db.get_sister_pool_for_category(cats[0]) == [cats[0]]


def test_pool_returns_full_group_for_grouped_category(db, cats):
    gid = db.create_sister_group([cats[0], cats[1], cats[2]])
    pool = db.get_sister_pool_for_category(cats[1])
    assert sorted(pool) == sorted([cats[0], cats[1], cats[2]])


def test_pool_includes_self_even_if_membership_inconsistent(db, cats):
    """Self always present in pool — defensive against data drift."""
    gid = db.create_sister_group([cats[0], cats[1]])
    # Manually remove cats[0] from the join table (bypass helper)
    db._conn().execute(
        "DELETE FROM sister_group_members "
        "WHERE category_id = ?", [cats[0]])
    db._conn().commit()
    # cats[0] looks ungrouped; pool is [self]
    assert db.get_sister_pool_for_category(cats[0]) == [cats[0]]


def test_group_lookup_for_category(db, cats):
    gid = db.create_sister_group([cats[0], cats[1]])
    assert db.get_sister_group_for_category(cats[0]) == gid
    assert db.get_sister_group_for_category(cats[2]) is None


# ── get_sister_groups join shape ────────────────────────────────────────


def test_get_sister_groups_includes_song_counts(db, cats):
    """get_sister_groups joins songs to surface total_songs per group."""
    # Seed 2 songs into cats[0]
    conn = db._conn()
    for i in range(2):
        conn.execute(
            "INSERT INTO songs (artist, title, category_id, "
            "is_enabled, file_path) VALUES (?, ?, ?, 1, ?)",
            [f"A-{i}", f"T-{i}", cats[0], f"/x/s{i}.mp3"])
    # Seed 1 song into cats[1]
    conn.execute(
        "INSERT INTO songs (artist, title, category_id, "
        "is_enabled, file_path) VALUES (?, ?, ?, 1, ?)",
        ["A-3", "T-3", cats[1], "/x/s3.mp3"])
    conn.commit()
    try:
        gid = db.create_sister_group([cats[0], cats[1]])
        target = _group_by_id(db, gid)
        assert target["total_songs"] == 3
    finally:
        # cleanup
        conn.execute(
            "DELETE FROM songs WHERE category_id IN (?, ?)",
            [cats[0], cats[1]])
        conn.commit()


# ── AI Rotation Plan envelope ───────────────────────────────────────────


def test_plan_get_or_create_is_idempotent(db):
    plan_date = "2026-05-15"
    p1 = db.get_or_create_ai_rotation_plan(plan_date)
    p2 = db.get_or_create_ai_rotation_plan(plan_date)
    assert p1 == p2
    # Cleanup
    db._conn().execute(
        "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
        [plan_date])
    db._conn().commit()


def test_plan_rejects_bad_date(db):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        db.get_or_create_ai_rotation_plan("15/5/2026")


def test_plan_reset_wipes_decisions(db, a_clock):
    plan_date = "2026-05-16"
    plan_id = db.get_or_create_ai_rotation_plan(plan_date)
    db.add_rotation_decision(
        plan_id=plan_id, decision_date=plan_date,
        clock_id=a_clock, hour=10, song_id=None, action="rest",
        reason="test")
    assert len(db.get_rotation_decisions_for_date(plan_date)) == 1
    db.reset_ai_rotation_plan(plan_date)
    assert db.get_rotation_decisions_for_date(plan_date) == []
    # Cleanup
    db._conn().execute(
        "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
        [plan_date])
    db._conn().commit()


def test_plan_approve_stamps_status(db):
    plan_date = "2026-05-17"
    db.get_or_create_ai_rotation_plan(plan_date)
    db.mark_ai_rotation_plan_approved(plan_date)
    plan = db.get_ai_rotation_plan(plan_date)
    assert plan["status"] == "approved"
    assert plan["approved_at"] is not None
    db._conn().execute(
        "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
        [plan_date])
    db._conn().commit()


def test_plan_discard_wipes_decisions_and_stamps_status(db, a_clock):
    plan_date = "2026-05-18"
    plan_id = db.get_or_create_ai_rotation_plan(plan_date)
    db.add_rotation_decision(
        plan_id=plan_id, decision_date=plan_date,
        clock_id=a_clock, hour=10, song_id=None, action="rest")
    db.mark_ai_rotation_plan_discarded(plan_date)
    plan = db.get_ai_rotation_plan(plan_date)
    assert plan["status"] == "discarded"
    assert plan["discarded_at"] is not None
    # Decisions wiped
    assert db.get_rotation_decisions_for_date(plan_date) == []
    db._conn().execute(
        "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
        [plan_date])
    db._conn().commit()


def test_plan_auto_applied_stamps_without_wiping(db, a_clock):
    """5-PM safety net path — decisions stay, status=auto_applied."""
    plan_date = "2026-05-19"
    plan_id = db.get_or_create_ai_rotation_plan(plan_date)
    db.add_rotation_decision(
        plan_id=plan_id, decision_date=plan_date,
        clock_id=a_clock, hour=10, song_id=None, action="rest")
    db.mark_ai_rotation_plan_auto_applied(plan_date)
    plan = db.get_ai_rotation_plan(plan_date)
    assert plan["status"] == "auto_applied"
    # Decisions still present
    assert len(db.get_rotation_decisions_for_date(plan_date)) == 1
    db._conn().execute(
        "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
        [plan_date])
    db._conn().commit()


def test_get_plan_returns_none_if_absent(db):
    assert db.get_ai_rotation_plan("2099-01-01") is None


# ── Decisions: validation + insert ──────────────────────────────────────


def test_decision_action_validated(db, a_clock):
    plan_date = "2026-05-20"
    plan_id = db.get_or_create_ai_rotation_plan(plan_date)
    with pytest.raises(ValueError, match="action"):
        db.add_rotation_decision(
            plan_id=plan_id, decision_date=plan_date,
            clock_id=a_clock, hour=10, song_id=None, action="zombie")
    db._conn().execute(
        "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
        [plan_date])
    db._conn().commit()


def test_decision_hour_validated(db, a_clock):
    plan_date = "2026-05-21"
    plan_id = db.get_or_create_ai_rotation_plan(plan_date)
    with pytest.raises(ValueError, match="hour"):
        db.add_rotation_decision(
            plan_id=plan_id, decision_date=plan_date,
            clock_id=a_clock, hour=25, song_id=None, action="rest")
    db._conn().execute(
        "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
        [plan_date])
    db._conn().commit()


def test_decisions_for_date_joins_song_and_clock_meta(db, a_clock, cats):
    plan_date = "2026-05-22"
    plan_id = db.get_or_create_ai_rotation_plan(plan_date)
    # Seed a song so the join has data
    conn = db._conn()
    song_id = int(conn.execute(
        "INSERT INTO songs (artist, title, category_id, "
        "is_enabled, file_path) VALUES (?, ?, ?, 1, ?)",
        ["A1", "T1", cats[0], "/x/a.mp3"]).lastrowid)
    conn.commit()
    try:
        db.add_rotation_decision(
            plan_id=plan_id, decision_date=plan_date,
            clock_id=a_clock, hour=10, song_id=song_id,
            action="rest", source_category_id=cats[0],
            reason="slot_age=1")
        rows = db.get_rotation_decisions_for_date(plan_date)
        assert len(rows) == 1
        r = rows[0]
        assert r["song_title"] == "T1"
        assert r["song_artist"] == "A1"
        assert r["clock_name"] is not None    # join populated
        assert r["source_category_name"] is not None
        assert r["action"] == "rest"
        assert r["reason"] == "slot_age=1"
    finally:
        # ORDER MATTERS — ai_rotation_decisions.song_id REFERENCES
        # songs(id) without CASCADE, so the plan (which cascades the
        # decisions) must be deleted BEFORE the song row.
        conn.execute(
            "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
            [plan_date])
        conn.execute("DELETE FROM songs WHERE id = ?", [song_id])
        conn.commit()


def test_decisions_for_clock_scoped(db, a_clock):
    plan_date = "2026-05-23"
    plan_id = db.get_or_create_ai_rotation_plan(plan_date)
    # Create another clock for cross-filter check
    conn = db._conn()
    other_clock = int(conn.execute(
        "INSERT INTO clocks (name, is_active) VALUES (?, 1)",
        [f"phaseC-other-{uuid.uuid4().hex[:8]}"]).lastrowid)
    conn.commit()
    try:
        db.add_rotation_decision(
            plan_id=plan_id, decision_date=plan_date,
            clock_id=a_clock, hour=10, song_id=None, action="rest")
        db.add_rotation_decision(
            plan_id=plan_id, decision_date=plan_date,
            clock_id=other_clock, hour=10, song_id=None, action="rest")
        rows = db.get_rotation_decisions_for_clock(a_clock, plan_date)
        assert len(rows) == 1
        assert int(rows[0]["clock_id"]) == a_clock
    finally:
        conn.execute("DELETE FROM clocks WHERE id = ?", [other_clock])
        conn.execute(
            "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
            [plan_date])
        conn.commit()


def test_plan_stats_update(db, a_clock):
    plan_date = "2026-05-24"
    plan_id = db.get_or_create_ai_rotation_plan(plan_date)
    db.update_ai_rotation_plan_stats(
        plan_id, rested=7, promoted=5, clocks_balanced=3, errors=0)
    plan = db.get_ai_rotation_plan(plan_date)
    assert plan["rested_count"] == 7
    assert plan["promoted_count"] == 5
    assert plan["clocks_balanced"] == 3
    assert plan["total_changes"] == 12    # rested + promoted
    db._conn().execute(
        "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
        [plan_date])
    db._conn().commit()


def test_purge_old_plans(db, a_clock):
    """Plans older than retention_days deleted; cascade wipes their
    decisions too."""
    old_date = (date.today() - timedelta(days=20)).isoformat()
    recent_date = (date.today() - timedelta(days=3)).isoformat()
    p_old = db.get_or_create_ai_rotation_plan(old_date)
    p_new = db.get_or_create_ai_rotation_plan(recent_date)
    # Seed decisions on both
    db.add_rotation_decision(
        plan_id=p_old, decision_date=old_date,
        clock_id=a_clock, hour=10, song_id=None, action="rest")
    db.add_rotation_decision(
        plan_id=p_new, decision_date=recent_date,
        clock_id=a_clock, hour=10, song_id=None, action="rest")
    deleted = db.purge_old_rotation_decisions(retention_days=14)
    assert deleted >= 1
    # Old plan gone
    assert db.get_ai_rotation_plan(old_date) is None
    # Recent plan untouched
    assert db.get_ai_rotation_plan(recent_date) is not None
    # Cleanup
    db._conn().execute(
        "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
        [recent_date])
    db._conn().commit()


# ── Time-Slot Freshness input ───────────────────────────────────────────


def test_last_played_in_hour_returns_none_when_never(db):
    """Brand new song has no broadcast_log entries — returns None."""
    conn = db._conn()
    song_id = int(conn.execute(
        "INSERT INTO songs (artist, title, is_enabled, file_path) "
        "VALUES (?, ?, 1, ?)",
        [f"phaseC-A-{uuid.uuid4().hex[:6]}",
         f"phaseC-T-{uuid.uuid4().hex[:6]}",
         "/x/n.mp3"]).lastrowid)
    conn.commit()
    try:
        assert db.get_song_last_played_in_hour(song_id, 10) is None
    finally:
        conn.execute("DELETE FROM songs WHERE id = ?", [song_id])
        conn.commit()


def test_last_played_in_hour_returns_iso_date(db):
    """A song played at 10:23 today returns today's date for hour=10
    (and None for any other hour)."""
    conn = db._conn()
    song_id = int(conn.execute(
        "INSERT INTO songs (artist, title, is_enabled, file_path) "
        "VALUES (?, ?, 1, ?)",
        ["phaseC-A", "phaseC-T", "/x/s.mp3"]).lastrowid)
    conn.commit()
    # Stamp a played_at AT 10:23 today
    today_10 = datetime.now().replace(
        hour=10, minute=23, second=15).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO broadcast_log "
        "(entry_type, song_id, played_at, duration_ms) "
        "VALUES ('song', ?, ?, 180000)",
        [song_id, today_10])
    conn.commit()
    try:
        d = db.get_song_last_played_in_hour(song_id, 10)
        assert d == date.today().isoformat()
        # Other hours → None
        assert db.get_song_last_played_in_hour(song_id, 11) is None
        assert db.get_song_last_played_in_hour(song_id, 9) is None
    finally:
        conn.execute(
            "DELETE FROM broadcast_log WHERE song_id = ?", [song_id])
        conn.execute("DELETE FROM songs WHERE id = ?", [song_id])
        conn.commit()


def test_last_played_in_hour_weekday_agnostic(db):
    """Operator's D2 = (b) — weekday is NOT a discriminator. A song
    played Monday 10 AM should still show in the 10-hour slot when
    queried on Friday."""
    conn = db._conn()
    song_id = int(conn.execute(
        "INSERT INTO songs (artist, title, is_enabled, file_path) "
        "VALUES (?, ?, 1, ?)",
        ["phaseC-WD-A", "phaseC-WD-T", "/x/wd.mp3"]).lastrowid)
    conn.commit()
    # Stamp two plays at hour 10 — Monday + Friday last week
    monday = (date.today() - timedelta(days=date.today().weekday() + 7))
    monday_10 = datetime.combine(
        monday, datetime.min.time()).replace(
            hour=10, minute=5).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO broadcast_log "
        "(entry_type, song_id, played_at, duration_ms) "
        "VALUES ('song', ?, ?, 180000)",
        [song_id, monday_10])
    conn.commit()
    try:
        # Query — should find the Monday play even though today is
        # a different weekday
        d = db.get_song_last_played_in_hour(song_id, 10)
        assert d == monday.isoformat()
    finally:
        conn.execute(
            "DELETE FROM broadcast_log WHERE song_id = ?", [song_id])
        conn.execute("DELETE FROM songs WHERE id = ?", [song_id])
        conn.commit()


def test_last_played_in_hour_validates_hour(db):
    with pytest.raises(ValueError, match="hour"):
        db.get_song_last_played_in_hour(1, 25)
    with pytest.raises(ValueError, match="hour"):
        db.get_song_last_played_in_hour(1, -1)
