"""
peek == pick for random slots (QA ⚠26, seen live 2026-10-19 15:58).

Every picker draws with random.choice, so the NEXT chip's peek, the Up
Coming peek and the real EOS pick each rolled their own item: the chip
said "Jingle _Retro02", the glowing card "_Retro01". Each cursor
position now resolves its random choice ONCE (keyed by hour, clock, slot
index and pick serial), so every preview of a position and the real pick
of it agree. Break slots are excluded (time-based, fired-set).
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine

_REAL = sys.executable      # a file that exists (memo re-check)


def _clock(db, slot_types) -> int:
    cid = int(db.create_clock(f"_test_peekpick_{datetime.now():%H%M%S%f}"))
    db.save_clock_slots(cid, [{
        "slot_type": t, "category_id": None, "energy_pref": "Any",
        "vocal_pref": "Any", "priority_pref": "Normal", "is_break": 0,
        "item_id": 0} for t in slot_types])
    return cid


@pytest.fixture
def env(qapp):
    db = Database()
    now = (datetime.now() + timedelta(days=7)).replace(
        hour=9, minute=40, second=0, microsecond=0)
    made = []

    def _make(slot_types):
        cid = _clock(db, slot_types)
        db.set_auto_schedule_cell(now.weekday(), now.hour, cid)
        made.append(cid)
        return cid
    yield db, now, _make
    db.clear_auto_schedule_cell(now.weekday(), now.hour)
    for cid in made:
        try:
            db.delete_clock(cid)
        except Exception:
            pass


def _ids(items):
    return [(i["slot_idx"], i.get("item_id"), i.get("title")) for i in items]


def test_random_picker_peek_matches_pick_synthetic(env, monkeypatch):
    """Force a picker that returns a different item on every call: the
    previews and the real picks must still agree position by position."""
    db, now, make = env
    make(["Jingle", "Jingle", "Jingle"])
    eng = SchedulerEngine(db=db)
    monkeypatch.setattr(eng, "_pick_jingle", lambda slot: {
        "item_type": "jingle", "item_id": random.randint(1, 10**9),
        "title": "J", "file_path": _REAL, "duration_ms": 8000})
    first = _ids(eng.peek_next(5, now=now))
    assert first == _ids(eng.peek_next(5, now=now))     # previews agree
    for expected in first:                              # and so do picks
        assert _ids([eng.pick_next_item(now=now)]) == [expected]


def test_after_a_pick_the_next_preview_still_matches(env, monkeypatch):
    db, now, make = env
    make(["Jingle", "Jingle"])
    eng = SchedulerEngine(db=db)
    monkeypatch.setattr(eng, "_pick_jingle", lambda slot: {
        "item_type": "jingle", "item_id": random.randint(1, 10**9),
        "title": "J", "file_path": _REAL, "duration_ms": 8000})
    preview = _ids(eng.peek_next(3, now=now))
    eng.pick_next_item(now=now)                 # first position consumed
    assert _ids(eng.peek_next(2, now=now)) == preview[1:3]
    # Consumed positions are pruned from the memo.
    assert all(k[3] >= eng._pick_serial for k in eng._pick_memo)


def test_real_jingle_rows_chip_card_and_air_agree(env):
    """Real _pick_jingle against the session DB copy."""
    db, now, make = env
    n = db._conn().execute("SELECT COUNT(*) FROM jingles").fetchone()[0]
    if n < 2:
        pytest.skip("need 2+ jingles in the DB copy for a random choice")
    make(["Jingle", "Jingle", "Jingle", "Jingle"])
    eng = SchedulerEngine(db=db)
    chip = _ids(eng.peek_next(5, now=now))
    if not chip:
        pytest.skip("no playable jingle files on this machine")
    card = _ids(eng.peek_next(5, now=now))
    aired = [_ids([eng.pick_next_item(now=now)])[0] for _ in chip]
    assert chip == card == aired


def test_break_slots_are_not_memoised(env, monkeypatch):
    db, now, make = env
    make(["Break", "Jingle"])
    eng = SchedulerEngine(db=db)
    calls = {"n": 0}

    def _brk(slot, _now):
        calls["n"] += 1
        return None                          # nothing due
    monkeypatch.setattr(eng, "_pick_break", _brk)
    monkeypatch.setattr(eng, "_pick_jingle", lambda slot: {
        "item_type": "jingle", "item_id": 1, "title": "J",
        "file_path": _REAL, "duration_ms": 8000})
    eng.peek_next(1, now=now)
    eng.peek_next(1, now=now)
    assert calls["n"] >= 2                   # re-evaluated every time
    assert not any(k[2] == 0 for k in eng._pick_memo)


# ── QA ⚠26 gap: a remembered choice must never air STALE ──────────────

def _first_song(eng, now):
    items = eng.peek_next(1, now=now)
    if not items or items[0].get("item_type") != "song":
        pytest.skip("no playable songs in the DB copy")
    return items[0]


def test_real_songs_peek_equals_pick(env):
    db, now, make = env
    make(["Song", "Song", "Song"])
    eng = SchedulerEngine(db=db)
    preview = _ids(eng.peek_next(3, now=now))
    if len(preview) < 3:
        pytest.skip("not enough playable songs in the DB copy")
    assert [_ids([eng.pick_next_item(now=now)])[0] for _ in preview] \
        == preview


def test_disabled_memoised_song_is_not_aired(env):
    db, now, make = env
    make(["Song"])
    eng = SchedulerEngine(db=db)
    chosen = _first_song(eng, now)
    sid = int(chosen["item_id"])
    conn = db._conn()
    conn.execute("UPDATE songs SET is_enabled = 0 WHERE id = ?", [sid])
    conn.commit()
    try:
        aired = eng.pick_next_item(now=now)
        assert aired is not None and int(aired["item_id"]) != sid
        assert aired["slot_idx"] == chosen["slot_idx"]   # same position
    finally:
        conn.execute("UPDATE songs SET is_enabled = 1 WHERE id = ?", [sid])
        conn.commit()


def test_manually_played_memoised_song_is_not_re_aired(env):
    """The operator plays the previewed song by hand (ADD / INSERT):
    the scheduler must not air it again at its slot position."""
    db, now, make = env
    make(["Song"])
    eng = SchedulerEngine(db=db)
    chosen = _first_song(eng, now)
    sid = int(chosen["item_id"])
    conn = db._conn()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rid = conn.execute(
        "INSERT INTO broadcast_log (entry_type, song_id, was_manual, "
        "played_at, actual_time, duration_ms) VALUES ('song', ?, 1, ?, ?, 0)",
        [sid, stamp, stamp]).lastrowid
    conn.commit()
    try:
        aired = eng.pick_next_item(now=now)
        assert aired is not None and int(aired["item_id"]) != sid
    finally:
        conn.execute("DELETE FROM broadcast_log WHERE id = ?", [rid])
        conn.commit()


def test_clock_edit_drops_the_memo(env, monkeypatch):
    """A clock save bumps data_generation → the next pick invalidates the
    rotation cache, which now also clears every remembered choice."""
    db, now, make = env
    cid = make(["Jingle", "Jingle", "Jingle"])
    eng = SchedulerEngine(db=db)
    monkeypatch.setattr(eng, "_pick_jingle", lambda slot: {
        "item_type": "jingle", "item_id": random.randint(1, 10**9),
        "title": "J", "file_path": _REAL, "duration_ms": 8000})
    eng.pick_next_item(now=now)                      # warm the engine
    eng.peek_next(3, now=now)
    old_future = {k for k in eng._pick_memo if k[3] > eng._pick_serial}
    assert old_future                                # positions remembered
    db.save_clock_slots(cid, [{
        "slot_type": "Jingle", "category_id": None, "energy_pref": "Any",
        "vocal_pref": "Any", "priority_pref": "Normal", "is_break": 0,
        "item_id": 0} for _ in range(3)])            # edit → generation++
    eng.pick_next_item(now=now)
    assert not (old_future & set(eng._pick_memo))
