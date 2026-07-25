"""
Sweeper mix fields on the AUTO path + song ducking (2026-07-25).

Two bugs this pins:

  BUG 2 — ``SchedulerEngine._sweeper_to_item`` only carried
    file_path/duration/position, so an AUTO-dispatched sweeper always
    fell back to volume 100 / offset 0: every per-sweeper mix setting in
    the Sweeper Editor was silently ignored on air. Only the MANUAL
    click path read them off the row.

  DUCKING — ``volume_song_pct`` (and ``fade_seconds``) were written by
    the editor, stored in the DB, read back by the editor… and never
    reached playback. The song therefore kept playing at full master
    volume underneath a talking sweeper.

Contract pinned here:
  • the scheduler item carries volume_sweeper_pct / volume_song_pct /
    offset_seconds / fade_seconds
  • Studio only ducks when volume_song_pct < 100 AND the kill switch
    (settings ``sweeper_ducking_enabled``) is on — otherwise on_start /
    on_end are None and playback is byte-identical to before
  • the restore is skipped when the deck has moved on or the channel is
    crossfading, and ALWAYS clears the duck state
  • the 1Hz watchdog restores a duck that was somehow never released
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta

import pytest

from core.database import Database
from core.scheduler import SchedulerEngine
from ui.studio import Studio

_REAL_PATH = sys.executable


# ── Fakes (mirrors test_studio_sweeper_overlay.py) ──────────────────────


class _RecordingSignal:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *a, **k):
        for fn in list(self._slots):
            fn(*a, **k)


class _FakeScheduler:
    def __init__(self):
        self._items: list[dict] = []
        self._running = True
        self.spot_due = _RecordingSignal()
        self.song_auto_advance = _RecordingSignal()
        self.break_approaching = _RecordingSignal()
        self.next_break_in = _RecordingSignal()
        self.schedule_reloaded = _RecordingSignal()
        self.error_occurred = _RecordingSignal()
        self.started = _RecordingSignal()
        self.stopped = _RecordingSignal()
        self.active_clock_changed = _RecordingSignal()

    def is_running(self):
        return self._running

    def queue(self, *items):
        self._items.extend(items)

    def pick_next_item(self, _now=None):
        return self._items.pop(0) if self._items else None

    def peek_next(self, n=5, now=None):
        return list(self._items[:n])


class _FakeSweeperEngine:
    def __init__(self):
        self.scheduled = []
        self.is_playing = False

    def schedule_for_song(self, song_info, sweeper_info, deck_handle,
                          on_start=None, on_end=None):
        self.scheduled.append({
            "song": dict(song_info), "sweeper": dict(sweeper_info),
            "deck": deck_handle, "on_start": on_start, "on_end": on_end,
        })

    def cancel(self):
        pass


class _FakeAudioEngine:
    """Records volume slides so ducking can be asserted without BASS.

    Must carry every signal Studio.__init__ connects to, or the ctor
    raises before any test body runs."""

    def __init__(self, known_cids=(999,)):
        self.fades: list[tuple[int, int, int]] = []
        self._known = set(known_cids)
        self.position_changed = _RecordingSignal()
        self.playback_ended = _RecordingSignal()
        self.error_occurred = _RecordingSignal()
        self.mix_point_reached = _RecordingSignal()
        self.fade_completed = _RecordingSignal()

    def fade_volume_to(self, cid, target, duration_ms):
        if int(cid) not in self._known:
            raise RuntimeError(f"channel {cid} not found")
        self.fades.append((int(cid), int(target), int(duration_ms)))

    def set_volume(self, cid, vol):
        pass


@pytest.fixture
def db():
    return Database()


def _studio(db, scheduler=None, sweeper_engine=None, engine=None) -> Studio:
    s = Studio(db, parent=None, engine=engine, scheduler=scheduler,
               instant_jingle_engine=None, sweeper_engine=sweeper_engine)
    return s


def _sweeper_item(item_id=11, position="Start of Song",
                  song_pct=None, fade_s=None):
    it = {
        "item_type": "sweeper", "item_id": int(item_id),
        "title": "SW", "artist": "SWEEPER", "file_path": _REAL_PATH,
        "duration_ms": 8000, "position": position,
        "volume_sweeper_pct": 95, "offset_seconds": 0.0,
        "clock_id": 1, "slot_idx": 1,
    }
    if song_pct is not None:
        it["volume_song_pct"] = song_pct
    if fade_s is not None:
        it["fade_seconds"] = fade_s
    return it


def _arm_deck(studio, cid=999):
    studio._playback_cid = cid
    studio._current_track = {"id": 1, "duration_ms": 180000}
    studio._current_duration_ms = 180000


# ── BUG 2: the scheduler item carries the mix fields ────────────────────


def test_sweeper_to_item_carries_mix_fields(db):
    """A sweeper row's editor settings must survive into the item dict."""
    prefix = f"_test_duck_{uuid.uuid4().hex[:8]}_"
    conn = db._conn()
    db._ensure_sweepers_columns()
    cur = conn.execute(
        "INSERT INTO sweepers (name, category, file_path, duration_ms, "
        "position, properties, is_enabled, volume_song_pct, "
        "volume_sweeper_pct, offset_seconds, fade_seconds) "
        "VALUES (?, 'Station', ?, 8000, 'Start of Song', 'Regular', 1, "
        "25, 80, 1.5, 0.8)", [prefix + "sw", _REAL_PATH])
    sid = int(cur.lastrowid)
    conn.commit()
    try:
        row = conn.execute("SELECT * FROM sweepers WHERE id = ?",
                           [sid]).fetchone()
        item = SchedulerEngine._sweeper_to_item(row)
        assert item["volume_sweeper_pct"] == 80
        assert item["volume_song_pct"] == 25
        assert item["offset_seconds"] == 1.5
        assert item["fade_seconds"] == 0.8
        # Pre-existing fields still intact
        assert item["item_type"] == "sweeper"
        assert item["position"] == "Start of Song"
    finally:
        conn.execute("DELETE FROM sweepers WHERE id = ?", [sid])
        conn.commit()


def test_auto_dispatch_uses_row_sweeper_volume(qapp, db):
    """Before the fix this always reached the engine as 100."""
    sched, swe = _FakeScheduler(), _FakeSweeperEngine()
    s = _studio(db, scheduler=sched, sweeper_engine=swe)
    _arm_deck(s)
    item = _sweeper_item()
    item["volume_sweeper_pct"] = 70
    s._dispatch_overlay_sweeper(item)
    assert swe.scheduled[-1]["sweeper"]["sweeper_volume"] == 70
    s.deleteLater()


# ── Ducking engages only when asked ─────────────────────────────────────


def test_no_duck_when_song_pct_is_100(qapp, db):
    """Byte-identical to pre-feature behaviour: no callbacks at all."""
    sched, swe = _FakeScheduler(), _FakeSweeperEngine()
    eng = _FakeAudioEngine()
    s = _studio(db, scheduler=sched, sweeper_engine=swe, engine=eng)
    _arm_deck(s)
    s._dispatch_overlay_sweeper(_sweeper_item(song_pct=100))
    call = swe.scheduled[-1]
    assert call["on_start"] is None
    assert call["on_end"] is None
    assert eng.fades == []
    s.deleteLater()


def test_no_duck_when_field_absent(qapp, db):
    """A legacy item with no volume_song_pct must not duck."""
    sched, swe = _FakeScheduler(), _FakeSweeperEngine()
    s = _studio(db, scheduler=sched, sweeper_engine=swe,
                engine=_FakeAudioEngine())
    _arm_deck(s)
    s._dispatch_overlay_sweeper(_sweeper_item())      # no song_pct key
    assert swe.scheduled[-1]["on_start"] is None
    s.deleteLater()


def test_kill_switch_disables_ducking(qapp, db):
    sched, swe = _FakeScheduler(), _FakeSweeperEngine()
    s = _studio(db, scheduler=sched, sweeper_engine=swe,
                engine=_FakeAudioEngine())
    _arm_deck(s)
    s._cfg_sweeper_ducking = False
    s._dispatch_overlay_sweeper(_sweeper_item(song_pct=10))
    assert swe.scheduled[-1]["on_start"] is None
    s.deleteLater()


def test_duck_and_restore_round_trip(qapp, db):
    """on_start ducks the deck; on_end restores it to master volume."""
    sched, swe = _FakeScheduler(), _FakeSweeperEngine()
    eng = _FakeAudioEngine(known_cids=(999,))
    s = _studio(db, scheduler=sched, sweeper_engine=swe, engine=eng)
    _arm_deck(s)
    s._master_volume = 55
    s._dispatch_overlay_sweeper(_sweeper_item(song_pct=10, fade_s=0.4))

    call = swe.scheduled[-1]
    assert callable(call["on_start"]) and callable(call["on_end"])

    call["on_start"]()                       # engine thread → queued signal
    qapp.processEvents()
    assert eng.fades[-1] == (999, 10, 400)
    assert s._ducked_cid == 999

    call["on_end"]()
    qapp.processEvents()
    assert eng.fades[-1] == (999, 55, 400)   # back to master, not 100
    assert s._ducked_cid is None
    s.deleteLater()


def test_restore_uses_live_master_volume(qapp, db):
    """Operator changes volume mid-sweeper → restore honours the new one."""
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine()
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s)
    s._master_volume = 55
    s._apply_sweeper_duck(999, 10, 300)
    s._master_volume = 70                     # changed while ducked
    s._apply_sweeper_unduck(999, 300)
    assert eng.fades[-1] == (999, 70, 300)
    s.deleteLater()


# ── Guards: never stomp a channel that isn't ours ───────────────────────


def test_duck_skipped_when_deck_moved_on(qapp, db):
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine(known_cids=(999, 1000))
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s, cid=1000)                    # deck already advanced
    s._apply_sweeper_duck(999, 10, 300)       # stale cid
    assert eng.fades == []
    assert s._ducked_cid is None
    s.deleteLater()


def test_duck_skipped_while_crossfading(qapp, db):
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine()
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s)
    s._fading_cid = 999                       # crossfade owns the volume
    s._apply_sweeper_duck(999, 10, 300)
    assert eng.fades == []
    s.deleteLater()


def test_unduck_skipped_while_crossfading_but_state_cleared(qapp, db):
    """The outgoing song must keep fading — but state must not wedge."""
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine()
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s)
    s._master_volume = 55
    s._apply_sweeper_duck(999, 10, 300)
    assert s._ducked_cid == 999
    s._fading_cid = 999                       # crossfade started meanwhile
    s._apply_sweeper_unduck(999, 300)
    assert len(eng.fades) == 1                # duck only; no restore slide
    assert s._ducked_cid is None              # state cleared regardless
    s.deleteLater()


def test_unduck_is_noop_when_duck_never_applied(qapp, db):
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine()
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s)
    s._apply_sweeper_unduck(999, 300)
    assert eng.fades == []
    s.deleteLater()


def test_duck_survives_dead_channel(qapp, db):
    """A freed BASS channel raises — must be swallowed, state cleared."""
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine(known_cids=())
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s)
    s._apply_sweeper_duck(999, 10, 300)       # engine raises internally
    assert s._ducked_cid is None
    s.deleteLater()


# ── Watchdog: a song must never stay ducked ─────────────────────────────


def test_watchdog_restores_orphaned_duck(qapp, db):
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine()
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s)
    s._master_volume = 55
    s._apply_sweeper_duck(999, 10, 300)
    # Overlay ended but on_end never arrived; age the duck past the grace
    swe.is_playing = False
    s._ducked_at = datetime.now() - timedelta(
        seconds=Studio._DUCK_WATCHDOG_S + 1)

    s._tick_duck_watchdog()

    assert eng.fades[-1][0] == 999
    assert eng.fades[-1][1] == 55             # restored to master
    assert s._ducked_cid is None
    s.deleteLater()


def test_watchdog_leaves_active_overlay_alone(qapp, db):
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine()
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s)
    s._apply_sweeper_duck(999, 10, 300)
    swe.is_playing = True                     # sweeper still talking
    s._ducked_at = datetime.now() - timedelta(
        seconds=Studio._DUCK_WATCHDOG_S + 1)

    s._tick_duck_watchdog()

    assert len(eng.fades) == 1                # duck only — no restore
    assert s._ducked_cid == 999
    s.deleteLater()


def test_watchdog_respects_grace_period(qapp, db):
    """A duck applied a moment ago must not be yanked by the watchdog."""
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine()
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s)
    s._apply_sweeper_duck(999, 10, 300)
    swe.is_playing = False                    # not latched yet
    s._tick_duck_watchdog()                   # just ducked → too early
    assert len(eng.fades) == 1
    assert s._ducked_cid == 999
    s.deleteLater()


def test_watchdog_noop_when_not_ducked(qapp, db):
    swe, eng = _FakeSweeperEngine(), _FakeAudioEngine()
    s = _studio(db, scheduler=_FakeScheduler(), sweeper_engine=swe,
                engine=eng)
    _arm_deck(s)
    s._tick_duck_watchdog()
    assert eng.fades == []
    s.deleteLater()
