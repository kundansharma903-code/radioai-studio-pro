"""
SchedulerEngine.peek_next — read-only queue preview tests.

Studio v3's Up Coming panel reads the next N items the scheduler would
dispatch. The existing pick_next_item / pick_next_song are destructive
(advance _clock_slot_cursor), so calling them just for display would
make the broadcast skip slots. peek_next snapshots cursor state, calls
pick_next_item N times, and restores in a try/finally.

These tests verify:
  1. Returns up to N items.
  2. Does NOT advance _clock_slot_cursor (restored after call).
  3. Empty schedule returns [].
  4. Partial queue (fewer than N reachable items) returns the
     available count.
  5. The cursor sequence peek() walks matches what pick_next_item()
     would walk if called the same number of times — i.e., peek
     doesn't disturb the dispatch order. We compare slot_idx
     sequences rather than item identity because random_from_category
     slots use random.choice and may return different songs across
     calls; the CURSOR sequence is the deterministic invariant.

Pattern mirrors tests/test_scheduler_clock_wiring.py — uses the live
Database, sets up auto_schedule cells in deterministic (day, hour)
cells, cleans up in try/finally.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine


# ── Helpers (deliberately mirror test_scheduler_clock_wiring.py) ─────────


def _ensure_clock_with_n_song_slots(db: Database, n_slots: int = 5) -> int:
    """Create or reuse a clock with at least ``n_slots`` Song slots
    so peek_next has something to walk. Returns the clock id."""
    clocks = list(db.get_all_clocks())
    if clocks:
        cid = int(clocks[0]["id"])
    else:
        cid = db.create_clock("Peek Test Clock")

    existing = [dict(r) for r in db.get_clock_slots(cid)]
    n_song = sum(1 for s in existing
                 if (s.get("slot_type") or "").lower() == "song")
    if n_song < n_slots:
        # Append additional Song slots up to n_slots. Don't disturb
        # existing slots — that would corrupt other tests' state.
        slots = list(existing)
        while sum(1 for s in slots
                  if (s.get("slot_type") or "").lower() == "song") < n_slots:
            slots.append({
                "slot_type":   "Song",
                "category_id": None,
                "energy_pref": "Any",
                "vocal_pref":  "Any",
                "priority_pref": "Normal",
                "is_break":    0,
                "item_id":     0,
            })
        db.save_clock_slots(cid, slots)
    return cid


def _now_at(weekday: int, hour: int) -> datetime:
    """Datetime fixed to a known (weekday, hour) — drives
    pick_next_item / peek_next deterministically through the
    auto_schedule lookup."""
    base = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
    delta = (weekday - base.weekday()) % 7
    return base + timedelta(days=delta)


# ── 1. Returns up to N items ───────────────────────────────────────────


def test_peek_next_returns_n_items(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    cid = _ensure_clock_with_n_song_slots(db, n_slots=5)
    db.set_auto_schedule_cell(0, 6, cid)
    try:
        items = sch.peek_next(5, now=_now_at(0, 6))
        if not items:
            pytest.skip("no songs in DB to feed the picker")
        assert len(items) <= 5
        # Must be at least 1 (we've ensured 5 Song slots + the live DB
        # has 396 songs at baseline)
        assert len(items) >= 1
        # Each item carries the standard pick_next_item shape
        for it in items:
            assert "item_type" in it
            assert "slot_idx"  in it
            assert "clock_id" in it
            assert it["clock_id"] == cid
    finally:
        db.clear_auto_schedule_cell(0, 6)


# ── 2. Cursor not advanced ─────────────────────────────────────────────


def test_peek_next_does_not_advance_cursor(qtbot):
    """Bedrock invariant: after peek_next, the very next pick_next_item
    must return the SAME first item peek would have returned. If peek
    leaked any cursor mutation, pick would jump ahead."""
    db = Database()
    sch = SchedulerEngine(db=db)
    cid = _ensure_clock_with_n_song_slots(db, n_slots=5)
    db.set_auto_schedule_cell(1, 7, cid)
    try:
        # Snapshot all three state variables peek_next is supposed to
        # preserve — assert each one verbatim after the call.
        before_cursor = sch._clock_slot_cursor
        before_hour_key = sch._active_hour_key
        before_fired_breaks = set(sch._fired_breaks)

        peeked = sch.peek_next(5, now=_now_at(1, 7))
        if not peeked:
            pytest.skip("no songs in DB")

        # After peek_next, the hour-key may have updated to (1, 7)
        # because the inner pick_next_item runs the hour-rollover branch
        # — but the saved snapshot was taken BEFORE that call, and the
        # finally block restores it. So state must equal what we
        # snapshotted before peek.
        assert sch._clock_slot_cursor == before_cursor
        assert sch._active_hour_key == before_hour_key
        assert sch._fired_breaks == before_fired_breaks

        # Now actually call pick — the FIRST pick should return the
        # same slot_idx peek's first item targeted.
        first_pick = sch.pick_next_item(now=_now_at(1, 7))
        assert first_pick is not None
        assert first_pick["slot_idx"] == peeked[0]["slot_idx"]
    finally:
        db.clear_auto_schedule_cell(1, 7)


# ── 3. Empty schedule → [] ─────────────────────────────────────────────


def test_peek_next_with_empty_clock_returns_empty_list(qtbot):
    db = Database()
    sch = SchedulerEngine(db=db)
    # Deliberately use a (day, hour) cell with NO clock assigned.
    db.clear_auto_schedule_cell(6, 4)
    items = sch.peek_next(5, now=_now_at(6, 4))
    assert items == []


# ── 4. Partial queue → only-available count ────────────────────────────


def test_peek_next_with_partial_queue_returns_only_available(qtbot):
    """Build a clock with EXACTLY 2 reachable Song slots and ask for
    5. We expect ≤ 2 — the picker stops returning items once the
    cursor wraps and re-reaches the original position with no new
    output (current implementation breaks when item is None)."""
    db = Database()
    sch = SchedulerEngine(db=db)
    cid = db.create_clock("_test_peek_partial")
    try:
        db.save_clock_slots(cid, [
            {"slot_type": "Song", "is_break": 0, "category_id": None,
             "energy_pref": "Any", "vocal_pref": "Any",
             "priority_pref": "Normal", "item_id": 0},
            {"slot_type": "Song", "is_break": 0, "category_id": None,
             "energy_pref": "Any", "vocal_pref": "Any",
             "priority_pref": "Normal", "item_id": 0},
        ])
        db.set_auto_schedule_cell(2, 8, cid)
        try:
            items = sch.peek_next(5, now=_now_at(2, 8))
            if not items:
                pytest.skip("no songs in DB")
            # 2 distinct slots → at most 2 distinct slot_idx values in
            # the returned list. (Items may repeat song id if slots
            # share a category, but slot_idx values are bounded by
            # the slot count.)
            distinct_slot_idxs = set(it["slot_idx"] for it in items)
            assert distinct_slot_idxs.issubset({0, 1})
        finally:
            db.clear_auto_schedule_cell(2, 8)
    finally:
        # Clean up the test clock so it doesn't pollute the DB
        try:
            db._conn().execute(
                "DELETE FROM clock_slots WHERE clock_id = ?", [cid])
            db._conn().execute("DELETE FROM clocks WHERE id = ?", [cid])
            db._conn().commit()
        except Exception:
            pass


# ── 5. Order matches pick (slot_idx sequence) ──────────────────────────


def test_peek_next_items_match_pick_order(qtbot):
    """peek_next walks the same cursor sequence pick_next_item would
    walk if called the same number of times. We compare slot_idx
    sequences rather than item identity because random_from_category
    slots may return different songs each call (random.choice over
    the candidate set). The CURSOR sequence is the deterministic
    invariant that proves no slots got skipped."""
    db = Database()
    sch = SchedulerEngine(db=db)
    cid = _ensure_clock_with_n_song_slots(db, n_slots=5)
    db.set_auto_schedule_cell(3, 9, cid)
    try:
        # Take peek and snapshot what cursor sequence it walked
        peeked = sch.peek_next(5, now=_now_at(3, 9))
        if not peeked:
            pytest.skip("no songs in DB")
        peek_slot_idxs = [it["slot_idx"] for it in peeked]

        # Now actually walk pick_next_item the same number of times.
        # Cursor must end up walking the IDENTICAL slot_idx sequence,
        # which proves peek didn't skip any slot.
        picked = []
        for _ in range(len(peek_slot_idxs)):
            it = sch.pick_next_item(now=_now_at(3, 9))
            if it is None:
                break
            picked.append(it["slot_idx"])
        assert picked == peek_slot_idxs
    finally:
        db.clear_auto_schedule_cell(3, 9)
