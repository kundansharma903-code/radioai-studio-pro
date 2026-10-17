"""
Category air time applied to ANY clock (2026-10-16).

Operator rule: song category A tagged for 10 AM; clock abc (categories
B, C, D) sits on 10 AM → for that hour one of B / C / D, picked at
random, airs as A. The clock itself is never edited, other hours play
it as built, and pinned slots are never touched.

Two layers:
  • core.category_air_time — pure functions (no Qt, no DB)
  • SchedulerEngine.pick_next_item — the swap really reaches air
"""

from __future__ import annotations

from datetime import datetime

import pytest

from core.category_air_time import (
    AIR_TIME_FROM, apply_air_time, tagged_categories_at)


# ── Pure layer ──────────────────────────────────────────────────────────

A, B, C, D, E = 101, 102, 103, 104, 105


def _song(cat, **kw):
    s = {"slot_type": "song", "category_id": cat, "energy_pref": "High",
         "vocal_pref": "Female", "specific_song_id": None,
         "specific_artist_id": None, "filter_json": None, "item_id": 0}
    s.update(kw)
    return s


def _cats(slots):
    return [s["category_id"] for s in slots]


def _clock_bcd():
    return [{"slot_type": "sweeper", "category_id": None},
            _song(B), _song(C), {"slot_type": "jingle", "category_id": None},
            _song(D), _song(C)]


def test_tagged_categories_at_hour_and_day():
    parts = [{"category_id": A, "day_of_week": None,
              "hour_start": 10, "hour_end": 11},
             {"category_id": A, "day_of_week": None,
              "hour_start": 22, "hour_end": 23},
             {"category_id": E, "day_of_week": 1,       # Tuesday only
              "hour_start": 10, "hour_end": 11}]
    assert tagged_categories_at(parts, 0, 10) == [A]
    assert tagged_categories_at(parts, 1, 10) == [A, E]
    assert tagged_categories_at(parts, 0, 22) == [A]
    assert tagged_categories_at(parts, 0, 11) == []


def test_tagged_categories_overnight_wrap():
    parts = [{"category_id": A, "day_of_week": None,
              "hour_start": 23, "hour_end": 1}]
    assert tagged_categories_at(parts, 3, 23) == [A]
    assert tagged_categories_at(parts, 3, 0) == [A]
    assert tagged_categories_at(parts, 3, 1) == []


def test_one_whole_category_is_replaced():
    slots = _clock_bcd()
    out, swaps = apply_air_time(slots, [A], "2026-10-16|10|7")
    assert list(swaps) == [A]
    old = swaps[A]
    assert old in (B, C, D)
    # Every slot of the replaced category is now A; the rest untouched.
    expected = [None if c is None else (A if c == old else c)
                for c in _cats(slots)]
    assert _cats(out) == expected
    assert _cats(slots) == [None, B, C, None, D, C], "input not mutated"


def test_swapped_slot_is_marked_and_prefs_reset():
    out, swaps = apply_air_time(_clock_bcd(), [A], "seed",
                                names={A: "Category A"})
    swapped = [s for s in out if s.get("category_id") == A]
    assert swapped
    for s in swapped:
        assert s[AIR_TIME_FROM] == swaps[A]
        assert s["cat_name"] == "Category A"
        assert s["energy_pref"] == "Any" and s["vocal_pref"] == "Any"


def test_choice_is_stable_for_the_hour_and_varies_across_days():
    pick = lambda seed: apply_air_time(_clock_bcd(), [A], seed)[1][A]
    assert len({pick("2026-10-16|10|7") for _ in range(20)}) == 1
    days = {pick(f"2026-10-{d:02d}|10|7") for d in range(1, 29)}
    assert days == {B, C, D}, "over a month every category gets replaced"


def test_category_already_in_clock_changes_nothing():
    slots = _clock_bcd()
    out, swaps = apply_air_time(slots, [C], "seed")
    assert swaps == {} and out == slots


def test_pinned_slots_are_never_replaced():
    slots = [_song(B, specific_song_id=55), _song(C, filter_json='{"x":1}'),
             _song(D)]
    for d in range(1, 29):
        out, swaps = apply_air_time(slots, [A], f"2026-10-{d:02d}")
        assert swaps == {A: D}
        assert _cats(out) == [B, C, A]


def test_all_songs_slot_counts_as_a_choice():
    slots = [_song(None), _song(None)]
    out, swaps = apply_air_time(slots, [A], "seed")
    assert swaps == {A: None}
    assert _cats(out) == [A, A]


def test_two_tags_replace_two_different_categories():
    out, swaps = apply_air_time(_clock_bcd(), [A, E], "seed")
    assert set(swaps) == {A, E}
    assert swaps[A] != swaps[E]
    assert A in _cats(out) and E in _cats(out)


def test_more_tags_than_categories_places_what_fits():
    slots = [_song(B)]
    out, swaps = apply_air_time(slots, [A, E], "seed")
    assert len(swaps) == 1
    assert _cats(out)[0] in (A, E)


def test_clock_without_song_slots_is_untouched():
    slots = [{"slot_type": "jingle", "category_id": None}]
    out, swaps = apply_air_time(slots, [A], "seed")
    assert swaps == {} and out == slots


# ── Scheduler layer — the swap reaches air ─────────────────────────────


def _real_categories(db, n):
    rows = db._conn().execute(
        "SELECT category_id, COUNT(*) FROM songs WHERE is_enabled = 1 "
        "AND category_id IS NOT NULL GROUP BY category_id "
        "HAVING COUNT(*) >= 3 ORDER BY category_id").fetchall()
    cats = [int(r[0]) for r in rows]
    if len(cats) < n:
        pytest.skip(f"Need {n} categories with enabled songs")
    return cats[:n]


def _song_category(db, song_id):
    r = db._conn().execute("SELECT category_id FROM songs WHERE id = ?",
                           [int(song_id)]).fetchone()
    return int(r[0]) if r and r[0] is not None else None


@pytest.fixture
def engine_with_clock(monkeypatch):
    from core.database import Database
    from core.scheduler.engine import SchedulerEngine
    db = Database()
    cat_a, cat_b, cat_c, cat_d = _real_categories(db, 4)
    slots = [_song(cat_b, energy_pref="Any", vocal_pref="Any"),
             _song(cat_c, energy_pref="Any", vocal_pref="Any"),
             _song(cat_d, energy_pref="Any", vocal_pref="Any")]
    parts = [{"category_id": cat_a, "day_of_week": None,
              "hour_start": 10, "hour_end": 11, "category_name": "A"}]
    monkeypatch.setattr(db, "get_force_clock_for", lambda _now: None)
    monkeypatch.setattr(db, "get_active_clock",
                        lambda _d, _h: {"id": 777, "name": "abc"})
    monkeypatch.setattr(db, "get_clock_slots", lambda _cid: list(slots))
    monkeypatch.setattr(db, "get_all_category_dayparts", lambda: parts)
    eng = SchedulerEngine(db=db)
    return eng, db, (cat_a, cat_b, cat_c, cat_d), parts


def _aired_categories(eng, db, now, n=3):
    eng._active_hour_key = None
    return [_song_category(db, eng.pick_next_item(now)["item_id"])
            for _ in range(n)]


def test_tagged_hour_airs_the_tagged_category(engine_with_clock):
    eng, db, (a, b, c, d), _ = engine_with_clock
    aired = _aired_categories(eng, db, datetime(2026, 10, 16, 10, 5))
    assert a in aired, "category A must air in its tagged hour"
    assert sum(1 for x in (b, c, d) if x in aired) == 2, \
        "exactly one of B / C / D is replaced"


def test_untagged_hour_plays_clock_as_built(engine_with_clock):
    eng, db, (a, b, c, d), _ = engine_with_clock
    aired = _aired_categories(eng, db, datetime(2026, 10, 16, 15, 5))
    assert aired == [b, c, d]


def test_up_coming_preview_matches_what_airs(engine_with_clock):
    eng, db, *_ = engine_with_clock
    now = datetime(2026, 10, 16, 10, 5)
    eng._active_hour_key = None
    preview = [_song_category(db, it["item_id"])
               for it in eng.peek_next(3, now=now)]
    aired = [_song_category(db, eng.pick_next_item(now)["item_id"])
             for _ in range(3)]
    assert preview == aired


def test_tag_with_no_enabled_songs_is_ignored(engine_with_clock):
    eng, db, (a, b, c, d), parts = engine_with_clock
    parts[0]["category_id"] = 987654          # no songs in this category
    eng._air_time_at = -1e9                   # force re-read
    aired = _aired_categories(eng, db, datetime(2026, 10, 16, 10, 5))
    assert aired == [b, c, d]


def test_air_time_failure_never_breaks_dispatch(engine_with_clock,
                                               monkeypatch):
    eng, db, (a, b, c, d), _ = engine_with_clock

    def boom():
        raise RuntimeError("db blip")
    monkeypatch.setattr(db, "get_all_category_dayparts", boom)
    eng._air_time_at = -1e9
    aired = _aired_categories(eng, db, datetime(2026, 10, 16, 10, 5))
    assert aired == [b, c, d]
