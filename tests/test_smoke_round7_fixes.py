"""
Findings from the live smoke test of build 74ec334 (2026-10-19).

⚠30 Start-of-Song-type sweepers: they play OVER the next song only when
     the next pick happens by crossfade from a song. Chip and Up Coming
     now share that rule — overlay cards get no NEXT glow and no air time;
     after a jingle the sweeper plays on its own and IS next.
⚠31 Previews re-check remembered picks (a song that aired since is never
     shown again for a later position) and one preview never shows the
     same song twice.
⚠32 The NEXT chip refreshes whenever Up Coming reloads, so both name the
     same item.
⚠33 A clean exit folds the WAL into radioai.db and closes the DB.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

from core.database import Database
from core.scheduler.engine import SchedulerEngine
from tests.test_studio_settings_integration import (
    _FakeEngine, _FakeScheduler)

_REAL = sys.executable


# ── ⚠31: engine previews ──────────────────────────────────────────────

@pytest.fixture
def song_clock(qapp):
    db = Database()
    cid = int(db.create_clock(f"_test_r7_{datetime.now():%H%M%S%f}"))
    db.save_clock_slots(cid, [{
        "slot_type": "Song", "category_id": None, "energy_pref": "Any",
        "vocal_pref": "Any", "priority_pref": "Normal", "is_break": 0,
        "item_id": 0} for _ in range(3)])
    now = (datetime.now() + timedelta(days=7)).replace(
        hour=9, minute=40, second=0, microsecond=0)
    db.set_auto_schedule_cell(now.weekday(), now.hour, cid)
    made: list = []
    yield db, now, made
    conn = db._conn()
    for rid in made:
        conn.execute("DELETE FROM broadcast_log WHERE id = ?", [rid])
    conn.commit()
    db.clear_auto_schedule_cell(now.weekday(), now.hour)
    db.delete_clock(cid)


def _real_song_ids(db, n):
    ids = [int(r[0]) for r in db._conn().execute(
        "SELECT id FROM songs WHERE is_enabled = 1 ORDER BY id LIMIT ?",
        [n]).fetchall()]
    if len(ids) < n:
        pytest.skip("not enough songs in the DB copy")
    return ids


def test_one_preview_never_shows_the_same_song_twice(song_clock,
                                                     monkeypatch):
    db, now, _ = song_clock
    a, b = _real_song_ids(db, 2)
    seq = iter([a, a, a, b, b, b])       # the picker keeps offering A first
    eng = SchedulerEngine(db=db)
    monkeypatch.setattr(eng, "_pick_song", lambda slot: {
        "item_type": "song", "item_id": next(seq), "title": "S",
        "file_path": _REAL, "duration_ms": 180_000})
    ids = [i["item_id"] for i in eng.peek_next(2, now=now)]
    assert ids[0] == a and ids[1] != a


def test_preview_drops_a_remembered_song_that_has_aired(song_clock):
    """The 17:00 → 17:05 Mehrama case: a later position remembered song X;
    X then airs → the next preview must not show X there any more."""
    db, now, made = song_clock
    eng = SchedulerEngine(db=db)
    first = eng.peek_next(3, now=now)
    if len(first) < 3:
        pytest.skip("not enough playable songs in the DB copy")
    x = int(first[2]["item_id"])
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db._conn()
    made.append(conn.execute(
        "INSERT INTO broadcast_log (entry_type, song_id, was_manual, "
        "played_at, actual_time, duration_ms) VALUES ('song', ?, 0, ?, ?, 0)",
        [x, stamp, stamp]).lastrowid)
    conn.commit()
    again = eng.peek_next(3, now=now)
    assert int(again[2]["item_id"]) != x
    # …and the real pick for that position agrees with the new preview.
    picks = [eng.pick_next_item(now=now) for _ in range(3)]
    assert [int(p["item_id"]) for p in picks] == \
        [int(i["item_id"]) for i in again]


# ── ⚠30 / ⚠32: Studio chip + Up Coming ────────────────────────────────

class _Peek(_FakeScheduler):
    def __init__(self, items):
        super().__init__()
        self.items = list(items)

    def is_running(self):
        return True

    def peek_next(self, n=5, now=None):
        return [dict(i) for i in self.items[:int(n)]]


def _sweeper():
    return {"item_type": "sweeper", "item_id": 1064,
            "title": "Sweepers_RR-Musical 01", "artist": "SWEEPER",
            "position": "Start of Song", "file_path": _REAL,
            "duration_ms": 9_000, "clock_id": 4039, "slot_idx": 0}


def _song(title="Mehrama"):
    return {"item_type": "song", "item_id": 148, "title": title,
            "artist": "A", "file_path": _REAL, "duration_ms": 249_000,
            "clock_id": 4039, "slot_idx": 1}


def _jingle():
    return {"item_type": "jingle", "item_id": 1465, "title": "Jingle _Retro01",
            "artist": "JINGLE", "file_path": _REAL, "duration_ms": 19_000,
            "clock_id": 4039, "slot_idx": 2}


@pytest.fixture
def studio(qapp, monkeypatch):
    from ui.studio import Studio

    # Keep the LIVE spot / SOTG schedule out from construction on (QA ⚠9):
    # a real spot within 60 s of the run time otherwise lands as card 0.
    def _no_preview(self, *, now=None):
        self._upcoming_preview_spots = []
        self._upcoming_preview_sotgs = []
        return False
    monkeypatch.setattr(Studio, "_check_upcoming_dispatches", _no_preview)
    monkeypatch.setattr(Studio, "_sotg_check_tick", lambda self: None)

    def _make(items, on_deck_type="song"):
        sch = _Peek(items)
        s = Studio(Database(), engine=_FakeEngine(), scheduler=sch,
                   sweeper_engine=object())
        s._upcoming_preview_spots, s._upcoming_preview_sotgs = [], []
        s._pending_spots, s._pending_sotgs, s._teased_songs = [], [], []
        s._manual_queue = []
        s._playback_cid = 11
        s._playback_kind = "deck"
        s._current_duration_ms = 270_000
        s._cfg_fade_out_start_s = 8
        s._cfg_automix_trigger = "At song MIX POINT marker"
        s._current_track = {"id": 1, "title": "On Air", "mix_point_ms": 0,
                            "_item_type": on_deck_type}
        s._last_position_ms = 28_000
        s._load_upcoming_queue()
        return s, sch
    made = []

    def _wrapped(*a, **k):
        s, sch = _make(*a, **k)
        made.append(s)
        return s, sch
    yield _wrapped
    for s in made:
        s.deleteLater()


def _cards(s):
    return [c for c in s._upcoming._cards if c.song() is not None]


def _glow(s):
    g = [c.song()["title"] for c in _cards(s) if c._is_next]
    assert len(g) == 1
    return g[0]


def test_song_on_deck_overlay_sweeper_is_not_next(studio):
    """17:00:42 live: sweeper laid over Mehrama, both start together."""
    s, _ = studio([_sweeper(), _song(), _jingle()])
    cards = _cards(s)
    assert cards[0].song()["_overlay"] is True
    assert s._next_chip._title == _glow(s) == "Mehrama"
    assert cards[0]._at_text == cards[1]._at_text      # start together
    assert not cards[0]._is_next


def test_jingle_on_deck_sweeper_plays_on_its_own(studio):
    """17:05:02 live: after a jingle the sweeper took the deck itself."""
    s, _ = studio([_sweeper(), _song(), _jingle()], on_deck_type="jingle")
    cards = _cards(s)
    assert not cards[0].song()["_overlay"]
    assert s._next_chip._title == _glow(s) == "Sweepers_RR-Musical 01"
    assert cards[0]._at_text != cards[1]._at_text      # 9 s later


def test_overlay_after_a_song_inside_the_list(studio):
    """sweeper after the jingle → own turn; sweeper after a song → overlay."""
    s, _ = studio([_jingle(), _sweeper(), _song("A"), _sweeper(),
                   _song("B")])
    flags = [c.song().get("_overlay") for c in _cards(s)]
    assert flags[:5] == [False, False, False, True, False]


def test_chip_follows_every_up_coming_reload(studio):
    """⚠32: the chip named a different song than the cards after a reload."""
    s, sch = studio([_song("First")])
    assert s._next_chip._title == "First"
    sch.items = [_song("Changed")]
    s._load_upcoming_queue()                  # reload only, no track start
    assert s._next_chip._title == _glow(s) == "Changed"


# ── ⚠33: clean exit leaves a complete radioai.db ──────────────────────

def test_checkpoint_and_close_empties_the_wal(qapp):
    db = Database()
    path = db._conn().execute("PRAGMA database_list").fetchall()[0][2]
    conn = db._conn()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rid = conn.execute(
        "INSERT INTO broadcast_log (entry_type, item_name, was_manual, "
        "played_at, actual_time, duration_ms) VALUES "
        "('jingle', '_test_r7_wal', 1, ?, ?, 0)", [stamp, stamp]).lastrowid
    conn.commit()
    try:
        assert os.path.getsize(path + "-wal") > 0       # data sits in WAL
        assert db.checkpoint_and_close() is True
        assert (not os.path.exists(path + "-wal")
                or os.path.getsize(path + "-wal") == 0)
        # The row is in the main file now, and the DB reopens on demand.
        assert db._conn().execute(
            "SELECT COUNT(*) FROM broadcast_log WHERE id = ?",
            [rid]).fetchone()[0] == 1
    finally:
        c = db._conn()
        c.execute("DELETE FROM broadcast_log WHERE id = ?", [rid])
        c.commit()
