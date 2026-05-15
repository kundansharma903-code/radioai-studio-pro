"""
Phase D — Rotation AI Engine tests.

Covers:
  • compute_weight pure math:
      - slot_age=0 → 0 (today veto)
      - slot_age=1 → 0.05 (yesterday penalty)
      - slot_age=never → 1.30 (boost)
      - primary boost ×1.2 multiplier
      - sister category gets ×1.0
      - 4-hour same-song veto fires
      - 1-hour same-artist veto fires
      - bad hour rejected
  • explain_weight returns structured breakdown for the UI
  • candidate_pool expands via sister-pool DB helper
  • pick_song_for_clock picks weighted-random, respects vetoes
  • pick returns None when pool empty + when all vetoed
  • compute_plan_for_date writes decisions for active clocks
  • compute_plan skips clocks with no slots / no category-id slots
  • compute_plan respects specific_song_id / specific_artist_id pins
  • compute_plan idempotent — re-running wipes prior decisions
  • Engine lifecycle start/stop/shutdown idempotent
  • Engine state transitions OFF → WARMING → ON; ERROR after exception
  • is_enabled gates on Settings key
  • Settings sentinels stamped after a successful tick

Tests use real DB + seeded categories + clocks + songs. Cleanup
via uuid prefixes + try/finally per repo convention.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Optional

import pytest

from core.database import Database


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seed_world(db):
    """Build a small but realistic test world:
      • 4 categories (Morning A/B/C/D) in a symmetric sister group
      • 1 standalone category (Late Night) — no group
      • 8 songs total (2 per Morning cat, 2 in Late Night)
      • 1 clock (Morning Mix) referencing Morning A as its primary
      • 1 standalone clock (Late Night Romance) referencing Late Night
      • auto_schedule cell: weekday=today @ hour=10 → Morning Mix
      • auto_schedule cell: weekday=today @ hour=21 → Late Night Romance

    Yields a dict with all the ids the test can address. Cleanup
    cascades via FK constraints — only top-level rows need explicit
    DELETE."""
    conn = db._conn()
    prefix = uuid.uuid4().hex[:8]

    # Categories
    cat_ids: dict[str, int] = {}
    for label in ("MA", "MB", "MC", "MD", "LN"):
        cur = conn.execute(
            "INSERT INTO categories (name, color) VALUES (?, ?)",
            [f"phaseD-{label}-{prefix}", "#06b6d4"])
        cat_ids[label] = int(cur.lastrowid)
    conn.commit()

    # Sister group for the 4 Morning categories (skip LN)
    group_id = db.create_sister_group(
        [cat_ids["MA"], cat_ids["MB"], cat_ids["MC"], cat_ids["MD"]])

    # Songs — 2 per Morning category, 2 in Late Night
    song_ids: dict[str, int] = {}
    for cat_label, song_label in [
        ("MA", "MA1"), ("MA", "MA2"),
        ("MB", "MB1"), ("MB", "MB2"),
        ("MC", "MC1"), ("MC", "MC2"),
        ("MD", "MD1"), ("MD", "MD2"),
        ("LN", "LN1"), ("LN", "LN2"),
    ]:
        cur = conn.execute(
            "INSERT INTO songs (artist, title, category_id, "
            "is_enabled, file_path, duration_ms) "
            "VALUES (?, ?, ?, 1, ?, 180000)",
            [f"artist-{song_label}-{prefix}",
             f"title-{song_label}-{prefix}",
             cat_ids[cat_label],
             f"/x/{song_label}.mp3"])
        song_ids[song_label] = int(cur.lastrowid)
    conn.commit()

    # Clocks
    cur = conn.execute(
        "INSERT INTO clocks (name, is_active) VALUES (?, 1)",
        [f"phaseD-MorningMix-{prefix}"])
    morning_clock_id = int(cur.lastrowid)
    cur = conn.execute(
        "INSERT INTO clocks (name, is_active) VALUES (?, 1)",
        [f"phaseD-LateNight-{prefix}"])
    late_clock_id = int(cur.lastrowid)

    # Slot 1 on Morning clock — rotation-eligible song slot in MA
    conn.execute(
        "INSERT INTO clock_slots (clock_id, slot_type, category_id, "
        "slot_order, selection_mode) VALUES (?, 'Song', ?, 1, ?)",
        [morning_clock_id, cat_ids["MA"], "random_from_category"])
    # Slot 2 on Morning clock — pinned to a specific song (AI must
    # NOT override these)
    conn.execute(
        "INSERT INTO clock_slots (clock_id, slot_type, category_id, "
        "slot_order, selection_mode, specific_song_id) "
        "VALUES (?, 'Song', ?, 2, ?, ?)",
        [morning_clock_id, cat_ids["MA"], "specific",
         song_ids["MA1"]])
    # Slot on Late Night clock — rotation-eligible song slot in LN
    conn.execute(
        "INSERT INTO clock_slots (clock_id, slot_type, category_id, "
        "slot_order, selection_mode) VALUES (?, 'Song', ?, 1, ?)",
        [late_clock_id, cat_ids["LN"], "random_from_category"])
    conn.commit()

    # auto_schedule cells — today's weekday
    weekday = date.today().weekday()
    conn.execute(
        "INSERT INTO auto_schedule (clock_id, day_of_week, "
        "hour_start, hour_end) VALUES (?, ?, 10, 11)",
        [morning_clock_id, weekday])
    conn.execute(
        "INSERT INTO auto_schedule (clock_id, day_of_week, "
        "hour_start, hour_end) VALUES (?, ?, 21, 22)",
        [late_clock_id, weekday])
    conn.commit()

    seed = {
        "prefix": prefix,
        "cat_ids": cat_ids,
        "group_id": group_id,
        "song_ids": song_ids,
        "morning_clock_id": morning_clock_id,
        "late_clock_id": late_clock_id,
        "weekday": weekday,
    }
    yield seed

    # Cleanup
    try:
        # plans/decisions cascade on date — wipe today's plan first to
        # release song_id FKs on ai_rotation_decisions before song delete
        today_iso = date.today().isoformat()
        conn.execute(
            "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
            [today_iso])
        conn.execute(
            "DELETE FROM auto_schedule WHERE clock_id IN (?, ?)",
            [morning_clock_id, late_clock_id])
        conn.execute("DELETE FROM clocks WHERE id IN (?, ?)",
                      [morning_clock_id, late_clock_id])
        conn.execute(
            "DELETE FROM songs WHERE id IN ("
            + ",".join("?" * len(song_ids)) + ")",
            list(song_ids.values()))
        db.delete_sister_group(group_id)
        for cid in cat_ids.values():
            conn.execute("DELETE FROM categories WHERE id = ?", [cid])
        conn.commit()
    except Exception:
        conn.rollback()


def _seed_broadcast_play(db, song_id: int, hour: int,
                          days_ago: int = 0, minute: int = 0) -> None:
    """Stamp a broadcast_log row for ``song_id`` played at hour H of
    ``days_ago`` days ago. Used by weight tests to set up slot history."""
    target = (datetime.now() - timedelta(days=int(days_ago))).replace(
        hour=int(hour), minute=int(minute), second=0, microsecond=0)
    db._conn().execute(
        "INSERT INTO broadcast_log "
        "(entry_type, song_id, played_at, duration_ms) "
        "VALUES ('song', ?, ?, 180000)",
        [int(song_id), target.isoformat(timespec="seconds")])
    db._conn().commit()


def _clear_broadcast_log(db, song_ids: list) -> None:
    """Wipe broadcast_log rows for the given song ids (test cleanup)."""
    if not song_ids:
        return
    placeholders = ",".join("?" * len(song_ids))
    db._conn().execute(
        f"DELETE FROM broadcast_log WHERE song_id IN ({placeholders})",
        [int(s) for s in song_ids])
    db._conn().commit()


# ════════════════════════════════════════════════════════════════════════════
# compute_weight — pure algorithm
# ════════════════════════════════════════════════════════════════════════════


def test_weight_never_played_in_slot_gets_boost(db, seed_world):
    """Brand new song → slot_age = never → weight 1.30."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    song_id = s["song_ids"]["MA1"]
    w = eng.compute_weight(
        song_id=song_id,
        song_category_id=s["cat_ids"]["MA"],
        song_artist=None,
        primary_category_id=s["cat_ids"]["MA"],
        hour=10)
    # Boost ×1.2 over the never weight 1.30
    assert w == pytest.approx(RotationAIEngine.WEIGHT_NEVER
                                * RotationAIEngine.PRIMARY_BOOST)


def test_weight_played_today_hard_veto(db, seed_world):
    """Song played in same hour today → weight 0 (veto)."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    song_id = s["song_ids"]["MA1"]
    try:
        _seed_broadcast_play(db, song_id, hour=10, days_ago=0)
        w = eng.compute_weight(
            song_id=song_id,
            song_category_id=s["cat_ids"]["MA"],
            song_artist=None,
            primary_category_id=s["cat_ids"]["MA"],
            hour=10)
        # slot_age=0 → 0.00 → ALSO triggers 4-hour overall veto since
        # we just inserted a play. Result MUST be 0.0 either way.
        assert w == 0.0
    finally:
        _clear_broadcast_log(db, [song_id])


def test_weight_played_yesterday_heavy_penalty(db, seed_world):
    """slot_age=1 + no overall recency veto → weight 0.05 × boost."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    song_id = s["song_ids"]["MA1"]
    try:
        _seed_broadcast_play(db, song_id, hour=10, days_ago=1)
        w = eng.compute_weight(
            song_id=song_id,
            song_category_id=s["cat_ids"]["MA"],
            song_artist=None,
            primary_category_id=s["cat_ids"]["MA"],
            hour=10)
        # 0.05 × 1.2 (primary boost) = 0.06
        assert w == pytest.approx(0.05 * RotationAIEngine.PRIMARY_BOOST)
    finally:
        _clear_broadcast_log(db, [song_id])


def test_weight_played_3_days_ago_modest_recovery(db, seed_world):
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    song_id = s["song_ids"]["MA1"]
    try:
        _seed_broadcast_play(db, song_id, hour=10, days_ago=3)
        w = eng.compute_weight(
            song_id=song_id,
            song_category_id=s["cat_ids"]["MA"],
            song_artist=None,
            primary_category_id=s["cat_ids"]["MA"],
            hour=10)
        assert w == pytest.approx(0.60 * RotationAIEngine.PRIMARY_BOOST)
    finally:
        _clear_broadcast_log(db, [song_id])


def test_weight_played_7_days_ago_full_weight(db, seed_world):
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    song_id = s["song_ids"]["MA1"]
    try:
        _seed_broadcast_play(db, song_id, hour=10, days_ago=7)
        w = eng.compute_weight(
            song_id=song_id,
            song_category_id=s["cat_ids"]["MA"],
            song_artist=None,
            primary_category_id=s["cat_ids"]["MA"],
            hour=10)
        # Default weight 1.0 × boost 1.2
        assert w == pytest.approx(1.00 * RotationAIEngine.PRIMARY_BOOST)
    finally:
        _clear_broadcast_log(db, [song_id])


def test_weight_sister_category_no_boost(db, seed_world):
    """A song from Morning B picked into Morning A's clock → no boost."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    song_id = s["song_ids"]["MB1"]    # in MB
    w = eng.compute_weight(
        song_id=song_id,
        song_category_id=s["cat_ids"]["MB"],
        song_artist=None,
        primary_category_id=s["cat_ids"]["MA"],    # clock is MA
        hour=10)
    # Sister → boost 1.0 → weight = WEIGHT_NEVER (never played)
    assert w == pytest.approx(RotationAIEngine.WEIGHT_NEVER * 1.0)


def test_weight_4hour_same_song_veto(db, seed_world):
    """Even with high slot freshness, a song played <4h ago anywhere
    must return weight 0."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    song_id = s["song_ids"]["MA1"]
    try:
        # Played 1 hour ago at hour 9 — doesn't match hour 10 slot,
        # but the 4-hour overall rule should still veto
        now = datetime.now()
        target = now - timedelta(hours=1)
        db._conn().execute(
            "INSERT INTO broadcast_log (entry_type, song_id, "
            "played_at, duration_ms) "
            "VALUES ('song', ?, ?, 180000)",
            [song_id, target.isoformat(timespec="seconds")])
        db._conn().commit()
        w = eng.compute_weight(
            song_id=song_id,
            song_category_id=s["cat_ids"]["MA"],
            song_artist=None,
            primary_category_id=s["cat_ids"]["MA"],
            hour=10)
        assert w == 0.0
    finally:
        _clear_broadcast_log(db, [song_id])


def test_weight_1hour_same_artist_veto(db, seed_world):
    """Different song, but same artist, played in last hour → veto."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    artist_name = f"shared-artist-{s['prefix']}"
    # Update both MA1 + MA2 to share the same artist
    db._conn().execute(
        "UPDATE songs SET artist = ? WHERE id IN (?, ?)",
        [artist_name, s["song_ids"]["MA1"], s["song_ids"]["MA2"]])
    db._conn().commit()
    try:
        # MA1 played 30 min ago at hour 9
        now = datetime.now()
        target = now - timedelta(minutes=30)
        db._conn().execute(
            "INSERT INTO broadcast_log (entry_type, song_id, "
            "played_at, duration_ms) "
            "VALUES ('song', ?, ?, 180000)",
            [s["song_ids"]["MA1"],
             target.isoformat(timespec="seconds")])
        db._conn().commit()
        # MA2 — different song, same artist — should be vetoed
        w = eng.compute_weight(
            song_id=s["song_ids"]["MA2"],
            song_category_id=s["cat_ids"]["MA"],
            song_artist=artist_name,
            primary_category_id=s["cat_ids"]["MA"],
            hour=10)
        assert w == 0.0
    finally:
        _clear_broadcast_log(db,
            [s["song_ids"]["MA1"], s["song_ids"]["MA2"]])


def test_weight_rejects_bad_hour(db):
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    with pytest.raises(ValueError, match="hour"):
        eng.compute_weight(
            song_id=1, song_category_id=1, song_artist=None,
            primary_category_id=1, hour=25)


# ════════════════════════════════════════════════════════════════════════════
# explain_weight — structured breakdown for UI
# ════════════════════════════════════════════════════════════════════════════


def test_explain_returns_never_breakdown(db, seed_world):
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    out = eng.explain_weight(
        song_id=s["song_ids"]["MA1"],
        song_category_id=s["cat_ids"]["MA"],
        song_artist=None,
        primary_category_id=s["cat_ids"]["MA"],
        hour=10)
    assert out["slot_age_days"] is None    # never played
    assert out["slot_weight"] == RotationAIEngine.WEIGHT_NEVER
    assert out["boost"] == RotationAIEngine.PRIMARY_BOOST
    assert out["weight"] > 0
    assert out["veto_reason"] is None


def test_explain_surfaces_4hour_veto_reason(db, seed_world):
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    song_id = s["song_ids"]["MA1"]
    try:
        # 1 hour ago — triggers 4-hour rule
        now = datetime.now()
        target = now - timedelta(hours=1)
        db._conn().execute(
            "INSERT INTO broadcast_log (entry_type, song_id, "
            "played_at, duration_ms) "
            "VALUES ('song', ?, ?, 180000)",
            [song_id, target.isoformat(timespec="seconds")])
        db._conn().commit()
        out = eng.explain_weight(
            song_id=song_id,
            song_category_id=s["cat_ids"]["MA"],
            song_artist=None,
            primary_category_id=s["cat_ids"]["MA"],
            hour=10)
        assert out["weight"] == 0.0
        assert out["veto_reason"]
        assert "4h" in out["veto_reason"]
    finally:
        _clear_broadcast_log(db, [song_id])


# ════════════════════════════════════════════════════════════════════════════
# candidate_pool + pick_song_for_clock
# ════════════════════════════════════════════════════════════════════════════


def test_candidate_pool_expands_via_sister_group(db, seed_world):
    """Pool for Morning A must include songs from all 4 sister cats."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    pool = eng.candidate_pool(s["cat_ids"]["MA"])
    pool_ids = {int(p["id"]) for p in pool}
    # All 8 Morning songs (2 per cat × 4 cats) must be present
    for label in ("MA1", "MA2", "MB1", "MB2",
                    "MC1", "MC2", "MD1", "MD2"):
        assert s["song_ids"][label] in pool_ids, (
            f"missing {label} in pool")
    # LN songs must NOT be present (not in sister group)
    assert s["song_ids"]["LN1"] not in pool_ids
    assert s["song_ids"]["LN2"] not in pool_ids


def test_candidate_pool_ungrouped_returns_self_only(db, seed_world):
    """Late Night category is not in any sister group → pool is its
    own songs."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    pool = eng.candidate_pool(s["cat_ids"]["LN"])
    pool_ids = {int(p["id"]) for p in pool}
    assert pool_ids == {s["song_ids"]["LN1"], s["song_ids"]["LN2"]}


def test_pick_song_returns_eligible_from_pool(db, seed_world):
    """First call after seeding — no broadcast history exists for any
    sample song, so all candidates have weight > 0 and pick succeeds."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    pick = eng.pick_song_for_clock(
        clock_id=s["morning_clock_id"], hour=10,
        primary_category_id=s["cat_ids"]["MA"])
    assert pick is not None
    # Must be drawn from the Morning sister pool
    morning_ids = {s["song_ids"][k] for k in
                    ("MA1", "MA2", "MB1", "MB2",
                     "MC1", "MC2", "MD1", "MD2")}
    assert int(pick["id"]) in morning_ids


def test_pick_song_returns_none_when_all_vetoed(db, seed_world):
    """Stamp every song in the Morning pool with a play 1h ago → all
    vetoed by 4-hour rule → pick returns None (Phase E falls back)."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    pool_song_ids = [s["song_ids"][k] for k in
                       ("MA1", "MA2", "MB1", "MB2",
                        "MC1", "MC2", "MD1", "MD2")]
    try:
        now = datetime.now()
        target = now - timedelta(minutes=30)
        for sid in pool_song_ids:
            db._conn().execute(
                "INSERT INTO broadcast_log (entry_type, song_id, "
                "played_at, duration_ms) "
                "VALUES ('song', ?, ?, 180000)",
                [sid, target.isoformat(timespec="seconds")])
        db._conn().commit()
        pick = eng.pick_song_for_clock(
            clock_id=s["morning_clock_id"], hour=10,
            primary_category_id=s["cat_ids"]["MA"])
        assert pick is None
    finally:
        _clear_broadcast_log(db, pool_song_ids)


# ════════════════════════════════════════════════════════════════════════════
# compute_plan_for_date — engine writes decisions
# ════════════════════════════════════════════════════════════════════════════


def test_compute_plan_writes_decisions_for_active_clock(db, seed_world):
    """Plan for today should pick songs for Morning Mix (10 AM) +
    Late Night (9 PM). Decisions persist in ai_rotation_decisions."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    today = date.today().isoformat()
    plan_id = eng.compute_plan_for_date(today)
    assert plan_id > 0
    decisions = db.get_rotation_decisions_for_date(today)
    # Morning Mix has 1 rotation-eligible song slot (slot 2 is
    # specific_song_id pinned → skipped). Late Night has 1.
    # So we expect ≥ 2 'pick' decisions (one per slot per clock).
    pick_decisions = [d for d in decisions
                       if d["action"] in ("pick", "promote")]
    assert len(pick_decisions) >= 2


def test_compute_plan_skips_specific_song_pinned_slot(db, seed_world):
    """Slot 2 on Morning Mix has specific_song_id set — AI must not
    override. No decision should reference that slot's pinned song."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    today = date.today().isoformat()
    eng.compute_plan_for_date(today)
    decisions = db.get_rotation_decisions_for_date(today)
    # The pinned song is MA1 with slot_idx=2. Decisions for that
    # slot_idx must NOT exist on the morning clock.
    morning_slot2_decisions = [
        d for d in decisions
        if int(d["clock_id"]) == seed_world["morning_clock_id"]
        and int(d["slot_idx"] or 0) == 2
    ]
    assert morning_slot2_decisions == []


def test_compute_plan_idempotent_reset(db, seed_world):
    """Re-running compute_plan_for_date for the same date wipes the
    previous decisions and re-computes from scratch."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    today = date.today().isoformat()
    eng.compute_plan_for_date(today)
    first_count = len(db.get_rotation_decisions_for_date(today))
    eng.compute_plan_for_date(today)
    second_count = len(db.get_rotation_decisions_for_date(today))
    # Same world + same algorithm → identical decision count
    assert first_count == second_count


def test_compute_plan_updates_envelope_stats(db, seed_world):
    """After compute_plan, the envelope's counters should match the
    decisions: rested_count + promoted_count + clocks_balanced."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    today = date.today().isoformat()
    eng.compute_plan_for_date(today)
    plan = db.get_ai_rotation_plan(today)
    assert plan is not None
    decisions = db.get_rotation_decisions_for_date(today)
    rested_actual = sum(1 for d in decisions if d["action"] == "rest")
    promoted_actual = sum(1 for d in decisions if d["action"] == "promote")
    assert plan["rested_count"] == rested_actual
    assert plan["promoted_count"] == promoted_actual
    assert plan["total_changes"] == rested_actual + promoted_actual


def test_compute_plan_emits_rest_decisions_for_vetoed_primary_songs(
        db, seed_world):
    """Seed MA1 played today @ 10 AM → AI must record a 'rest'
    decision for MA1 on the Morning Mix clock at hour 10."""
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    s = seed_world
    try:
        _seed_broadcast_play(db, s["song_ids"]["MA1"], hour=10, days_ago=0)
        today = date.today().isoformat()
        eng.compute_plan_for_date(today)
        decisions = db.get_rotation_decisions_for_date(today)
        rest_ma1 = [d for d in decisions
                     if d["action"] == "rest"
                     and int(d["song_id"]) == s["song_ids"]["MA1"]
                     and int(d["clock_id"]) == s["morning_clock_id"]]
        assert rest_ma1, "expected rest decision for MA1 played today"
    finally:
        _clear_broadcast_log(db, [s["song_ids"]["MA1"]])


# ════════════════════════════════════════════════════════════════════════════
# Engine lifecycle
# ════════════════════════════════════════════════════════════════════════════


def test_engine_start_stop_idempotent(qapp, db):
    from core.rotation_ai_engine import RotationAIEngine, STATE_OFF
    eng = RotationAIEngine(db=db)
    assert not eng.is_running()
    assert eng.state() == STATE_OFF
    eng.start()
    assert eng.is_running()
    eng.start()    # idempotent
    assert eng.is_running()
    eng.stop()
    assert not eng.is_running()
    eng.stop()    # idempotent
    assert not eng.is_running()


def test_engine_state_transitions_to_warming_on_start(qapp, db, qtbot):
    """Boot transition: OFF → WARMING (first tick pending)."""
    from core.rotation_ai_engine import (
        RotationAIEngine, STATE_OFF, STATE_WARMING,
    )
    eng = RotationAIEngine(db=db)
    received: list[str] = []
    eng.engine_state_changed.connect(received.append)
    assert eng.state() == STATE_OFF
    eng.start()
    # Allow Qt event loop to process the queued state-change signal
    qtbot.wait(50)
    assert STATE_WARMING in received or eng.state() == STATE_WARMING
    eng.stop()


def test_engine_is_enabled_gates_on_settings(qapp, db):
    from core.settings import Settings
    from core.rotation_ai_engine import (
        RotationAIEngine, KEY_ENGINE_ENABLED,
    )
    eng = RotationAIEngine(db=db)
    # Default → enabled
    Settings().set(KEY_ENGINE_ENABLED, "1")
    assert eng.is_enabled() is True
    Settings().set(KEY_ENGINE_ENABLED, "0")
    assert eng.is_enabled() is False
    Settings().set(KEY_ENGINE_ENABLED, "1")    # restore


def test_engine_tick_stamps_settings_sentinels(qapp, db, seed_world):
    """After a successful tick, KEY_LAST_TICK_AT + KEY_LAST_PLAN_DATE
    + KEY_LAST_ERROR='' should be set."""
    from core.settings import Settings
    from core.rotation_ai_engine import (
        RotationAIEngine,
        KEY_LAST_TICK_AT, KEY_LAST_PLAN_DATE, KEY_LAST_ERROR,
    )
    eng = RotationAIEngine(db=db)
    Settings().set(KEY_LAST_ERROR, "stale-error")
    eng.tick()
    assert Settings().get(KEY_LAST_TICK_AT)
    assert Settings().get(KEY_LAST_PLAN_DATE) == date.today().isoformat()
    assert Settings().get(KEY_LAST_ERROR) == ""


def test_engine_tick_emits_tick_completed_signal(qapp, db, qtbot,
                                                    seed_world):
    from core.rotation_ai_engine import RotationAIEngine
    eng = RotationAIEngine(db=db)
    fired: list[tuple] = []
    eng.tick_completed.connect(
        lambda pid, summary: fired.append((int(pid), dict(summary))))
    eng.tick()
    qtbot.wait(20)
    assert fired, "tick_completed never fired"
    plan_id, summary = fired[0]
    assert plan_id > 0
    assert "rested" in summary
    assert "promoted" in summary
    assert "balanced" in summary


def test_engine_tick_state_becomes_on(qapp, db, seed_world):
    from core.rotation_ai_engine import RotationAIEngine, STATE_ON
    eng = RotationAIEngine(db=db)
    eng.tick()
    assert eng.state() == STATE_ON


def test_engine_tick_handles_db_error_without_crashing(qapp, db,
                                                          monkeypatch):
    """Force compute_plan_for_date to raise — engine state must flip
    to ERROR, error_occurred signal must fire, but engine stays
    instantiated (no exception escapes _on_tick)."""
    from core.rotation_ai_engine import RotationAIEngine, STATE_ERROR
    eng = RotationAIEngine(db=db)
    def boom(self_, plan_date):
        raise RuntimeError("simulated DB hiccup")
    monkeypatch.setattr(RotationAIEngine, "compute_plan_for_date", boom)
    errors: list[str] = []
    eng.error_occurred.connect(errors.append)
    # _on_tick wraps in try/except — should not raise
    eng._on_tick()
    assert eng.state() == STATE_ERROR
    assert errors, "error_occurred signal never fired"
    assert "simulated" in errors[0].lower()


def test_engine_tick_skipped_when_disabled(qapp, db, monkeypatch):
    """When the operator toggles the engine OFF, _on_tick should skip
    compute and flip state to OFF without raising."""
    from core.settings import Settings
    from core.rotation_ai_engine import (
        RotationAIEngine, STATE_OFF, KEY_ENGINE_ENABLED,
    )
    Settings().set(KEY_ENGINE_ENABLED, "0")
    try:
        eng = RotationAIEngine(db=db)
        called: list[bool] = []
        # Spy on tick — should NOT be called
        original_tick = eng.tick
        def spy(*a, **kw):
            called.append(True)
            return original_tick(*a, **kw)
        eng.tick = spy
        eng._on_tick()
        assert called == []
        assert eng.state() == STATE_OFF
    finally:
        Settings().set(KEY_ENGINE_ENABLED, "1")
