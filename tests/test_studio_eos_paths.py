"""
Studio EOS-path unit tests (Phase D6 — covering the D5 four paths).

The Phase D5 _on_engine_playback_ended handler branches on
_playback_kind into four paths:

  (a) kind == 'spot'  → advance from _pre_spot_song_id (Jazler)
  (b) kind == 'deck' + _stop_after_current → idle + flag auto-reset
  (c) kind == 'deck' + _loop_enabled → replay same song
  (d) kind == 'deck' otherwise → auto-advance to next queue item

Each path has one test. Tests use the real AudioEngine (so the channel
lifecycle is exercised end-to-end), the real Database (queue_songs are
loaded from real DB), and trigger EOS programmatically by calling
_on_engine_playback_ended(cid). No scheduler fixture needed — D5 keeps
auto-advance internal to Studio.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.studio import Studio


@pytest.fixture
def studio(qtbot, engine):
    """Studio with the shared engine fixture from conftest.py and a
    fresh Database singleton. No scheduler — these tests cover Studio's
    internal auto-advance logic, which doesn't depend on the scheduler
    (per Q4: scheduler.song_auto_advance signal is reserved for Phase E)."""
    db = Database()
    s = Studio(db=db, engine=engine, scheduler=None)
    if len(s._queue_songs) < 2:
        pytest.skip("queue needs ≥2 playable DB songs for EOS tests")
    yield s
    # Per-test cleanup so a leftover channel doesn't pollute other tests.
    if s._playback_cid is not None:
        try:
            engine.cleanup(s._playback_cid)
        except Exception:
            pass


# ── Path (d): auto-advance ──────────────────────────────────────────────

def test_eos_auto_advance(qtbot, studio):
    song_a = studio._queue_songs[0]
    song_b = studio._queue_songs[1]

    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid_a = studio._playback_cid
    assert cid_a is not None
    assert studio._current_track["id"] == song_a["id"]

    studio._on_engine_playback_ended(cid_a)
    qtbot.wait(50)

    assert studio._playback_kind == "deck"
    assert studio._current_track is not None
    assert studio._current_track["id"] == song_b["id"]


# ── Path (c): loop replays same song ───────────────────────────────────

def test_eos_loop_replays(qtbot, studio):
    song_a = studio._queue_songs[0]

    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid_first = studio._playback_cid

    # Enable loop BEFORE simulating EOS
    studio._loop_enabled = True
    studio._on_engine_playback_ended(cid_first)
    qtbot.wait(50)

    cid_second = studio._playback_cid
    assert cid_second is not None
    # Channel id is never-reused (Phase A contract) — second load gets
    # a strictly higher id even though the song dict is identical.
    assert cid_second > cid_first
    assert studio._current_track["id"] == song_a["id"]
    assert studio._playback_kind == "deck"


# ── Path (b): stop-next halts to idle, flag auto-resets ────────────────

def test_eos_stop_next_idle_resets(qtbot, studio):
    song_a = studio._queue_songs[0]

    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid_a = studio._playback_cid

    studio._stop_after_current = True
    studio._on_engine_playback_ended(cid_a)
    qtbot.wait(50)

    assert studio._playback_cid is None
    assert studio._current_track is None
    assert studio._stop_after_current is False, \
        "stop-next flag must auto-reset after consume (Q5)"


# ── Path (a): spot EOS resumes with NEXT song after pre-spot anchor ────

def test_spot_eos_resumes_next(qtbot, studio):
    """Set up Studio state to mimic 'song A was playing, scheduler
    fired a spot, spot is now ending'. Verify the post-spot resume
    advances to song B (Jazler convention — spot replaces a slot)."""
    song_a = studio._queue_songs[0]
    song_b = studio._queue_songs[1]

    # Load song A as if it were the spot's audio (we just need a real
    # channel on the engine to satisfy cleanup() in the EOS handler).
    studio._on_queue_song_play(song_a)
    qtbot.wait(50)
    cid = studio._playback_cid

    # Manually flip state to "spot mode" — this mimics what
    # _on_scheduler_spot_due does after stopping the deck.
    studio._playback_kind = "spot"
    studio._playback_campaign_id = 999       # arbitrary
    studio._pre_spot_song_id = song_a["id"]

    studio._on_engine_playback_ended(cid)
    qtbot.wait(50)

    assert studio._playback_kind == "deck"
    assert studio._current_track is not None
    assert studio._current_track["id"] == song_b["id"], \
        f"expected post-spot resume to advance to B (id={song_b['id']}), " \
        f"got {studio._current_track.get('id')}"
    assert studio._pre_spot_song_id is None, \
        "pre_spot anchor must be cleared after use"
