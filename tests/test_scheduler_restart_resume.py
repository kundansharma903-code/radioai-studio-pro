"""
Restart safety of the scheduler (QA ⚠20 / ⚠23, operator-approved 2026-10-18).

⚠20: after a restart the clock resumed at slot 0 mid-hour, so top-of-hour
elements replayed. It now resumes from the Final Log: the newest
scheduler-dispatched broadcast_log row of the SAME clock in the CURRENT
local hour → cursor = slot_idx + 1. A normal hour rollover still resets
to slot 0 (⚠19, by design).

⚠23: _fired_breaks is in-memory only, so after a restart _pick_break
(every break earlier this hour is "due") and the spot_due tick re-aired
paid spots that had already gone out. Today's airings are now rebuilt
from broadcast_log, one airing per break.

Resume tests use the shielded session DB copy, with log rows inserted at
controlled LOCAL 'YYYY-MM-DD HH:MM:SS' times (the format played_at is
stored in). Break tests use a small fake DB so break times and airings
are exact. Each ⚠23 test also runs a control without the log airings,
proving the scenario really would re-air.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import core.scheduler.engine as engine_mod
from core.database import Database
from core.scheduler.engine import SchedulerEngine


# ── ⚠20 helpers: real (session-copy) DB ────────────────────────────────

def _clock_with_song_slots(db, n=5) -> int:
    cid = int(db.create_clock(f"_test_resume_{datetime.now():%H%M%S%f}"))
    db.save_clock_slots(cid, [{
        "slot_type": "Song", "category_id": None, "energy_pref": "Any",
        "vocal_pref": "Any", "priority_pref": "Normal", "is_break": 0,
        "item_id": 0} for _ in range(n)])
    return cid


def _future_hour(days_ahead=7, hour=9, minute=40) -> datetime:
    """A fixed local time on a future date, so no real play can land in
    the same hour and the grid cell is ours alone."""
    base = datetime.now() + timedelta(days=days_ahead)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _log(db, clock_id, slot_idx, played_at, was_manual=0,
         entry_type="song"):
    conn = db._conn()
    cur = conn.execute(
        "INSERT INTO broadcast_log (entry_type, clock_id, slot_idx, "
        "was_manual, played_at, actual_time, duration_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, 0)",
        [entry_type, clock_id, slot_idx, was_manual, played_at, played_at])
    conn.commit()
    return int(cur.lastrowid)


@pytest.fixture
def resume_env(qapp):
    db = Database()
    cid = _clock_with_song_slots(db, 5)
    now = _future_hour()
    db.set_auto_schedule_cell(now.weekday(), now.hour, cid)
    made: list[int] = []
    try:
        yield db, cid, now, made
    finally:
        conn = db._conn()
        for rid in made:
            conn.execute("DELETE FROM broadcast_log WHERE id = ?", [rid])
        conn.commit()
        db.clear_auto_schedule_cell(now.weekday(), now.hour)
        try:
            db.delete_clock(cid)
        except Exception:
            pass


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _first_pick_slot(db, now) -> int | None:
    item = SchedulerEngine(db=db).pick_next_item(now=now)
    if item is None:
        pytest.skip("no songs in the DB copy to feed the picker")
    return item["slot_idx"]


def test_resume_after_last_logged_slot(resume_env):
    db, cid, now, made = resume_env
    made.append(_log(db, cid, 1, _ts(now.replace(minute=12))))
    assert _first_pick_slot(db, now) == 2


def test_resume_uses_newest_row_and_wraps(resume_env):
    db, cid, now, made = resume_env
    made.append(_log(db, cid, 1, _ts(now.replace(minute=5))))
    made.append(_log(db, cid, 4, _ts(now.replace(minute=30))))
    assert _first_pick_slot(db, now) == 0          # (4 + 1) % 5


def test_no_rows_this_hour_starts_at_slot_0(resume_env):
    db, cid, now, made = resume_env
    assert _first_pick_slot(db, now) == 0


def test_previous_hour_row_is_ignored(resume_env):
    db, cid, now, made = resume_env
    made.append(_log(db, cid, 3, _ts(now.replace(minute=0)
                                     - timedelta(minutes=2))))
    assert _first_pick_slot(db, now) == 0


def test_previous_day_row_is_ignored_across_midnight(qapp):
    """Rows from 23:58 yesterday never resume the 00:xx clock."""
    db = Database()
    cid = _clock_with_song_slots(db, 5)
    now = _future_hour(hour=0, minute=5)
    db.set_auto_schedule_cell(now.weekday(), now.hour, cid)
    rid = _log(db, cid, 3, _ts(now.replace(minute=0) - timedelta(minutes=2)))
    try:
        assert _first_pick_slot(db, now) == 0
    finally:
        db._conn().execute("DELETE FROM broadcast_log WHERE id = ?", [rid])
        db._conn().commit()
        db.clear_auto_schedule_cell(now.weekday(), now.hour)
        db.delete_clock(cid)


def test_other_clock_and_manual_and_legacy_rows_are_ignored(resume_env):
    db, cid, now, made = resume_env
    other = _clock_with_song_slots(db, 5)
    t = _ts(now.replace(minute=20))
    try:
        made.append(_log(db, other, 3, t))             # another clock
        made.append(_log(db, cid, 3, t, was_manual=1))  # manual play
        made.append(_log(db, None, 3, t))               # legacy: no clock_id
        assert _first_pick_slot(db, now) == 0
    finally:
        conn = db._conn()
        for rid in made:
            conn.execute("DELETE FROM broadcast_log WHERE id = ?", [rid])
        conn.commit()
        made.clear()
        db.delete_clock(other)


def test_break_slot_spot_row_counts_for_resume(resume_env):
    """Break-slot spots are logged with clock_id/slot_idx (Studio deck
    path), so a restart right after a break resumes after it."""
    db, cid, now, made = resume_env
    made.append(_log(db, cid, 2, _ts(now.replace(minute=30)),
                     entry_type="spot"))
    assert _first_pick_slot(db, now) == 3


def test_resume_only_on_cold_start_not_on_rollover(resume_env):
    """A running engine that crosses into a new hour starts at slot 0,
    even if that hour already has log rows (⚠19 by design)."""
    db, cid, now, made = resume_env
    made.append(_log(db, cid, 1, _ts(now.replace(minute=12))))
    eng = SchedulerEngine(db=db)
    eng._active_hour_key = (now.weekday(), (now.hour - 1) % 24)  # warm
    item = eng.pick_next_item(now=now)
    if item is None:
        pytest.skip("no songs in the DB copy to feed the picker")
    assert item["slot_idx"] == 0


def test_peek_next_matches_first_real_pick_and_restores(resume_env):
    db, cid, now, made = resume_env
    made.append(_log(db, cid, 1, _ts(now.replace(minute=12))))
    eng = SchedulerEngine(db=db)
    preview = eng.peek_next(1, now=now)
    if not preview:
        pytest.skip("no songs in the DB copy to feed the picker")
    assert eng._active_hour_key is None and eng._clock_slot_cursor == 0
    assert preview[0]["slot_idx"] == 2
    assert eng.pick_next_item(now=now)["slot_idx"] == 2


def test_resume_compares_local_hour_strings(resume_env):
    """The window is the CURRENT LOCAL hour as a played_at-format string."""
    db, cid, now, made = resume_env
    since = now.strftime("%Y-%m-%d %H:00:00")
    made.append(_log(db, cid, 2, since))                    # exactly HH:00:00
    assert db.get_last_clock_slot_play(cid, since) == 2
    assert _first_pick_slot(db, now) == 3


# ── ⚠23 helpers: fake DB with exact breaks and airings ─────────────────

class _BreaksDB:
    def __init__(self, breaks, plays):
        self.breaks = list(breaks)          # [{"campaign_id", "break_time"}]
        self.plays = list(plays)            # [(campaign_id, played_at)]
        self.queries: list = []

    def get_active_breaks_for_day(self, _dow):
        return [{"campaign_name": f"Client {b['campaign_id']}", **b}
                for b in self.breaks]

    def get_spot_plays_between(self, start, end):
        self.queries.append((start, end))
        return [p for p in self.plays if start <= p[1] < end]

    def get_spot_files(self, _cid):
        return [{"file_path": "spot.mp3", "is_active": 1,
                 "duration_ms": 30000, "filename": "spot.mp3"}]


DAY = datetime(2026, 10, 19)              # a Monday, fixed for determinism


def _at(h, m, s=0, day=DAY):
    return day.replace(hour=h, minute=m, second=s)


def _picked_campaigns(eng, now):
    picked = []
    while True:
        item = eng._pick_break({"slot_type": "break"}, now)
        if item is None:
            return picked
        picked.append(item["campaign_id"])


def test_restart_0940_does_not_reair_0915_spot_via_break_slot(qapp):
    """The QA scenario: the 09:15 spot aired at 09:15; restart at 09:40."""
    breaks = [{"campaign_id": 19, "break_time": "09:15"}]
    # Control: without the log airing, the restarted engine re-airs it.
    assert _picked_campaigns(SchedulerEngine(db=_BreaksDB(breaks, [])),
                             _at(9, 40)) == [19]
    db = _BreaksDB(breaks, [(19, "2026-10-19 09:15:04")])
    assert _picked_campaigns(SchedulerEngine(db=db), _at(9, 40)) == []


class _FixedClock(datetime):
    fixed: datetime = DAY

    @classmethod
    def now(cls, tz=None):
        return cls.fixed


def _spot_due_after_restart(monkeypatch, db, now):
    monkeypatch.setattr(engine_mod, "datetime", _FixedClock)
    _FixedClock.fixed = now
    eng = SchedulerEngine(db=db)
    emitted: list = []
    eng.spot_due.connect(emitted.append)
    eng._dispatch_due_events()             # first tick after the restart
    return emitted


def test_restart_inside_tolerance_spot_due_does_not_refire(qapp, monkeypatch):
    """Restart 20 s after the 09:15 spot aired — still inside the ±30 s
    due window, so the tick would fire it again without the fix."""
    breaks = [{"campaign_id": 19, "break_time": "09:15"}]
    assert _spot_due_after_restart(
        monkeypatch, _BreaksDB(breaks, []), _at(9, 15, 25)) == [19]
    assert _spot_due_after_restart(
        monkeypatch, _BreaksDB(breaks, [(19, "2026-10-19 09:15:05")]),
        _at(9, 15, 25)) == []


def test_held_spot_not_yet_aired_is_not_marked_fired(qapp):
    """Break Policy held the 09:15 spot for a later window and it has
    NOT aired: no log row, so it must stay eligible after a restart."""
    breaks = [{"campaign_id": 19, "break_time": "09:15"}]
    eng = SchedulerEngine(db=_BreaksDB(breaks, []))
    assert _picked_campaigns(eng, _at(9, 40)) == [19]


def test_late_airing_counts_for_its_own_break_only(qapp):
    """Held 08:40 spot aired late at 09:16. It covers the 08:40 break
    only, so the campaign's 09:15 break is still owed."""
    breaks = [{"campaign_id": 19, "break_time": "08:40"},
              {"campaign_id": 19, "break_time": "09:15"}]
    db = _BreaksDB(breaks, [(19, "2026-10-19 09:16:00")])
    eng = SchedulerEngine(db=db)
    eng._seed_fired_from_log(_at(9, 40))
    assert (19, "08:40") in eng._fired_breaks
    assert (19, "09:15") not in eng._fired_breaks
    assert _picked_campaigns(eng, _at(9, 40)) == [19]


def test_future_break_never_marked(qapp):
    breaks = [{"campaign_id": 19, "break_time": "10:15"}]
    eng = SchedulerEngine(db=_BreaksDB(breaks, [(19, "2026-10-19 09:15:04")]))
    eng._seed_fired_from_log(_at(9, 40))
    assert not eng._fired_breaks


def test_midnight_window_strings_and_tolerance(qapp):
    """Day boundary: the query is local [00:00:00 - 30 s, next 00:00:00).
    An airing at 23:59:45 counts for today's 00:00 break; yesterday's
    23:50 airing does not count for today's 00:10 break."""
    day = datetime(2026, 10, 20)
    breaks = [{"campaign_id": 7, "break_time": "00:00"},
              {"campaign_id": 8, "break_time": "00:10"}]
    db = _BreaksDB(breaks, [(7, "2026-10-19 23:59:45"),
                            (8, "2026-10-19 23:50:00")])
    eng = SchedulerEngine(db=db)
    eng._seed_fired_from_log(_at(0, 20, day=day))
    assert db.queries == [("2026-10-19 23:59:30", "2026-10-21 00:00:00")]
    assert (7, "00:00") in eng._fired_breaks
    assert (8, "00:10") not in eng._fired_breaks


def test_peek_next_preview_also_skips_aired_break(qapp):
    """The Up Coming preview must not show an already-aired spot either:
    peek_next seeds the set before taking its simulation snapshot."""
    db = _BreaksDB([{"campaign_id": 19, "break_time": "09:15"}],
                   [(19, "2026-10-19 09:15:04")])
    eng = SchedulerEngine(db=db)
    eng._seed_fired_from_log(_at(9, 40))
    assert (19, "09:15") in eng._fired_snapshot()
    eng2 = SchedulerEngine(db=db)
    eng2._peek_local.fired = None
    # peek_next path: seeding happens before the snapshot
    eng2._seed_fired_from_log(_at(9, 40))
    eng2._peek_local.fired = eng2._fired_snapshot()
    try:
        assert eng2._pick_break({"slot_type": "break"}, _at(9, 40)) is None
    finally:
        eng2._peek_local.fired = None


def test_seeding_is_idempotent_per_day_and_tolerates_fake_dbs(qapp):
    class _NoHelperDB:
        def get_active_breaks_for_day(self, _dow):
            return [{"campaign_id": 1, "break_time": "09:00"}]
    eng = SchedulerEngine(db=_NoHelperDB())
    eng._seed_fired_from_log(_at(9, 40))           # no helper → no crash
    assert not eng._fired_breaks
    db = _BreaksDB([{"campaign_id": 19, "break_time": "09:15"}],
                   [(19, "2026-10-19 09:15:04")])
    eng = SchedulerEngine(db=db)
    eng._seed_fired_from_log(_at(9, 40))
    eng._seed_fired_from_log(_at(9, 41))
    assert len(db.queries) == 1                    # once per day
