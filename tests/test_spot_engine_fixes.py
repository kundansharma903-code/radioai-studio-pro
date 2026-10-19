"""
Spot / campaign engine fixes (2026-10-17).

Covers:
  1. SchedulerEngine.reload_breaks — in-place reload keeps _fired_breaks,
     emits queue_changed; failed load retries + emits error_occurred.
  2. peek_next never replaces/loses the real _fired_breaks set.
  3. _pick_break only takes DUE breaks and carries campaign_id.
  4. get_active_breaks_for_day honours start_date / end_date (localtime).
  5. Database.campaign_air_check — active / window / daily cap / min gap /
     max per break.
  6. Studio gate + campaign_id in broadcast_log for Break-slot spots.
  7. Play Report Scheduled mode clipped to the campaign window.
  8. delete_campaign stamps item_name before NULL-ing the FK.

Everything runs on an in-memory SQLite DB through a tiny fake object
that borrows the real Database methods — the live DB is never touched.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, date

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine


# ── In-memory DB fake ──────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE campaigns (
    id INTEGER PRIMARY KEY, name TEXT, category TEXT DEFAULT 'Commercials',
    start_date TEXT, end_date TEXT,
    contracted_plays_per_day INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    min_gap_minutes INTEGER DEFAULT 0, max_per_break INTEGER DEFAULT 0);
CREATE TABLE campaign_schedule (
    id INTEGER PRIMARY KEY, campaign_id INTEGER, day_of_week INTEGER,
    break_time TEXT, slot_order INTEGER DEFAULT 0, priority TEXT);
CREATE TABLE spot_files (
    id INTEGER PRIMARY KEY, campaign_id INTEGER, filename TEXT,
    file_path TEXT, duration_ms INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1, display_order INTEGER DEFAULT 0);
CREATE TABLE broadcast_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, entry_type TEXT,
    song_id INTEGER, campaign_id INTEGER, jingle_id INTEGER,
    duration_ms INTEGER, deck TEXT, was_manual INTEGER, operator TEXT,
    played_at TEXT, actual_time TEXT);
CREATE TABLE final_log_entries (id INTEGER PRIMARY KEY, campaign_id INTEGER);
"""


class _MemDB:
    """Borrows real Database methods, backed by one in-memory conn."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def _conn(self):
        return self.conn

    def _ensure_campaign_schedule_columns(self):
        pass

    _ensure_broadcast_log_columns = Database._ensure_broadcast_log_columns
    get_active_breaks_for_day = Database.get_active_breaks_for_day
    campaign_air_check = Database.campaign_air_check
    delete_campaign = Database.delete_campaign
    get_spot_files = Database.get_spot_files

    # helpers
    def add_campaign(self, cid, **kw):
        cols = {"id": cid, "name": f"C{cid}", **kw}
        self.conn.execute(
            f"INSERT INTO campaigns ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})", list(cols.values()))

    def add_play(self, cid, played_at, etype="spot", name=None):
        self.conn.execute(
            "INSERT INTO broadcast_log (entry_type, campaign_id, played_at) "
            "VALUES (?, ?, ?)",
            [etype, cid, played_at.strftime("%Y-%m-%d %H:%M:%S")])


def _today(offset_days=0) -> str:
    return (date.today() + timedelta(days=offset_days)).isoformat()


# ── 1. reload_breaks ───────────────────────────────────────────────────

class _BreaksDB:
    def __init__(self, rows):
        self.rows = rows
        self.fail = False

    def get_active_breaks_for_day(self, dow):
        if self.fail:
            raise sqlite3.OperationalError("database is locked")
        return [dict(r) for r in self.rows]


class _DictRow(dict):
    def keys(self):            # sqlite3.Row-ish
        return list(super().keys())


def _engine(db):
    return SchedulerEngine(db=db, tick_interval_ms=50)


def test_reload_breaks_in_place_keeps_fired_and_emits(qtbot):
    now = datetime.now()
    far = (now + timedelta(hours=2)).strftime("%H:%M:%S")
    db = _BreaksDB([_DictRow(campaign_id=1, break_time=far)])
    eng = _engine(db)
    eng._dispatch_due_events()                       # day load
    eng._fired_breaks.add((99, "00:00:00"))          # already-aired key
    db.rows = [_DictRow(campaign_id=1, break_time=far),
               _DictRow(campaign_id=2, break_time=far)]
    eng.reload_breaks()
    with qtbot.waitSignal(eng.queue_changed, timeout=1000):
        eng._dispatch_due_events()
    assert len(eng._loaded_breaks) == 2
    assert (99, "00:00:00") in eng._fired_breaks
    assert eng._breaks_dirty is False


def test_failed_load_retries_and_reports(qtbot):
    db = _BreaksDB([])
    db.fail = True
    eng = _engine(db)
    with qtbot.waitSignal(eng.error_occurred, timeout=1000) as blk:
        eng._dispatch_due_events()
    assert "retrying" in blk.args[0]
    assert eng._breaks_retry_at is not None
    # Not yet due → no retry on the next tick
    db.fail = False
    far = (datetime.now() + timedelta(hours=2)).strftime("%H:%M:%S")
    db.rows = [_DictRow(campaign_id=3, break_time=far)]
    eng._dispatch_due_events()
    assert eng._loaded_breaks == []
    # Retry deadline passes → loads
    eng._breaks_retry_at = 0.0
    eng._dispatch_due_events()
    assert len(eng._loaded_breaks) == 1
    assert eng._breaks_retry_at is None


# ── 2. peek_next race ──────────────────────────────────────────────────

def test_peek_next_never_loses_a_real_fired_key():
    db = _BreaksDB([])
    eng = _engine(db)
    eng._fired_breaks.add((1, "10:00:00"))

    def fake_pick(now=None):
        # Simulates the scheduler thread firing a break mid-peek.
        with eng._fired_lock:
            eng._fired_breaks.add((2, "10:05:00"))
        # And the simulated pick marks a key in the SIM set only.
        eng._peek_local.fired.add((3, "10:10:00"))
        return {"item_type": "song"}

    eng.pick_next_item = fake_pick      # type: ignore
    out = eng.peek_next(2)
    assert len(out) == 2
    assert (1, "10:00:00") in eng._fired_breaks
    assert (2, "10:05:00") in eng._fired_breaks      # not lost
    assert (3, "10:10:00") not in eng._fired_breaks  # sim didn't leak
    assert getattr(eng._peek_local, "fired", None) is None


# ── 3. _pick_break due filter + campaign_id ───────────────────────────

class _PickDB:
    def __init__(self, rows):
        self.rows = rows

    def get_active_breaks_for_day(self, dow):
        return self.rows

    def get_spot_files(self, cid):
        return [_DictRow(file_path=f"C:/spot{cid}.mp3", is_active=1,
                         duration_ms=30000)]


def test_pick_break_only_due_and_carries_campaign_id():
    now = datetime.now().replace(minute=20, second=0, microsecond=0)
    rows = [
        _DictRow(campaign_id=7, break_time="%02d:50" % now.hour,
                 campaign_name="Later"),
        _DictRow(campaign_id=8, break_time="%02d:20" % now.hour,
                 campaign_name="Due"),
    ]
    eng = _engine(_PickDB(rows))
    item = eng._pick_break(None, now)
    assert item is not None
    assert item["campaign_id"] == 8 and item["item_id"] == 8
    assert (8, "%02d:20" % now.hour) in eng._fired_breaks
    # The :50 break is NOT due at :20 → nothing more to pick
    assert eng._pick_break(None, now) is None


def test_pick_break_during_peek_uses_sim_set():
    now = datetime.now().replace(minute=20, second=0, microsecond=0)
    rows = [_DictRow(campaign_id=8, break_time="%02d:20" % now.hour,
                     campaign_name="Due")]
    eng = _engine(_PickDB(rows))
    eng._peek_local.fired = set()
    assert eng._pick_break(None, now)["campaign_id"] == 8
    assert eng._fired_breaks == set()
    eng._peek_local.fired = None


def test_next_break_info_and_skip():
    now = datetime.now().replace(minute=10, second=0, microsecond=0)
    bt = "%02d:40:00" % now.hour
    eng = _engine(_BreaksDB([]))
    eng._loaded_breaks = [{"campaign_id": 1, "break_time": bt,
                           "campaign_name": "A"},
                          {"campaign_id": 2, "break_time": bt,
                           "campaign_name": "B"}]
    info = eng.next_break_info(now)
    assert info["campaign_ids"] == [1, 2] and info["seconds"] == 1800
    assert len(eng.upcoming_breaks(1800, now)) == 2
    eng.skip_next_break(now)
    assert (1, bt) in eng._fired_breaks and (2, bt) in eng._fired_breaks
    assert eng.next_break_info(now) is None


# ── 4. get_active_breaks_for_day date window ──────────────────────────

def test_active_breaks_respect_start_and_end_dates():
    db = _MemDB()
    db.add_campaign(1)                                         # open
    db.add_campaign(2, start_date=_today(+1))                  # future
    db.add_campaign(3, end_date=_today(-1))                    # expired
    db.add_campaign(4, start_date="", end_date="Never")        # open
    db.add_campaign(5, start_date=_today(), end_date=_today())  # today only
    db.add_campaign(6, is_active=0)
    for cid in range(1, 7):
        db.conn.execute(
            "INSERT INTO campaign_schedule (campaign_id, day_of_week, "
            "break_time) VALUES (?, 2, '10:00')", [cid])
    got = {int(r["campaign_id"]) for r in db.get_active_breaks_for_day(2)}
    assert got == {1, 4, 5}


# ── 5. campaign_air_check ─────────────────────────────────────────────

def test_air_check_inactive_and_window():
    db = _MemDB()
    db.add_campaign(1, is_active=0)
    db.add_campaign(2, end_date=_today(-1))
    db.add_campaign(3, start_date=_today(+2))
    db.add_campaign(4, start_date="Never", end_date="")
    assert db.campaign_air_check(1)[0] is False
    assert db.campaign_air_check(2)[0] is False
    assert db.campaign_air_check(3)[0] is False
    assert db.campaign_air_check(4) == (True, "")
    assert db.campaign_air_check(999)[0] is False


def test_air_check_daily_cap_and_min_gap():
    db = _MemDB()
    now = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
    db.add_campaign(1, contracted_plays_per_day=2)
    db.add_play(1, now - timedelta(hours=3))
    assert db.campaign_air_check(1, now)[0] is True
    db.add_play(1, now - timedelta(hours=2))
    ok, why = db.campaign_air_check(1, now)
    assert ok is False and "daily limit" in why
    # Yesterday's plays don't count
    db.add_campaign(2, contracted_plays_per_day=1)
    db.add_play(2, now - timedelta(days=1))
    assert db.campaign_air_check(2, now)[0] is True
    # Min gap
    db.add_campaign(3, min_gap_minutes=30)
    db.add_play(3, now - timedelta(minutes=10))
    ok, why = db.campaign_air_check(3, now)
    assert ok is False and "min gap" in why
    assert db.campaign_air_check(3, now + timedelta(minutes=25))[0] is True


def test_air_check_grid_wins_unless_strict():
    """Programmed (scheduled) spots ignore play limits by default; the
    'strict' campaign_limits_mode setting makes the limits cap them too.
    Status + date window are always enforced."""
    db = _MemDB()
    db.conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    now = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
    db.add_campaign(1, contracted_plays_per_day=1, min_gap_minutes=30)
    db.add_play(1, now - timedelta(minutes=5))
    assert db.campaign_air_check(1, now)[0] is False            # extra play
    assert db.campaign_air_check(1, now, scheduled=True) == (True, "")
    db.add_campaign(2, is_active=0)
    assert db.campaign_air_check(2, now, scheduled=True)[0] is False
    db.conn.execute("INSERT INTO settings VALUES "
                    "('campaign_limits_mode', 'strict')")
    assert db.campaign_air_check(1, now, scheduled=True)[0] is False


def test_air_check_max_per_break_counts_since_last_song():
    db = _MemDB()
    now = datetime.now()
    db.add_campaign(1, max_per_break=1)
    db.add_play(None, now - timedelta(minutes=4), etype="song")
    assert db.campaign_air_check(1, now)[0] is True
    db.add_play(1, now - timedelta(minutes=1))
    ok, why = db.campaign_air_check(1, now)
    assert ok is False and "per break" in why
    db.add_play(None, now, etype="song")         # break chain ends
    assert db.campaign_air_check(1, now)[0] is True


# ── 6. Studio gate + broadcast_log campaign_id ────────────────────────

def test_studio_spot_due_gate_blocks_and_continues_chain():
    from ui.studio import Studio

    calls = []

    class _Fake:
        _campaign_may_air = Studio._campaign_may_air
        _engine = object()
        _playback_cid = None

        class _db:
            @staticmethod
            def campaign_air_check(cid):
                return False, "daily limit reached (3/3 plays today)"

        def _continue_chain_if_idle(self):
            calls.append("chain")

        def _break_policy_enabled(self):
            raise AssertionError("gate must run before the policy valve")

    Studio._do_scheduler_spot_due(_Fake(), 42)
    assert calls == ["chain"]


def test_studio_operator_override_bypasses_gate():
    from ui.studio import Studio

    class _Fake:
        _spot_limit_override = {42}

        class _db:
            @staticmethod
            def campaign_air_check(cid):
                return False, "nope"

    assert Studio._campaign_may_air(_Fake(), 42, "t") is True
    assert Studio._campaign_may_air(_Fake(), 41, "t") is False


def test_write_broadcast_log_passes_campaign_id_for_spots():
    from ui.studio import Studio

    logged = []

    class _Fake:
        _current_duration_ms = 30000
        _recent_song_logs: dict = {}

        class _db:
            @staticmethod
            def log_play(**kw):
                logged.append(kw)

    Studio._write_broadcast_log(_Fake(), {
        "id": 8, "title": "Client X", "_item_type": "spot",
        "_campaign_id": 8, "_clock_id": 3, "_slot_idx": 1})
    Studio._write_broadcast_log(_Fake(), {
        "id": 5, "title": "Song", "_item_type": "song"})
    assert logged[0]["campaign_id"] == 8
    assert logged[0]["item_name"] == "Client X"
    assert logged[1]["campaign_id"] is None


# ── 7. Play Report Scheduled mode clipped to campaign window ──────────

def test_scheduled_plays_clipped_to_campaign_window():
    from core.reports.spot_play_report import _fetch_scheduled_plays
    db = _MemDB()
    db.add_campaign(1, start_date="2026-10-05", end_date="2026-10-07")
    for dow in range(7):
        db.conn.execute(
            "INSERT INTO campaign_schedule (campaign_id, day_of_week, "
            "break_time) VALUES (1, ?, '09:00')", [dow])
    out = _fetch_scheduled_plays(db, 1, date(2026, 10, 1),
                                 date(2026, 10, 10), 1)
    with_plays = sorted(d for d, v in out.items() if v)
    assert with_plays == [date(2026, 10, 5), date(2026, 10, 6),
                          date(2026, 10, 7)]
    assert len(out) == 10           # days outside still listed, empty


# ── 8. delete_campaign keeps proof of play readable ───────────────────

def test_delete_campaign_stamps_item_name():
    db = _MemDB()
    db.add_campaign(1, name="Kisan Fertilisers")
    db.add_play(1, datetime.now())
    db.delete_campaign(1)
    row = db.conn.execute(
        "SELECT campaign_id, item_name FROM broadcast_log").fetchone()
    assert row["campaign_id"] is None
    assert row["item_name"] == "Kisan Fertilisers"
