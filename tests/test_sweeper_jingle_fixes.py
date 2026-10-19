"""Regression tests — sweepers, jingles, Studio library tiles (2026-10-17).

Covers:
  1  AudioEngine.bass_handle + Studio passes the REAL BASS handle
  2  SweeperEngine per-schedule cancel + handle ownership
  3  "Custom Position" trigger
  4  overlay sweeper logged only when it actually starts (with a name)
  5  sweeper_volume=0 survives; Stop / Esc / AUTO-off cancel the overlay
  6  _pick_jingle: no jingle_pads fallback by id; missing files filtered
  7  Clock Editor keeps station_id slots
  8  jingle slot counts are case-insensitive
  9  log_play jingle_id / item_name; Instant Jingle pads logged
  10 Libraries tiles refresh (re-click / show) + library_changed signals
  11 double-click resolves the clicked (filtered) row
  12 editors refuse to save without an existing audio file

Fakes are preferred; tests that need Studio use the session's
live-DB-shield copy (see conftest) and clean up their own rows.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
import uuid

import pytest

from core import dialogs as _dialogs
from core.database import Database
from ui.studio import Studio

_REAL_PATH = sys.executable          # any file that exists on disk


# ── Shared fakes ────────────────────────────────────────────────────────────

class _Sig:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *a, **k):
        for fn in list(self._slots):
            fn(*a, **k)


class _FakeAudioEngine:
    """Carries every signal Studio.__init__ connects to + bass_handle."""

    def __init__(self, handles=None):
        self._handles = dict(handles or {})
        self.position_changed = _Sig()
        self.playback_ended = _Sig()
        self.error_occurred = _Sig()
        self.mix_point_reached = _Sig()
        self.fade_completed = _Sig()

    def bass_handle(self, cid):
        return self._handles.get(int(cid), 0)

    def set_volume(self, *a, **k):
        pass

    def stop(self, *a, **k):
        pass

    def cleanup(self, *a, **k):
        pass

    def cleanup_all(self, *a, **k):
        pass


class _FakeSweeperEngine:
    def __init__(self):
        self.scheduled = []
        self.cancelled = 0
        self.is_playing = False

    def schedule_for_song(self, song_info, sweeper_info, deck_handle,
                          on_start=None, on_end=None):
        self.scheduled.append({"song": dict(song_info),
                               "sweeper": dict(sweeper_info),
                               "deck": deck_handle,
                               "on_start": on_start, "on_end": on_end})

    def cancel(self):
        self.cancelled += 1


@pytest.fixture
def db():
    return Database()


def _studio(db, engine=None, sweeper_engine=None, ije=None) -> Studio:
    return Studio(db, parent=None, engine=engine, scheduler=None,
                  instant_jingle_engine=ije, sweeper_engine=sweeper_engine)


def _arm_deck(s, cid=7):
    s._playback_cid = cid
    s._current_track = {"id": 1, "duration_ms": 180000}
    s._current_duration_ms = 180000


def _sweeper_item(**over):
    it = {"item_type": "sweeper", "item_id": 55, "title": "Hit Sweep",
          "file_path": _REAL_PATH, "duration_ms": 6000,
          "position": "Bridge at End", "volume_sweeper_pct": 80,
          "offset_seconds": 0.0, "clock_id": None, "slot_idx": None}
    it.update(over)
    return it


# ── 1. bass_handle ──────────────────────────────────────────────────────────

def test_audio_engine_bass_handle_maps_cid_to_real_handle(engine):
    from core.audio.channels import Channel
    assert engine.bass_handle(123456) == 0
    assert engine.bass_handle(None) == 0
    engine._channels[987654] = Channel(id=987654, handle=4242,
                                       file_path="x")
    try:
        assert engine.bass_handle(987654) == 4242
    finally:
        engine._channels.pop(987654, None)


def test_overlay_dispatch_passes_bass_handle_not_cid(qapp, db):
    swe = _FakeSweeperEngine()
    s = _studio(db, engine=_FakeAudioEngine({7: 90001}), sweeper_engine=swe)
    _arm_deck(s, 7)
    s._dispatch_overlay_sweeper(_sweeper_item())
    assert swe.scheduled and swe.scheduled[0]["deck"] == 90001
    s.deleteLater()


def test_overlay_skipped_when_engine_has_no_handle(qapp, db):
    swe = _FakeSweeperEngine()
    s = _studio(db, engine=_FakeAudioEngine({}), sweeper_engine=swe)
    _arm_deck(s, 7)
    s._dispatch_overlay_sweeper(_sweeper_item())
    assert swe.scheduled == []
    s.deleteLater()


# ── 2/3. SweeperEngine ──────────────────────────────────────────────────────

class _FakeBass:
    """Stands in for pybass3 BassStream + BassChannel."""

    def __init__(self):
        self.next_handle = 100
        self.freed: list[int] = []
        self.lock = threading.Lock()

    # BassStream
    def CreateFile(self, *a, **k):
        with self.lock:
            self.next_handle += 1
            return self.next_handle

    def Free(self, h):
        with self.lock:
            self.freed.append(int(h))

    # BassChannel
    def Play(self, *a, **k):
        return True

    def Stop(self, *a, **k):
        return True

    def GetPositionSeconds(self, _h):
        return 0.0                      # deck never reaches the trigger

    def IsActive(self, h):
        from pybass3.codes import channel as _ch
        with self.lock:
            return (_ch.ACTIVE_STOPPED if int(h) in self.freed
                    else _ch.ACTIVE_PLAYING)


@pytest.fixture
def fake_bass(monkeypatch):
    import core.sweeper_engine as se
    fb = _FakeBass()
    monkeypatch.setattr(se, "BassStream", fb)
    monkeypatch.setattr(se, "BassChannel", fb)
    return fb


def _wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_reschedule_cancels_old_watcher_and_keeps_new_handle(fake_bass):
    from core.sweeper_engine import SweeperEngine
    eng = SweeperEngine()
    song = {"duration_ms": 180000}
    sw = {"file_path": _REAL_PATH, "duration_ms": 5000,
          "position": "Start of Song", "sweeper_volume": 100}
    eng.schedule_for_song(song, sw, deck_handle=1)
    assert _wait(lambda: eng._handle == 101)
    t_old = eng._thread
    eng.schedule_for_song(song, sw, deck_handle=1)
    assert _wait(lambda: eng._handle == 102)
    t_old.join(2.0)
    assert not t_old.is_alive(), "old watcher must exit on cancel"
    time.sleep(0.3)
    assert 101 in fake_bass.freed
    assert 102 not in fake_bass.freed, \
        "old thread's cleanup must never free the NEW sweeper"
    assert eng._handle == 102
    eng.cancel()
    assert 102 in fake_bass.freed
    assert eng._handle == 0


def test_cancel_stops_pending_positioned_watcher(fake_bass):
    from core.sweeper_engine import SweeperEngine
    eng = SweeperEngine()
    started = []
    eng.schedule_for_song({"duration_ms": 180000},
                          {"file_path": _REAL_PATH, "duration_ms": 5000,
                           "position": "Before End"},
                          deck_handle=1, on_start=lambda: started.append(1))
    t = eng._thread
    eng.cancel()
    t.join(2.0)
    assert not t.is_alive()
    assert started == [] and fake_bass.next_handle == 100


def test_custom_position_trigger_uses_offset():
    from core.sweeper_engine import SweeperEngine
    e = SweeperEngine()
    for pos in ("Custom", "Custom Position"):
        assert e._calc_trigger({"duration_ms": 200000},
                               {"position": pos, "position_offset": 12,
                                "duration_ms": 5000}) == 12000


# ── 4/5. Studio overlay logging, volume, cancel ─────────────────────────────

def test_overlay_logged_only_on_actual_start_with_name(qapp, db, monkeypatch):
    swe = _FakeSweeperEngine()
    s = _studio(db, sweeper_engine=swe)
    calls = []
    monkeypatch.setattr(s._db, "log_play", lambda **k: calls.append(k))
    _arm_deck(s)
    s._dispatch_overlay_sweeper(_sweeper_item())
    assert calls == [], "must not log at schedule time"
    swe.scheduled[0]["on_start"]()          # engine says: it started
    assert len(calls) == 1
    assert calls[0]["entry_type"] == "sweeper"
    assert calls[0]["item_name"] == "Hit Sweep"
    s.deleteLater()


def test_sweeper_volume_zero_is_kept(qapp, db):
    swe = _FakeSweeperEngine()
    s = _studio(db, sweeper_engine=swe)
    _arm_deck(s)
    s._dispatch_overlay_sweeper(_sweeper_item(volume_sweeper_pct=0))
    assert swe.scheduled[0]["sweeper"]["sweeper_volume"] == 0
    s._dispatch_overlay_sweeper(_sweeper_item(volume_sweeper_pct=None,
                                              sweeper_volume=None))
    assert swe.scheduled[1]["sweeper"]["sweeper_volume"] == 100
    s.deleteLater()


def test_stop_esc_and_auto_off_cancel_overlay(qapp, db):
    swe = _FakeSweeperEngine()
    s = _studio(db, sweeper_engine=swe)
    s._on_stop_all_clicked()
    assert swe.cancelled == 1
    s._on_jingle_stop_all()
    assert swe.cancelled == 2
    s._on_deck_stop()
    assert swe.cancelled == 3
    s._auto_advance_enabled = True
    s._on_auto_pill_clicked()               # no scheduler → flag flips off
    assert s._auto_advance_enabled is False
    assert swe.cancelled == 4
    s.deleteLater()


# ── 6. Scheduler pickers ────────────────────────────────────────────────────

class _PickerDb:
    def __init__(self, tmp_path):
        self._c = sqlite3.connect(":memory:")
        self._c.row_factory = sqlite3.Row
        self._c.executescript(
            "CREATE TABLE jingles (id INTEGER PRIMARY KEY, name TEXT, "
            "category TEXT, file_path TEXT, duration_ms INT, is_enabled INT);"
            "CREATE TABLE jingle_pads (id INTEGER PRIMARY KEY, label TEXT, "
            "file_path TEXT, duration_ms INT);")
        self.missing = str(tmp_path / "gone.mp3")

    def _conn(self):
        return self._c

    def get_jingle_pads_active(self, pallet_id=None):
        return self._c.execute("SELECT * FROM jingle_pads").fetchall()

    def get_station_ids_active(self):
        return self._c.execute(
            "SELECT * FROM jingles WHERE category='Station ID' "
            "AND is_enabled=1").fetchall()


def test_pick_jingle_specific_never_falls_back_to_pad(tmp_path):
    from core.scheduler.engine import SchedulerEngine
    db = _PickerDb(tmp_path)
    db._c.execute("INSERT INTO jingles VALUES (5,'Off','Promo',?,1000,0)",
                  [_REAL_PATH])
    db._c.execute("INSERT INTO jingle_pads VALUES (5,'Unrelated Pad',?,900)",
                  [_REAL_PATH])
    sch = SchedulerEngine(db)
    slot = {"selection_mode": "specific", "item_id": 5, "category_id": None}
    assert sch._pick_jingle(slot) is None


def test_pick_jingle_and_station_id_skip_missing_files(tmp_path):
    from core.scheduler.engine import SchedulerEngine
    db = _PickerDb(tmp_path)
    db._c.execute("INSERT INTO jingles VALUES (1,'Gone','Station ID',?,1,1)",
                  [db.missing])
    db._c.execute("INSERT INTO jingles VALUES (2,'Real','Station ID',?,1,1)",
                  [_REAL_PATH])
    sch = SchedulerEngine(db)
    spec = {"selection_mode": "specific", "item_id": 1, "category_id": None}
    assert sch._pick_jingle(spec) is None
    assert sch._pick_station_id(spec) is None
    anyslot = {"selection_mode": "random_any", "item_id": 0,
               "category_id": None}
    for _ in range(10):
        assert sch._pick_jingle(anyslot)["item_id"] == 2
        assert sch._pick_station_id(anyslot)["item_id"] == 2


def test_pad_items_are_tagged_as_pad_source():
    from core.scheduler.engine import SchedulerEngine
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    row = c.execute("SELECT 3 AS id, 'P' AS label, 'x' AS file_path, "
                    "1 AS duration_ms").fetchone()
    assert SchedulerEngine._jingle_pad_to_item(row)["_source"] == "pad"


# ── 7. Clock Editor station_id round-trip ───────────────────────────────────

def test_clock_editor_preserves_station_id_slot_type():
    from ui.clock_editor import ClockEditor
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT 'Station ID' AS slot_type, NULL AS category_id, "
        "'' AS filter_json, 0 AS minute_position, 10 AS duration_seconds, "
        "'specific' AS selection_mode, 4 AS item_id").fetchall()
    els = ClockEditor._slots_to_elements(rows)
    assert els[0]["element_type"] == "jingle"
    payload = ClockEditor._elements_to_slot_payload(els)
    assert payload[0]["slot_type"] == "station_id"
    assert payload[0]["item_id"] == 4
    # A plain jingle stays a jingle
    plain = ClockEditor._elements_to_slot_payload(
        [{"element_type": "jingle", "slot_type_db": "jingle"}])
    assert plain[0]["slot_type"] == "jingle"


# ── 8/9. Database helpers (in-memory fake) ──────────────────────────────────

class _MemDb:
    _ensure_broadcast_log_columns = Database._ensure_broadcast_log_columns
    log_play = Database.log_play
    count_jingle_clock_slots = Database.count_jingle_clock_slots
    delete_jingle = Database.delete_jingle

    def __init__(self):
        self._c = sqlite3.connect(":memory:")
        self._c.row_factory = sqlite3.Row
        self._c.executescript(
            "CREATE TABLE jingles (id INTEGER PRIMARY KEY, name TEXT);"
            "CREATE TABLE clock_slots (id INTEGER PRIMARY KEY, "
            "slot_type TEXT, item_id INT, selection_mode TEXT);"
            "CREATE TABLE final_log_entries (id INTEGER PRIMARY KEY, "
            "jingle_id INT);"
            "CREATE TABLE broadcast_log (id INTEGER PRIMARY KEY, "
            "played_at TEXT, entry_type TEXT, song_id INT, campaign_id INT, "
            "jingle_id INTEGER REFERENCES jingles(id), actual_time TEXT, "
            "duration_ms INT, deck TEXT, was_manual INT, operator TEXT);")

    def _conn(self):
        return self._c


def test_jingle_slot_count_and_delete_are_case_insensitive():
    m = _MemDb()
    m._c.execute("INSERT INTO jingles VALUES (9, 'J')")
    for st in ("Jingle", "jingle", "Station ID", "station_id", "song"):
        m._c.execute("INSERT INTO clock_slots (slot_type, item_id, "
                     "selection_mode) VALUES (?, 9, 'specific')", [st])
    m._c.commit()
    assert m.count_jingle_clock_slots(9) == 4
    m.delete_jingle(9)
    left = m._c.execute("SELECT COUNT(*) FROM clock_slots "
                        "WHERE item_id = 9").fetchone()[0]
    assert left == 1                       # only the 'song' slot


def test_log_play_stores_jingle_id_and_item_name():
    m = _MemDb()
    m._c.execute("INSERT INTO jingles VALUES (3, 'ID One')")
    m.log_play(entry_type="jingle", jingle_id=3, item_name="ID One")
    m.log_play(entry_type="sweeper", item_name="Hit Sweep")
    rows = m._c.execute("SELECT entry_type, jingle_id, item_name "
                        "FROM broadcast_log ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("jingle", 3, "ID One"),
                                         ("sweeper", None, "Hit Sweep")]


def test_final_log_row_shows_sweeper_and_pad_names():
    from ui.final_log import FinalLog
    base = {"played_at": "2026-10-17 10:00:00", "cat_name": None,
            "duration_ms": 5000, "song_title": None, "song_artist": None,
            "campaign_name": None, "jingle_name": None}
    sw = FinalLog._row_to_dict(None, {**base, "entry_type": "sweeper",
                                      "item_name": "Hit Sweep"})
    assert "Hit Sweep" in str(sw.values())
    pad = FinalLog._row_to_dict(None, {**base, "entry_type": "jingle",
                                       "item_name": "Pad Boom"})
    assert "Pad Boom" in str(pad.values())


# ── 9. Instant Jingle pad + deck jingle logging ─────────────────────────────

class _FakeIJE:
    def __init__(self):
        self.pad_started = _Sig()
        self.pad_ended = _Sig()
        self.pad_stopped = _Sig()

    def play_pad(self, *a, **k):
        return True

    def stop_all(self):
        return 0

    def is_playing(self, _id):
        return False

    def fade_stop_pad(self, *a, **k):
        return True


def test_instant_jingle_pad_play_is_logged(qapp, db, monkeypatch):
    s = _studio(db, ije=_FakeIJE())
    calls = []
    monkeypatch.setattr(s._db, "log_play", lambda **k: calls.append(k))
    s._jingle_pads = [{"id": 77, "label": "Pad Boom",
                       "file_path": _REAL_PATH, "duration_ms": 3000}]
    s._play_jingle_at_index(0)
    assert len(calls) == 1
    assert calls[0]["entry_type"] == "jingle"
    assert calls[0]["item_name"] == "Pad Boom"
    assert calls[0].get("jingle_id") is None   # pad id ≠ jingles.id
    s.deleteLater()


def test_deck_jingle_log_passes_jingle_id(qapp, db, monkeypatch):
    s = _studio(db)
    calls = []
    monkeypatch.setattr(s._db, "log_play", lambda **k: calls.append(k))
    s._write_broadcast_log({"id": 12, "title": "Lib ID",
                            "_item_type": "jingle"})
    s._write_broadcast_log({"id": 13, "title": "A Pad",
                            "_item_type": "jingle", "_source": "pad"})
    assert calls[0]["jingle_id"] == 12 and calls[0]["item_name"] == "Lib ID"
    assert calls[1]["jingle_id"] is None and calls[1]["item_name"] == "A Pad"
    s.deleteLater()


# ── 10/11. Libraries panel ──────────────────────────────────────────────────

@pytest.fixture
def two_jingles(db):
    prefix = f"_t_swjf_{uuid.uuid4().hex[:8]}_"
    ids = [db.add_jingle({"name": prefix + n, "category": "Promo",
                          "file_path": _REAL_PATH, "duration_ms": 1000,
                          "is_enabled": 1}) for n in ("Alpha", "Bravo")]
    yield prefix, ids
    for jid in ids:
        db._conn().execute("DELETE FROM jingles WHERE id = ?", [jid])
    db._conn().commit()


def test_jingles_double_click_with_search_plays_clicked_row(
        qapp, db, two_jingles):
    prefix, (a_id, b_id) = two_jingles
    s = _studio(db)
    got = []
    s._on_play_library_jingle = lambda j: got.append(j)
    s._libraries._on_type_clicked("Jingles")
    s._libraries._search.setText(prefix + "Bravo")
    s._libraries._apply_search_filter()
    s._on_library_song_double_clicked(0)          # first VISIBLE row
    assert got and int(got[0]["id"]) == b_id
    s._libraries._on_row_selected(0)
    q = s._selected_library_row_as_queue_dict()
    assert q and int(q["id"]) == b_id
    s.deleteLater()


def test_songs_double_click_plays_library_row_not_queue(qapp, db):
    s = _studio(db)
    rows = s._libraries._rows
    if len(rows) < 2:
        pytest.skip("need songs in the library")
    got = []
    s._on_queue_song_play = lambda song: got.append(song)
    s._on_library_song_double_clicked(1)
    assert got and got[0]["id"] == s._libraries.row_data(1)["id"]
    s.deleteLater()


def test_active_tile_reclick_and_show_reload_jingles(qapp, db, two_jingles):
    prefix, ids = two_jingles
    s = _studio(db)
    s._libraries._on_type_clicked("Jingles")
    extra = db.add_jingle({"name": prefix + "Charlie", "category": "Promo",
                           "file_path": _REAL_PATH, "duration_ms": 1000,
                           "is_enabled": 1})
    try:
        assert extra not in [j["id"] for j in s._library_jingles]
        s._libraries._on_type_clicked("Jingles")       # re-click
        assert extra in [j["id"] for j in s._library_jingles]
        db._conn().execute("DELETE FROM jingles WHERE id = ?", [extra])
        db._conn().commit()
        s._refresh_library_on_show()
        assert extra not in [j["id"] for j in s._library_jingles]
        s.refresh_library_panel("Jingles")
        assert extra not in [j["id"] for j in s._library_jingles]
    finally:
        db._conn().execute("DELETE FROM jingles WHERE id = ?", [extra])
        db._conn().commit()
    s.deleteLater()


def test_libraries_emit_library_changed_on_save_and_delete(
        qapp, db, two_jingles, monkeypatch):
    from ui.jingles_library import JinglesLibrary
    from ui.sweepers_library import SweepersLibrary
    _prefix, (a_id, _b) = two_jingles
    lib = JinglesLibrary(db)
    hits = []
    lib.library_changed.connect(lambda: hits.append(1))
    lib._on_jingle_saved(a_id)
    assert hits == [1]
    monkeypatch.setattr(_dialogs, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(db, "delete_jingle", lambda jid: None)
    lib._selected_id = a_id
    if any(j["id"] == a_id for j in lib._jingles):
        lib._on_delete()
        assert hits == [1, 1]
    lib.deleteLater()
    assert hasattr(SweepersLibrary, "library_changed")


# ── 12. Editors require an audio file ───────────────────────────────────────

@pytest.mark.parametrize("path", ["", "Z:/definitely/not/here.mp3"])
def test_editors_refuse_save_without_existing_file(qapp, db, monkeypatch,
                                                   path):
    from ui.dialogs.jingle_editor_dialog import JingleEditorDialog
    from ui.dialogs.sweeper_editor_dialog import SweeperEditorDialog
    warned = []
    monkeypatch.setattr(_dialogs, "warning",
                        lambda *a, **k: warned.append(a[1] if len(a) > 1
                                                      else ""))
    monkeypatch.setattr(db, "add_jingle",
                        lambda *a, **k: pytest.fail("must not insert"))
    monkeypatch.setattr(db, "add_sweeper",
                        lambda *a, **k: pytest.fail("must not insert"))
    for dlg_cls, sig in ((JingleEditorDialog, "jingle_saved"),
                         (SweeperEditorDialog, "sweeper_saved")):
        d = dlg_cls(db)
        fired = []
        getattr(d, sig).connect(fired.append)
        d._title_input.setText("Has A Title")
        d._file_input.setText(path)
        d._on_save()
        assert fired == []
        d.deleteLater()
    assert warned == ["Audio file required"] * 2
