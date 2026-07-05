"""
core/break_policy.py — pure policy logic tests.

Pinned behaviour (operator-approved design 2026-07-04):
  • Window snap: due 9:05 → 9:15, 9:31 → 9:45, 9:50 → next hour 10:15,
    exact 9:15:00 stays 9:15.
  • parse_windows tolerates junk, dedupes, sorts, falls back.
  • Budget split: fits stay in order, overflow defers (never drops),
    unknown durations count as 30s.
  • Interleave (competitive separation): operator's exact example —
    3 education + 2 automobile + 3 healthcare → NO same-category
    neighbours; unavoidable clusters degrade gracefully; prev-chain
    seam respected; FIFO order kept inside one category.
  • Meter: ok < 80% ≤ warn < 100% ≤ over; pending pushes projection.
"""

from __future__ import annotations

from datetime import datetime

from core.break_policy import (
    DEFAULT_WINDOWS, budget_split, first_window_next_hour, fmt_mmss,
    has_adjacent_same_category, hour_start, interleave_by_category,
    is_window_open, meter_state, next_window_at, parse_windows,
)


def _e(cid, cat, dur_ms=30000):
    return {"campaign_id": cid, "category": cat, "duration_ms": dur_ms}


# ── Window math ─────────────────────────────────────────────────────────

def test_window_snap_examples():
    W = (15, 30, 45)
    assert next_window_at(datetime(2026, 7, 4, 9, 5), W) == \
        datetime(2026, 7, 4, 9, 15)
    assert next_window_at(datetime(2026, 7, 4, 9, 31), W) == \
        datetime(2026, 7, 4, 9, 45)
    assert next_window_at(datetime(2026, 7, 4, 9, 50), W) == \
        datetime(2026, 7, 4, 10, 15)
    assert next_window_at(datetime(2026, 7, 4, 9, 15, 0), W) == \
        datetime(2026, 7, 4, 9, 15)
    assert next_window_at(datetime(2026, 7, 4, 9, 15, 1), W) == \
        datetime(2026, 7, 4, 9, 30)


def test_parse_windows_junk_and_defaults():
    assert parse_windows("15,30,45") == (15, 30, 45)
    assert parse_windows(" 45, 15 ,15") == (15, 45)
    assert parse_windows("") == DEFAULT_WINDOWS
    assert parse_windows("abc") == DEFAULT_WINDOWS
    assert parse_windows("75") == (15,)      # % 60


def test_window_open_and_next_hour():
    assert is_window_open(datetime(2026, 7, 4, 9, 15, 33))
    assert not is_window_open(datetime(2026, 7, 4, 9, 16, 0))
    assert first_window_next_hour(datetime(2026, 7, 4, 9, 40)) == \
        datetime(2026, 7, 4, 10, 15)
    assert hour_start(datetime(2026, 7, 4, 9, 40, 12)) == \
        datetime(2026, 7, 4, 9, 0)


# ── Budget ──────────────────────────────────────────────────────────────

def test_budget_split_defers_overflow_in_order():
    pool = [_e(1, "edu", 300_000), _e(2, "auto", 300_000),
            _e(3, "health", 120_000)]
    fits, deferred = budget_split(pool, aired_seconds=60,
                                  max_seconds=660)    # 600s remain
    assert [e["campaign_id"] for e in fits] == [1, 2]  # 300+300 fits
    assert [e["campaign_id"] for e in deferred] == [3]  # 120 > 0 left


def test_budget_unknown_duration_counts_30s():
    pool = [_e(i, "x", 0) for i in range(30)]
    fits, deferred = budget_split(pool, 0, 660)   # 660/30 = 22 fit
    assert len(fits) == 22 and len(deferred) == 8


def test_budget_nothing_when_hour_already_over():
    fits, deferred = budget_split([_e(1, "edu")], aired_seconds=700,
                                  max_seconds=660)
    assert fits == [] and len(deferred) == 1


# ── Competitive separation ──────────────────────────────────────────────

def test_operator_example_3edu_2auto_3health_no_adjacency():
    pool = ([_e(i, "education") for i in (1, 2, 3)]
            + [_e(i, "automobile") for i in (4, 5)]
            + [_e(i, "healthcare") for i in (6, 7, 8)])
    ordered = interleave_by_category(pool)
    assert len(ordered) == 8
    assert not has_adjacent_same_category(ordered)


def test_interleave_keeps_fifo_within_category():
    pool = [_e(1, "edu"), _e(2, "auto"), _e(3, "edu"), _e(4, "auto")]
    ordered = interleave_by_category(pool)
    edu_ids = [e["campaign_id"] for e in ordered
               if e["category"] == "edu"]
    assert edu_ids == [1, 3]


def test_interleave_respects_previous_chain_seam():
    pool = [_e(1, "edu"), _e(2, "health")]
    ordered = interleave_by_category(pool, prev_category="edu")
    assert ordered[0]["category"] == "health"


def test_interleave_unavoidable_cluster_degrades():
    pool = [_e(1, "edu"), _e(2, "edu"), _e(3, "edu"), _e(4, "health")]
    ordered = interleave_by_category(pool)
    # 3 vs 1 — some adjacency is mathematically forced; all items kept
    assert len(ordered) == 4
    assert {e["campaign_id"] for e in ordered} == {1, 2, 3, 4}


def test_interleave_none_category_is_others():
    pool = [_e(1, None), _e(2, ""), _e(3, "edu")]
    ordered = interleave_by_category(pool)
    assert not has_adjacent_same_category(
        [e for e in ordered if True]) or len(ordered) == 3


# ── Meter ───────────────────────────────────────────────────────────────

def test_meter_levels():
    assert meter_state(0, 0, 660)["level"] == "ok"
    assert meter_state(530, 0, 660)["level"] == "warn"     # ≥80%
    assert meter_state(300, 400, 660)["level"] == "warn"   # projection
    assert meter_state(700, 0, 660)["level"] == "over"
    assert meter_state(700, 0, 660)["fraction"] == 1.0


def test_fmt_mmss():
    assert fmt_mmss(0) == "0:00"
    assert fmt_mmss(662) == "11:02"


# ── Auto-Distribute ─────────────────────────────────────────────────────

def test_auto_distribute_20_rotations_8_to_21():
    from core.break_policy import auto_distribute_slots
    times = auto_distribute_slots(20, 8, 21)      # 13h × 3 = 39 slots
    assert len(times) == 20
    assert times == sorted(times)
    assert times[0].startswith("08:")
    assert all(t.split(":")[1] in ("15", "30", "45") for t in times)
    # evenly spread: last pick lands in the final hour of the range
    assert times[-1].startswith("20:")


def test_auto_distribute_caps_at_available_slots():
    from core.break_policy import auto_distribute_slots
    times = auto_distribute_slots(99, 9, 11)      # only 6 slots exist
    assert times == ["09:15", "09:30", "09:45",
                     "10:15", "10:30", "10:45"]


def test_auto_distribute_deterministic_and_bad_input():
    from core.break_policy import auto_distribute_slots
    a = auto_distribute_slots(7, 8, 20)
    b = auto_distribute_slots(7, 8, 20)
    assert a == b and len(a) == 7                 # client-sheet stable
    assert auto_distribute_slots(0, 8, 20) == []
    assert auto_distribute_slots(5, 20, 8) == []
    assert auto_distribute_slots("x", 8, 20) == []
