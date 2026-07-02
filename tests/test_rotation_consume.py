"""
Rotation AI — scheduler-side consumption tests (BUG-2/BUG-3 fixes).

Covers SchedulerEngine._pick_song honoring an operator-approved daily
plan via Database.get_active_rotation_decisions:

  • plan 'pick'/'promote' decisions are honored FIRST (before the
    engine consult + the normal random+separation ladder)
  • plan 'rest' decisions are excluded from the normal ladder
  • never-stall rule: when rest-exclusion empties the candidate pool,
    _pick_song falls back unfiltered — broadcast never goes silent

Test strategy: the plan is created for TOMORROW and the scheduler's
pick context (`_current_pick_now`) is pinned to tomorrow noon, so the
tests never touch today's plan (which may hold real operator
decisions on the live dev DB). All seeded rows use unique uuid
prefixes and are cleaned up in fixture teardown.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine


class _StubRotationEngine:
    """Minimal handle satisfying what SchedulerEngine reads:
    is_enabled() gates _active_rotation_decisions; the live consult
    path (step 3.5) calls pick_song_for_clock — return None so tests
    exercise the plan-decision + ladder paths deterministically."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def pick_song_for_clock(self, **_kw):
        return None


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def plan_world(db, tmp_path):
    """Seed: temp category + 2 playable temp songs (real on-disk
    files) + temp clock + an ai_rotation_plans envelope for TOMORROW.
    Yields ids; the test adds its own decision rows + approves.

    Skips honestly if a plan for tomorrow already exists (never
    tamper with a row we didn't create)."""
    conn = db._conn()
    prefix = uuid.uuid4().hex[:8]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    if db.get_ai_rotation_plan(tomorrow) is not None:
        pytest.skip(
            f"a rotation plan for {tomorrow} already exists — "
            f"refusing to touch a row this test didn't create")

    cur = conn.execute(
        "INSERT INTO categories (name, color) VALUES (?, ?)",
        [f"consume-{prefix}", "#06b6d4"])
    cat_id = int(cur.lastrowid)
    song_ids: list[int] = []
    for i in ("X", "Y"):
        f = tmp_path / f"consume-{prefix}-{i}.mp3"
        f.write_bytes(b"\x00" * 256)
        cur = conn.execute(
            "INSERT INTO songs (artist, title, category_id, "
            "is_enabled, file_path, duration_ms) "
            "VALUES (?, ?, ?, 1, ?, 180000)",
            [f"consume-A{i}-{prefix}", f"consume-T{i}-{prefix}",
             cat_id, str(f)])
        song_ids.append(int(cur.lastrowid))
    cur = conn.execute(
        "INSERT INTO clocks (name, is_active) VALUES (?, 1)",
        [f"consume-clock-{prefix}"])
    clock_id = int(cur.lastrowid)
    conn.commit()

    plan_id = db.get_or_create_ai_rotation_plan(tomorrow)

    yield {
        "prefix":    prefix,
        "plan_date": tomorrow,
        "plan_id":   plan_id,
        "cat_id":    cat_id,
        "song_x":    song_ids[0],
        "song_y":    song_ids[1],
        "clock_id":  clock_id,
        "hour":      10,
    }

    # Cleanup — plan first (decisions FK-reference songs)
    try:
        conn.execute(
            "DELETE FROM ai_rotation_plans WHERE plan_date = ?",
            [tomorrow])
        conn.execute("DELETE FROM clocks WHERE id = ?", [clock_id])
        conn.execute("DELETE FROM songs WHERE id IN (?, ?)", song_ids)
        conn.execute("DELETE FROM categories WHERE id = ?", [cat_id])
        conn.commit()
    except Exception:
        conn.rollback()


def _make_scheduler(db, world) -> SchedulerEngine:
    """SchedulerEngine wired the way MainWindow does it, with pick
    context pinned to (tomorrow noon, temp clock, hour) — mirrors what
    pick_next_item stashes before dispatching to _pick_song."""
    sch = SchedulerEngine(db=db)
    sch.set_rotation_engine(_StubRotationEngine(enabled=True))
    sch._current_pick_clock_id = world["clock_id"]
    sch._current_pick_hour = world["hour"]
    sch._current_pick_now = datetime.combine(
        date.fromisoformat(world["plan_date"]),
        datetime.min.time()).replace(hour=12)
    return sch


def _song_slot(world) -> dict:
    return {
        "slot_type":            "Song",
        "selection_mode":       "random_from_category",
        "category_id":          world["cat_id"],
        "energy_pref":          "Any",
        "vocal_pref":           "Any",
        "item_id":              0,
        "fallback_category_id": None,
    }


# ── Plan-pick honored first ────────────────────────────────────────────


def test_scheduler_honors_plan_pick(qapp, db, plan_world):
    """An approved plan's 'pick' decision for the current (clock, hour)
    is what airs — _pick_song returns exactly that song."""
    w = plan_world
    db.add_rotation_decision(
        plan_id=w["plan_id"], decision_date=w["plan_date"],
        clock_id=w["clock_id"], hour=w["hour"],
        song_id=w["song_x"], action="pick", reason="consume test")
    db.mark_ai_rotation_plan_approved(w["plan_date"])

    sch = _make_scheduler(db, w)
    result = sch._pick_song(_song_slot(w))
    assert result is not None
    assert result["item_type"] == "song"
    assert result["item_id"] == w["song_x"], (
        f"plan pick (song {w['song_x']}) must be honored, "
        f"got {result['item_id']}")


def test_scheduler_ignores_pending_plan(qapp, db, plan_world):
    """Gate check end-to-end: a plan left 'pending' has NO authority —
    the pick falls through to the normal ladder (either pool song is
    acceptable, and the rest decision is NOT applied)."""
    w = plan_world
    db.add_rotation_decision(
        plan_id=w["plan_id"], decision_date=w["plan_date"],
        clock_id=w["clock_id"], hour=w["hour"],
        song_id=w["song_x"], action="rest", reason="consume test")
    # NOT approved — stays pending
    sch = _make_scheduler(db, w)
    seen = set()
    for _ in range(30):
        r = sch._pick_song(_song_slot(w))
        assert r is not None
        seen.add(int(r["item_id"]))
    # With no active plan, the rested song is still pickable
    assert seen <= {w["song_x"], w["song_y"]}
    assert w["song_x"] in seen, (
        "pending plan must not veto songs — rest applied despite "
        "status='pending'")


# ── Rest exclusion in the normal ladder ────────────────────────────────


def test_scheduler_excludes_rested_from_ladder(qapp, db, plan_world):
    """Approved plan rests song X; the category pool is {X, Y} →
    30 ladder picks never return X."""
    w = plan_world
    db.add_rotation_decision(
        plan_id=w["plan_id"], decision_date=w["plan_date"],
        clock_id=w["clock_id"], hour=w["hour"],
        song_id=w["song_x"], action="rest", reason="consume test")
    db.mark_ai_rotation_plan_approved(w["plan_date"])

    sch = _make_scheduler(db, w)
    for i in range(30):
        r = sch._pick_song(_song_slot(w))
        assert r is not None, f"pick {i} returned None"
        assert r["item_id"] != w["song_x"], (
            f"pick {i} returned the RESTED song {w['song_x']}")
        assert r["item_id"] == w["song_y"]


def test_scheduler_never_stalls_when_all_rested(qapp, db, plan_world):
    """Never-stall rule: when EVERY candidate is rested, _pick_song
    falls back unfiltered and still returns a song — the AI must never
    take the station silent."""
    w = plan_world
    for sid in (w["song_x"], w["song_y"]):
        db.add_rotation_decision(
            plan_id=w["plan_id"], decision_date=w["plan_date"],
            clock_id=w["clock_id"], hour=w["hour"],
            song_id=sid, action="rest", reason="consume test")
    db.mark_ai_rotation_plan_approved(w["plan_date"])

    sch = _make_scheduler(db, w)
    result = sch._pick_song(_song_slot(w))
    assert result is not None, (
        "all-rested pool must fall back unfiltered, not stall")
    assert result["item_type"] == "song"
    assert result["item_id"] in (w["song_x"], w["song_y"])
