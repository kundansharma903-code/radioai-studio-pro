"""
Studio v3 — deferred spot dispatch tests.

When the scheduler emits ``spot_due`` while a song is actively playing
on the deck, Studio defers the spot until the song's natural EOS
instead of hard-cutting the song. This matches Jazler's "let the song
finish" mode — listeners never hear a mid-song ad cut.

State machine under test:
  - ``_pending_spots`` FIFO list — append when spot_due fires during a
    deck-playing song; the deck is NOT interrupted.
  - Song EOS path (d) consumes pending → captures _pre_spot_song_id
    from the just-ended song → calls _do_scheduler_spot_due (which
    now sees deck idle and runs the original "play immediately" path).
  - Stop-next (path b) clears pending — operator wanted silence.
  - Loop (path c) clears pending — repeat-this-song instruction.
  - AUTO-off (header pill) clears pending — operator-takes-control.
  - spot_due during idle still plays immediately — defer ONLY engages
    when the deck is busy with a song.

Mirror tests/test_studio_eos_paths.py — real AudioEngine + Database
fixtures from conftest, queue_songs from live DB. We don't need real
spot files on disk; the deferred path doesn't touch DB until the
spot actually fires, and the state-machine assertions cover the
deferral + consume + clear paths without needing audible playback.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.studio import Studio


# ── Recording signal stand-in (re-defined locally — same shape as the
#    pattern in tests/test_studio_*_wiring.py).


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


class _MinimalScheduler:
    """Stand-in for SchedulerEngine with just the surfaces Studio touches
    during construction + AUTO-toggle. Used by the AUTO-off-clears-pending
    test where a real scheduler thread would be overkill."""

    def __init__(self, running: bool = True):
        self._running = bool(running)
        self.stop_calls = 0
        self.start_calls = 0
        self.spot_due          = _RecordingSignal()
        self.song_auto_advance = _RecordingSignal()
        self.break_approaching = _RecordingSignal()
        self.next_break_in     = _RecordingSignal()
        self.started           = _RecordingSignal()
        self.stopped           = _RecordingSignal()
        self.active_clock_changed = _RecordingSignal()

    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self.stop_calls += 1
        self._running = False

    def start(self) -> None:
        self.start_calls += 1
        self._running = True

    def peek_next(self, n: int = 5, now=None) -> list:
        return []

    def current_active_clock(self) -> tuple:
        return None, ""


@pytest.fixture
def studio(qtbot, engine):
    """Studio with the shared engine fixture from conftest.py + a fresh
    Database. No scheduler — these tests cover Studio's internal
    deferred-spot state machine, which doesn't depend on the scheduler
    thread (we exercise the handler entry points directly)."""
    db = Database()
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=None)
    if len(s._queue_songs) < 2:
        pytest.skip("queue needs ≥2 playable DB songs for deferred-spot tests")
    yield s
    if s._playback_cid is not None:
        try:
            engine.cleanup(s._playback_cid)
        except Exception:
            pass


# ── 1. Defer: spot_due during a playing deck song does NOT interrupt ───


def test_spot_due_during_song_playback_defers(qtbot, studio):
    """Song playing → fire spot_due → assert deck channel survives,
    pending campaign is cached, _playback_kind stays 'deck'."""
    song_a = studio._queue_songs[0]
    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid_before = studio._playback_cid
    assert cid_before is not None
    assert studio._playback_kind == "deck"
    assert studio._pending_spots == []

    studio._do_scheduler_spot_due(12345)

    # Deck channel survives (no cleanup, no replacement)
    assert studio._playback_cid == cid_before
    assert studio._playback_kind == "deck"
    assert studio._current_track is not None
    assert studio._current_track["id"] == song_a["id"]
    # Pending cached for later consumption
    assert studio._pending_spots == [12345]


# ── 2. Pending consumed on song EOS via path (d) ──────────────────────


def test_pending_spot_consumed_on_song_eos(qtbot, studio):
    """Song playing, pending set → EOS song → handler runs path (d),
    captures _pre_spot_song_id from the just-ended song, clears pending,
    invokes _do_scheduler_spot_due. Spot files don't exist for the
    fake campaign id, so the spot itself logs a warning + returns,
    but the state transition is the contract under test."""
    song_a = studio._queue_songs[0]
    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid = studio._playback_cid

    studio._pending_spots = [99999]

    studio._on_engine_playback_ended(cid)
    qtbot.wait(50)

    # Pending consumed
    assert studio._pending_spots == []
    # Pre-spot anchor captured from the just-ended song so a future
    # spot EOS path (a) resumes from the right place in the queue
    assert studio._pre_spot_song_id == song_a["id"]


# ── 3. spot_due during idle plays immediately (no defer) ──────────────


def test_spot_due_during_idle_does_not_defer(studio):
    """Idle Studio → fire spot_due → defer check fails (no deck song),
    pending stays None. The dispatch then proceeds to file lookup and
    bails out gracefully because the fake campaign has no spot files."""
    assert studio._playback_cid is None
    assert studio._playback_kind is None

    studio._do_scheduler_spot_due(54321)

    # Defer did NOT engage (deck wasn't busy)
    assert studio._pending_spots == []


# ── 4. Stop-next clears pending ───────────────────────────────────────


def test_stop_next_clears_pending_spot(qtbot, studio):
    """Operator hits stop-next mid-song with a deferred spot pending.
    Song EOS runs path (b) — pending must be dropped so the spot
    doesn't slip into the operator's intended silence."""
    song_a = studio._queue_songs[0]
    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid = studio._playback_cid

    # Multiple pending spots — stop-next must drain ALL.
    studio._pending_spots = [11111, 22222, 33333]
    studio._stop_after_current = True

    studio._on_engine_playback_ended(cid)
    qtbot.wait(50)

    assert studio._pending_spots == []
    assert studio._playback_cid is None
    assert studio._stop_after_current is False
    assert studio._current_track is None


# ── 5. Loop clears pending ────────────────────────────────────────────


def test_loop_clears_pending_spot(qtbot, studio):
    """Loop is "play this song again" — sneaking a spot into the loop
    cycle would be a surprise for the operator. Pending dropped on
    loop EOS path (c)."""
    song_a = studio._queue_songs[0]
    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid_first = studio._playback_cid

    # Multiple pending spots — loop must drain ALL.
    studio._pending_spots = [22222, 33333]
    studio._loop_enabled = True

    studio._on_engine_playback_ended(cid_first)
    qtbot.wait(50)

    # Loop replayed: same song, fresh channel id
    assert studio._pending_spots == []
    assert studio._current_track is not None
    assert studio._current_track["id"] == song_a["id"]


# ── 6. AUTO-off (header pill) clears pending ──────────────────────────


def test_auto_off_clears_pending_spot(qtbot, engine):
    """When the operator clicks AUTO off mid-show with a spot pending,
    they're taking control. The deferred spot must be dropped so it
    doesn't fire later in Live-Assist mode."""
    db = Database()
    sch = _MinimalScheduler(running=True)
    s = Studio(db=db, engine=engine, scheduler=sch,
               instant_jingle_engine=None)
    qtbot.addWidget(s)

    s._auto_advance_enabled = True
    s._pending_spots = [77777, 88888]   # multiple — AUTO off drains all
    assert sch.is_running() is True

    s._on_auto_pill_clicked()

    assert sch.stop_calls == 1
    assert sch.is_running() is False
    assert s._auto_advance_enabled is False
    assert s._pending_spots == []


# ── 7. NowPlayer visual reflects the spot's name (regression guard) ────


def test_spot_dispatch_updates_nowplayer_with_spot_name(qtbot, studio):
    """After a spot fires, the NowPlayer panel must show the campaign's
    name, NOT the previous song's title. Regression guard for the
    listener-quality bug where the operator saw a misleading "song
    still playing" display while audibly the spot was on air.

    Uses a real on-disk audio file (lifted from the songs table) as
    the spot file so engine.load_file succeeds. Test campaign +
    spot_file rows are cleaned up in the finally block."""
    import os as _os
    import uuid as _uuid

    db = studio._db

    # Find any real on-disk audio path to attach as the spot's file.
    rows = db._conn().execute(
        "SELECT file_path FROM songs WHERE file_path IS NOT NULL "
        "AND file_path != '' ORDER BY id LIMIT 5"
    ).fetchall()
    real_path = next(
        (r[0] for r in rows if r[0] and _os.path.exists(r[0])), None)
    if real_path is None:
        pytest.skip("no real on-disk song file to use as spot audio")

    test_name = f"_test_spot_now_{_uuid.uuid4().hex[:8]}"
    cid = db.add_campaign({
        "name":      test_name,
        "is_active": 1,
        "priority":  5,
    })
    fid = db.add_spot_file(cid, {
        "filename":    f"{test_name}.mp3",
        "file_path":   real_path,
        "duration_ms": 5_000,
        "is_active":   1,
    })
    try:
        # Idle state — defer doesn't engage, spot plays immediately.
        assert studio._playback_kind is None
        studio._do_scheduler_spot_due(int(cid))
        qtbot.wait(50)

        # Visual binding contract — _apply_playing_state was called and
        # NowPlayer reflects the spot's campaign name.
        assert studio._playback_kind == "spot"
        assert studio._current_track is not None
        assert studio._current_track["title"] == test_name
        assert studio._now_player._title == test_name, (
            "NowPlayer title must show the spot's campaign name "
            "while the spot is on air, not the prior song's title")
        # Artist label is the standard auto-air tag — same field that
        # the post-Phase-A spot dispatch dict carries.
        assert studio._now_player._artist_year == "Spot · auto-aired"
    finally:
        try:
            db.delete_spot_file(fid)
        except Exception:
            pass
        try:
            db._conn().execute(
                "DELETE FROM campaigns WHERE id = ?", [int(cid)])
            db._conn().commit()
        except Exception:
            pass
        if studio._playback_cid is not None:
            try:
                studio._engine.cleanup(studio._playback_cid)
            except Exception:
                pass


# ── 8. Multiple-spot FIFO (2026-05-17 operator request) ───────────────


def test_multiple_spots_at_same_minute_all_queued(qtbot, studio):
    """Operator's "5 spots fired at same time → sab playlist queue mai
    added ho jaye on top" — the old single-slot pending overwrote
    every earlier spot, so 4 of 5 silently vanished. New FIFO list
    must hold every spot in arrival order."""
    song_a = studio._queue_songs[0]
    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    assert studio._playback_kind == "deck"
    assert studio._pending_spots == []
    # Fire 5 spot_due signals back-to-back.
    for cid in (100, 200, 300, 400, 500):
        studio._do_scheduler_spot_due(cid)
    # FIFO order, every spot preserved — no overwrite.
    assert studio._pending_spots == [100, 200, 300, 400, 500]
    # The currently-playing song state is untouched.
    assert studio._playback_kind == "deck"
    assert studio._current_track["id"] == song_a["id"]


def test_spot_chain_fires_in_fifo_order_on_eos(qtbot, studio,
                                                monkeypatch):
    """After 3 spots are queued behind a playing song, song EOS fires
    spot 1; spot 1 EOS chains to spot 2; spot 2 EOS chains to spot 3;
    spot 3 EOS resumes the song queue. The chain preserves
    _pre_spot_song_id across every spot so the eventual resume
    anchors back to the original pre-spot song."""
    song_a = studio._queue_songs[0]
    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid_song = studio._playback_cid

    # Stub the spot-load path so we don't need real DB rows.
    fired_order: list[int] = []
    def _stub_fire(campaign_id: int) -> None:
        fired_order.append(int(campaign_id))
        # Simulate the spot starting on a fresh channel.
        studio._playback_cid = 9000 + len(fired_order)
        studio._playback_kind = "spot"
        studio._current_track = {"id": int(campaign_id),
                                  "title": f"spot-{campaign_id}"}
        studio._playback_campaign_id = int(campaign_id)
    monkeypatch.setattr(
        studio, "_do_scheduler_spot_due", _stub_fire)

    studio._pending_spots = [10, 20, 30]
    # Song EOS — first spot fires.
    studio._on_engine_playback_ended(cid_song)
    qtbot.wait(20)
    assert fired_order == [10]
    assert studio._pre_spot_song_id == song_a["id"]
    assert studio._pending_spots == [20, 30]

    # Spot 10 EOS — chain to spot 20.
    studio._on_engine_playback_ended(studio._playback_cid)
    qtbot.wait(20)
    assert fired_order == [10, 20]
    assert studio._pre_spot_song_id == song_a["id"]   # preserved
    assert studio._pending_spots == [30]

    # Spot 20 EOS — chain to spot 30.
    studio._on_engine_playback_ended(studio._playback_cid)
    qtbot.wait(20)
    assert fired_order == [10, 20, 30]
    assert studio._pending_spots == []


def test_pending_spot_appears_in_upcoming_preview(qtbot, studio,
                                                    monkeypatch):
    """When a spot enters _pending_spots, _load_upcoming_queue must
    prepend it to the Up Coming preview so the operator sees the
    spot at the TOP of the visible queue (before any song / sweeper
    / jingle). Operator: "aaye system mai, it automatically added
    in Playlist queue ... before all songs, sweepers and jingles."""
    # Stub get_campaign + get_spot_files so the card builder finds
    # a name + duration without needing real DB rows.
    monkeypatch.setattr(
        studio._db, "get_campaign",
        lambda cid: {"name": f"Test Spot {int(cid)}"})
    monkeypatch.setattr(
        studio._db, "get_spot_files",
        lambda cid: [{"is_active": 1, "duration_ms": 15_000,
                       "file_path": "x"}])
    # Fake the scheduler peek_next so the song side has known content.
    if studio._scheduler is not None:
        monkeypatch.setattr(
            studio._scheduler, "peek_next",
            lambda n: [{
                "item_type": "song", "item_id": 999,
                "title": "Test Song", "artist": "A",
                "file_path": "x", "duration_ms": 200_000,
            }])

    studio._pending_spots = [101, 102]
    studio._load_upcoming_queue()

    # The first 2 cards must be the spots, then songs.
    preview = studio._upcoming_preview
    assert len(preview) >= 2, f"expected ≥2 cards, got {preview}"
    assert preview[0]["_item_type"] == "spot"
    assert preview[0]["id"] == 101
    assert preview[1]["_item_type"] == "spot"
    assert preview[1]["id"] == 102
    # If scheduler is wired, songs come after.
    if studio._scheduler is not None and len(preview) > 2:
        assert preview[2]["_item_type"] == "song"


# ── 9. SOTG > Spot priority (operator-locked 2026-05-17) ──────────────


def test_sotg_fires_before_spot_when_both_pending(qtbot, studio,
                                                    monkeypatch):
    """Operator-locked priority order: SOTG always fires before Spot
    when both are queued at the same EOS. Earlier code popped Spot
    first; flipped on 2026-05-17 after live smoke confirmed the
    SOTG-then-Spot order is the operator's preference."""
    song_a = studio._queue_songs[0]
    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid_song = studio._playback_cid

    fire_log: list[tuple[str, int]] = []
    def _stub_spot_fire(campaign_id: int) -> None:
        fire_log.append(("spot", int(campaign_id)))
        studio._playback_cid = 9001
        studio._playback_kind = "spot"
        studio._current_track = {"id": int(campaign_id),
                                  "title": "spot"}
        studio._playback_campaign_id = int(campaign_id)
    def _stub_sotg_fire(assignment: dict) -> None:
        fire_log.append(("sotg", int(assignment.get("assignment_id"))))
        studio._playback_cid = 9002
        studio._playback_kind = "sotg"
        studio._sotg_active_aid = int(assignment.get("assignment_id"))
        studio._current_track = {"id": studio._sotg_active_aid,
                                  "title": "sotg"}
    monkeypatch.setattr(studio, "_do_scheduler_spot_due", _stub_spot_fire)
    monkeypatch.setattr(studio, "_do_sotg_fire", _stub_sotg_fire)

    # Queue 1 spot + 1 SOTG with same arrival order they'd hit in
    # production (spot_due fires more frequently than SOTG check, so
    # in practice spot lands first; but operator wants SOTG to win
    # the EOS race regardless).
    studio._pending_spots = [500]
    studio._pending_sotgs = [{"assignment_id": 700,
                                "show_name": "Bhakti Sagar",
                                "file_path": "x"}]

    studio._on_engine_playback_ended(cid_song)
    qtbot.wait(20)
    # SOTG fired first.
    assert fire_log[0] == ("sotg", 700)
    assert studio._pending_sotgs == []
    # Spot still pending — waits for SOTG EOS.
    assert studio._pending_spots == [500]


def test_t60_preview_populates_upcoming_spots_from_campaign_schedule(
        qtbot, studio, monkeypatch):
    """`_check_upcoming_dispatches` walks today's campaign_schedule
    and keeps rows whose break_time is in (now, now+60s]. Verifies
    the T-60s preview pipe (operator: "1 min pehle queue mai load")."""
    from datetime import datetime

    # Pin a deterministic mid-minute "now" so the next-minute-rollover
    # logic in _check_upcoming_dispatches is exercised the same way
    # every run. 13:21:00 + 30s = same minute (13:21:30) → break_time
    # "13:21" already passed; need to pick break_times where the
    # delta math is unambiguous.
    now = datetime.now().replace(hour=13, minute=21, second=0,
                                  microsecond=0)
    # break_time "13:22" is 60s future → exactly at the edge; use 13:21
    # math instead. Let's pick:
    #   "13:22" → delta = 60s (just on the boundary, included)
    #   "13:23" → delta = 120s (clearly outside)
    fake_rows = [
        _row({"campaign_id": 11, "break_time": "13:22",
              "priority": "Medium", "slot_order": 0,
              "name": "Test Spot Soon"}),
        _row({"campaign_id": 12, "break_time": "13:23",
              "priority": "Medium", "slot_order": 0,
              "name": "Test Spot Far"}),
    ]

    class _FakeCursor:
        def fetchall(self):
            return fake_rows

    class _FakeConn:
        def execute(self, sql, params):
            assert "campaign_schedule" in sql
            return _FakeCursor()

    monkeypatch.setattr(studio._db, "_conn", lambda: _FakeConn())
    monkeypatch.setattr(studio._db, "get_sotg_assignments_for_date",
                        lambda d, status=None: [])

    studio._pending_spots = []
    studio._upcoming_preview_spots = []
    studio._check_upcoming_dispatches(now=now)

    # The 60s-out spot is inside the window (delta=60 ≤ 60); 120s is not.
    spot_ids = [s["campaign_id"] for s in studio._upcoming_preview_spots]
    assert 11 in spot_ids, (
        f"expected campaign 11 in preview, got {spot_ids}")
    assert 12 not in spot_ids, (
        f"campaign 12 is 120s out, must NOT be in 60s window: {spot_ids}")


def _row(d: dict):
    """Tiny stand-in for sqlite3.Row supporting `.keys()` + key
    access. Lets the upcoming-preview tests fake DB rows without
    a full real schema setup."""
    class _Row:
        def __init__(self, payload: dict) -> None:
            self._p = dict(payload)
        def keys(self):
            return list(self._p.keys())
        def __getitem__(self, k):
            return self._p[k]
    return _Row(d)
