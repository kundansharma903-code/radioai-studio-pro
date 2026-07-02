"""
Studio · Spot on the Go broadcast dispatch (Phase 1).

Pinned behaviour:

DB:
  • get_sotg_assignments_for_date(date, status=None) returns rows
    joined with link + show metadata, ordered by sharp_time.
  • mark_sotg_assignment_missed stamps MISSED + updated_at.

Studio dispatcher:
  • _sotg_check_tick polls today's READY assignments.
  • Assignments inside ±_SOTG_FIRE_TOLERANCE_S fire via _do_sotg_fire.
  • Assignments past _SOTG_MISS_THRESHOLD_S get stamped MISSED.
  • Priority semantics:
      - HIGH on song → fade outgoing deck, play SOTG on fresh channel
      - LOW on song → append to _pending_sotgs FIFO until EOS
      - On idle deck (or HIGH after fade)→ play immediately
      - On paid spot → defer until spot EOS (paid spot wins)
  • SOTG EOS path resumes the song queue from _pre_sotg_song_id.

Mocks: minimal _FakeAudioEngine + _FakeScheduler that carry the
signals Studio's __init__ touches.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta

import pytest

from core.database import Database


# ── Test doubles ────────────────────────────────────────────────────────


class _RecordingSignal:
    def __init__(self):
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, _slot=None) -> None:
        self._slots.clear()

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class _FakeAudioEngine:
    def __init__(self):
        self.calls: list[tuple] = []
        self.position_changed = _RecordingSignal()
        self.playback_ended = _RecordingSignal()
        self.error_occurred = _RecordingSignal()
        self._next_cid = 100

    def load_file(self, path, loop=False):
        cid = self._next_cid
        self._next_cid += 1
        self.calls.append(("load", path, cid))
        return cid

    def set_volume(self, cid, vol):
        self.calls.append(("vol", int(cid), int(vol)))

    def play(self, cid):
        self.calls.append(("play", int(cid)))

    def fade_volume_to(self, cid, target, dur_ms):
        self.calls.append(("fade", int(cid), int(target), int(dur_ms)))

    def cleanup(self, cid):
        self.calls.append(("cleanup", int(cid)))

    def cleanup_all(self):
        self.calls.append(("cleanup_all",))

    def get_levels(self, _cid):
        return (0.0, 0.0)

    def get_state(self, _cid):
        return "stopped"

    def get_duration_ms(self, _cid):
        return 60_000


class _FakeIJE:
    def __init__(self):
        self.calls: list[tuple] = []
        self.pad_started = _RecordingSignal()
        self.pad_ended = _RecordingSignal()
        self.pad_stopped = _RecordingSignal()

    def play_pad(self, *a, **k): return True
    def stop_pad(self, _id):    return True
    def stop_all(self):         return 0
    def is_playing(self, _id):  return False


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded_show(db):
    sid = db.create_sotg_show(
        rj_name=f"RJ {uuid.uuid4().hex[:6]}",
        show_name=f"Disp Show {uuid.uuid4().hex[:6]}",
        days="Daily", time_start="04:00", time_end="07:00",
        color="#06b6d4", description="",
        link_names=["L1", "L2", "L3"])
    yield sid
    try:
        db.delete_sotg_show(sid)
    except Exception:
        pass


# ── DB helpers ─────────────────────────────────────────────────────────


def test_get_for_date_returns_joined_rows(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    lid = int(show["links"][0]["id"])
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    db.upsert_sotg_assignment(
        show_id=seeded_show, link_id=lid,
        scheduled_date=tomorrow,
        file_path="/x/a.mp3", file_name="a.mp3",
        file_duration_ms=10_000,
        sharp_time="05:00", priority="High", status="READY")
    rows = db.get_sotg_assignments_for_date(tomorrow, status="READY")
    target = [r for r in rows if r["link_id"] == lid]
    assert len(target) == 1
    r = target[0]
    # Joined fields surface:
    assert r["show_name"].startswith("Disp Show")
    assert r["link_name"] == "L1"
    assert r["rj_name"].startswith("RJ ")
    assert r["sharp_time"] == "05:00"


def test_mark_missed_stamps_status(db, seeded_show):
    show = db.get_sotg_show(seeded_show)
    lid = int(show["links"][0]["id"])
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    aid = db.upsert_sotg_assignment(
        show_id=seeded_show, link_id=lid,
        scheduled_date=tomorrow,
        file_path="/x/a.mp3", file_name="a.mp3",
        file_duration_ms=10_000,
        sharp_time="05:00", priority="High", status="READY")
    db.mark_sotg_assignment_missed(aid)
    a = db.get_sotg_assignment(lid, tomorrow)
    assert a["status"] == "MISSED"


# ── Studio dispatcher ─────────────────────────────────────────────────


@pytest.fixture
def synthetic_assignment(tmp_path):
    """A SOTG assignment dict with a sharp_time set within the
    dispatcher's ±30s fire window + a real on-disk file the engine
    fake can 'load'.

    Phase H fix for a pre-existing wall-clock-timing flake: the
    earlier version stamped ``sharp_time = "HH:MM"`` using the
    fixture-construction minute. The dispatcher computes
    ``delta_s = (target_m - now_m) * 60 - now.second`` and only fires
    when ``abs(delta_s) <= 30``. If the fixture ran at second > 30 of
    a minute, delta_s landed at -31..-59 — outside the fire window AND
    short of the miss threshold (-60) — so the test silently failed
    with ``eng.calls == []``. The bug presented as a heisenbug because
    adding ``--log-cli-level=DEBUG`` shifted timings enough to land
    inside the window.

    The fix: pick a target minute guaranteed to be within ±30s by
    rounding to ``now + 30s`` (so we're at most 30s in the past, at
    most 30s in the future). Tests that need explicit past/far-future
    times still override ``sharp_time`` directly."""
    f = tmp_path / "sotg_test.mp3"
    f.write_bytes(b"\x00" * 256)
    now = datetime.now()
    target = now + timedelta(seconds=30)
    return {
        "assignment_id":   123,
        "show_id":         1,
        "link_id":         42,
        "scheduled_date":  date.today().isoformat(),
        "file_path":       str(f),
        "file_name":       f.name,
        "file_duration_ms": 60_000,
        "sharp_time":      f"{target.hour:02d}:{target.minute:02d}",
        "priority":        "High",
        "status":          "READY",
        "link_order":      1,
        "link_name":       "Synth Link",
        "show_name":       "Synth Show",
        "rj_name":         "RJ Synth",
        "color":           "#06b6d4",
    }


def _build_studio(db, engine, monkeypatch, qtbot,
                    today_assignments=()):
    """Construct Studio with a fake engine + DB get_sotg_assignments
    monkeypatched to return a fixed list. Returns the Studio."""
    from ui.studio import Studio
    monkeypatch.setattr(
        db, "get_sotg_assignments_for_date",
        lambda d, status=None: list(today_assignments)
        if d == date.today().isoformat() else [])
    s = Studio(db=db, engine=engine, scheduler=None,
                instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    return s


def test_due_high_on_idle_deck_fires_immediately(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    eng = _FakeAudioEngine()
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[synthetic_assignment])
    # Don't actually stamp the DB — patch out the fire/missed
    # mutations so the assignment id 123 (fake) doesn't crash.
    fired_ids: list[int] = []
    monkeypatch.setattr(
        db, "mark_sotg_assignment_fired",
        lambda aid, fired_at=None: fired_ids.append(int(aid)))
    monkeypatch.setattr(
        db, "log_play", lambda **k: None)

    # Drive the tick directly
    s._sotg_check_tick()
    # Engine should have loaded + played the file
    sequence = [c[0] for c in eng.calls]
    assert "load" in sequence
    assert "play" in sequence
    assert s._playback_kind == "sotg"
    assert s._sotg_active_aid == 123
    assert fired_ids == [123]


def test_due_high_on_song_fades_outgoing_then_plays(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    eng = _FakeAudioEngine()
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[synthetic_assignment])
    # Simulate a song currently on deck
    s._playback_kind = "deck"
    s._playback_cid = 7
    s._current_track = {"id": 88, "title": "Test Song"}
    s._master_volume = 80
    monkeypatch.setattr(
        db, "mark_sotg_assignment_fired",
        lambda aid, fired_at=None: None)
    monkeypatch.setattr(db, "log_play", lambda **k: None)

    s._sotg_check_tick()
    # Outgoing deck should have fade triggered
    assert any(c[0] == "fade" and c[1] == 7 for c in eng.calls)
    # New SOTG channel should be playing
    assert s._playback_kind == "sotg"
    assert s._pre_sotg_song_id == 88
    assert s._fading_cid == 7   # outgoing channel marked for tail-cleanup


def test_due_low_on_song_defers_until_eos(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    eng = _FakeAudioEngine()
    low = dict(synthetic_assignment)
    low["priority"] = "Low"
    low["assignment_id"] = 200
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[low])
    s._playback_kind = "deck"
    s._playback_cid = 9
    s._current_track = {"id": 88, "title": "Test Song"}

    s._sotg_check_tick()
    # Should NOT have fired yet — appended to pending FIFO list
    assert len(s._pending_sotgs) == 1
    assert s._pending_sotgs[0]["assignment_id"] == 200
    assert s._playback_kind == "deck"   # still on song
    # No load call yet
    assert all(c[0] != "load" for c in eng.calls)


def test_due_during_paid_spot_defers_regardless_of_priority(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    eng = _FakeAudioEngine()
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[synthetic_assignment])
    # Paid spot in progress
    s._playback_kind = "spot"
    s._playback_cid = 5
    s._current_track = {"id": 0, "title": "Ad"}

    s._sotg_check_tick()
    assert len(s._pending_sotgs) == 1
    # SOTG must NOT have started its own channel
    assert s._playback_kind == "spot"


def test_past_threshold_marks_missed(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    """Assignment whose sharp_time slipped past the miss threshold
    gets stamped MISSED — operator's bug report scenario."""
    eng = _FakeAudioEngine()
    now = datetime.now()
    past = now - timedelta(minutes=5)
    expired = dict(synthetic_assignment)
    expired["sharp_time"] = f"{past.hour:02d}:{past.minute:02d}"
    expired["assignment_id"] = 555
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[expired])

    missed_ids: list[int] = []
    monkeypatch.setattr(
        db, "mark_sotg_assignment_missed",
        lambda aid: missed_ids.append(int(aid)))

    s._sotg_check_tick()
    assert missed_ids == [555]
    # No engine load happened
    assert all(c[0] != "load" for c in eng.calls)


def test_far_future_ignored(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    """Far-future assignment (more than tolerance away) doesn't fire
    or get marked missed."""
    eng = _FakeAudioEngine()
    now = datetime.now()
    far = (now + timedelta(hours=3)).strftime("%H:%M")
    future = dict(synthetic_assignment)
    future["sharp_time"] = far
    future["assignment_id"] = 999
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[future])
    missed: list[int] = []
    monkeypatch.setattr(
        db, "mark_sotg_assignment_missed",
        lambda aid: missed.append(int(aid)))

    s._sotg_check_tick()
    assert missed == []
    assert all(c[0] != "load" for c in eng.calls)


def test_missing_file_marks_missed(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    """File deleted between save + fire → mark MISSED, don't crash."""
    eng = _FakeAudioEngine()
    bad = dict(synthetic_assignment)
    bad["file_path"] = "/nonexistent/path/zzz.mp3"
    bad["assignment_id"] = 700
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[bad])
    missed: list[int] = []
    monkeypatch.setattr(
        db, "mark_sotg_assignment_missed",
        lambda aid: missed.append(int(aid)))
    monkeypatch.setattr(
        db, "mark_sotg_assignment_fired",
        lambda aid, fired_at=None: None)

    s._sotg_check_tick()
    assert missed == [700]
    assert all(c[0] != "load" for c in eng.calls)


def test_sotg_eos_resumes_queue(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    """After the SOTG file plays out, the deck should resume the
    song queue from the pre-SOTG anchor."""
    eng = _FakeAudioEngine()
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[])
    # Fake state: SOTG just finished
    s._playback_kind = "sotg"
    s._playback_cid = 12
    s._sotg_active_aid = 42
    s._pre_sotg_song_id = 88
    # Stub the queue resume to a sentinel — _compute_next_song path is
    # already covered by other tests, we just want to see that it was
    # called with the right anchor.
    resume_called_with: list = []
    monkeypatch.setattr(
        s, "_compute_next_song",
        lambda after_id: resume_called_with.append(after_id) or None)
    s._on_engine_playback_ended(12)
    assert resume_called_with == [88]
    # State cleared
    assert s._pre_sotg_song_id is None
    assert s._sotg_active_aid is None


def test_crossfade_dispatch_defers_when_pending_sotg(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    """Operator-gated 2026-05-17 — when a SOTG or Spot is pending,
    _dispatch_crossfade_overlap DEFERS the entire transition. The song
    plays to its natural EOS, and EOS path (d) fires the pending SOTG
    on a clean fresh channel with NO music overlap.

    Replaces the prior "absorb" behavior which had been the source of
    the "spot overlay on music" complaint. The deferred flow preserves
    the 2026-05-14 LOW-priority-never-played fix because EOS path (d)
    drains _pending_sotgs in priority order (already covered by
    test_song_eos_fires_pending_sotg_before_auto_advance)."""
    eng = _FakeAudioEngine()
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[])
    monkeypatch.setattr(
        db, "mark_sotg_assignment_fired",
        lambda aid, fired_at=None: None)
    monkeypatch.setattr(db, "log_play", lambda **k: None)

    s._playback_kind = "deck"
    s._playback_cid = 50
    s._current_track = {"id": 88, "title": "Outgoing Song"}
    s._master_volume = 75
    pending_dict = dict(synthetic_assignment)
    pending_dict["assignment_id"] = 909
    pending_dict["priority"] = "Low"
    s._pending_sotgs = [pending_dict]

    fired = s._dispatch_crossfade_overlap()
    # Deferred — returns False, no side effects.
    assert fired is False
    # Song's state unchanged — playing on deck.
    assert s._playback_kind == "deck"
    assert s._playback_cid == 50
    # Pending SOTG still queued, will fire on EOS.
    assert len(s._pending_sotgs) == 1
    assert s._pending_sotgs[0]["assignment_id"] == 909
    # No engine activity (no load, no play, no fade).
    assert all(c[0] not in ("load", "play", "fade") for c in eng.calls), (
        f"engine should be untouched on deferral; got {eng.calls}")


def test_crossfade_dispatch_defers_when_pending_spot(
        qapp, db, qtbot, monkeypatch):
    """Same deferral for paid spots — _dispatch_crossfade_overlap
    returns False without side effects when a spot is queued. The
    spot fires on the song's natural EOS via path (d)."""
    eng = _FakeAudioEngine()
    monkeypatch.setattr(
        db, "get_sotg_assignments_for_date",
        lambda d, status=None: [])
    from ui.studio import Studio
    s = Studio(db=db, engine=eng, scheduler=None,
                instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)

    spot_fired_with: list = []
    monkeypatch.setattr(
        s, "_do_scheduler_spot_due",
        lambda cid: spot_fired_with.append(int(cid)))

    s._playback_kind = "deck"
    s._playback_cid = 60
    s._current_track = {"id": 99, "title": "Playing Song"}
    s._pending_spots = [444]

    fired = s._dispatch_crossfade_overlap()
    # Deferred — no fire, no state change.
    assert fired is False
    assert spot_fired_with == []
    assert s._playback_kind == "deck"
    assert s._playback_cid == 60
    assert s._pending_spots == [444]
    assert all(c[0] not in ("load", "play", "fade") for c in eng.calls), (
        f"engine untouched on deferral; got {eng.calls}")


def test_song_eos_fires_pending_sotg_before_auto_advance(
        qapp, db, qtbot, monkeypatch, synthetic_assignment):
    """Song EOS path picks up the deferred LOW-priority SOTG and
    fires it BEFORE asking _compute_next_song for the next track."""
    eng = _FakeAudioEngine()
    s = _build_studio(db, eng, monkeypatch, qtbot,
                       today_assignments=[])
    monkeypatch.setattr(
        db, "mark_sotg_assignment_fired",
        lambda aid, fired_at=None: None)
    monkeypatch.setattr(db, "log_play", lambda **k: None)

    # Simulate the deck mid-song with a pending SOTG cached.
    s._playback_kind = "deck"
    s._playback_cid = 21
    s._current_track = {"id": 77, "title": "Outgoing Song"}
    pending_dict = dict(synthetic_assignment)
    pending_dict["priority"] = "Low"
    pending_dict["assignment_id"] = 808
    s._pending_sotgs = [pending_dict]
    s._auto_advance_enabled = True

    # Avoid _compute_next_song being called this path
    compute_calls: list = []
    monkeypatch.setattr(
        s, "_compute_next_song",
        lambda after_id: compute_calls.append(after_id))

    s._on_engine_playback_ended(21)
    # Should have moved to SOTG playback
    assert s._playback_kind == "sotg"
    assert s._sotg_active_aid == 808
    # _compute_next_song should NOT have been called yet (SOTG plays
    # first, queue resume happens on SOTG EOS)
    assert compute_calls == []
    # Pre-SOTG anchor = the song id that just ended
    assert s._pre_sotg_song_id == 77


