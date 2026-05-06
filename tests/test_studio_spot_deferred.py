"""
Studio v3 — deferred spot dispatch tests.

When the scheduler emits ``spot_due`` while a song is actively playing
on the deck, Studio defers the spot until the song's natural EOS
instead of hard-cutting the song. This matches Jazler's "let the song
finish" mode — listeners never hear a mid-song ad cut.

State machine under test:
  - ``_pending_spot_campaign_id`` cached when spot_due fires during a
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
    assert studio._pending_spot_campaign_id is None

    studio._do_scheduler_spot_due(12345)

    # Deck channel survives (no cleanup, no replacement)
    assert studio._playback_cid == cid_before
    assert studio._playback_kind == "deck"
    assert studio._current_track is not None
    assert studio._current_track["id"] == song_a["id"]
    # Pending cached for later consumption
    assert studio._pending_spot_campaign_id == 12345


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

    studio._pending_spot_campaign_id = 99999

    studio._on_engine_playback_ended(cid)
    qtbot.wait(50)

    # Pending consumed
    assert studio._pending_spot_campaign_id is None
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
    assert studio._pending_spot_campaign_id is None


# ── 4. Stop-next clears pending ───────────────────────────────────────


def test_stop_next_clears_pending_spot(qtbot, studio):
    """Operator hits stop-next mid-song with a deferred spot pending.
    Song EOS runs path (b) — pending must be dropped so the spot
    doesn't slip into the operator's intended silence."""
    song_a = studio._queue_songs[0]
    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid = studio._playback_cid

    studio._pending_spot_campaign_id = 11111
    studio._stop_after_current = True

    studio._on_engine_playback_ended(cid)
    qtbot.wait(50)

    assert studio._pending_spot_campaign_id is None
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

    studio._pending_spot_campaign_id = 22222
    studio._loop_enabled = True

    studio._on_engine_playback_ended(cid_first)
    qtbot.wait(50)

    # Loop replayed: same song, fresh channel id
    assert studio._pending_spot_campaign_id is None
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
    s._pending_spot_campaign_id = 77777
    assert sch.is_running() is True

    s._on_auto_pill_clicked()

    assert sch.stop_calls == 1
    assert sch.is_running() is False
    assert s._auto_advance_enabled is False
    assert s._pending_spot_campaign_id is None


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
