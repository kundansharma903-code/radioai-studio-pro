"""
Studio StopNext button — skip-to-next semantic.

Operator (Kavish) feedback 2026-05-07: with the previous "stop after
current ends" semantic, clicking StopNext didn't visibly stop the
song or advance the queue. The ⏭ icon mental model is "skip to next
track NOW", not "stop after current". Rewrote the handler to drive
through the same EOS path a natural song-end would, so:

  • Deck channel cleans up immediately.
  • Auto-advance (if AUTO is on) picks the next scheduler slot and
    loads it — Up Coming queue + NEXT chip refresh as a side effect.
  • Idle-deck case is a clean no-op.

This file pins the new contract.
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.studio import Studio


def _make_studio(db) -> Studio:
    """Studio with no real engine — tests inject a thin fake into
    self._engine after construction so the ctor's signal-connect
    path doesn't try to wire signals on the fake."""
    return Studio(db, parent=None, engine=None,
                  scheduler=None, instant_jingle_engine=None,
                  sweeper_engine=None)


@pytest.fixture
def db():
    return Database()


# ── Skip behaviour ─────────────────────────────────────────────────────────

def test_idle_deck_click_is_noop(qapp, db):
    """No song is playing → click is a no-op (no exception, no state change)."""
    studio = _make_studio(db)
    # _engine is None and _playback_cid is None — both fail-fast guards
    studio._on_stop_next_clicked()        # must not raise
    assert studio._playback_cid is None
    studio.deleteLater()


def test_click_drives_through_eos_path(qapp, db):
    """Active deck → click invokes the EOS handler with the deck cid.
    The EOS path is what auto-advances; this test just verifies the
    handler routes through it. We empty _queue_songs so the EOS chain
    idles cleanly without trying to load a follow-up track on the
    fake engine."""
    cleanups: list[int] = []
    eos_calls: list[int] = []

    class _FakeEngine:
        def cleanup(self, cid):
            cleanups.append(int(cid))

    studio = _make_studio(db)
    studio._engine = _FakeEngine()
    studio._playback_cid = 42
    studio._playback_kind = "deck"
    studio._current_track = {"id": 1}
    studio._queue_songs = []     # avoids the fake engine's missing load_file

    # Spy the EOS handler — verifies StopNext routes through it
    real_eos = studio._on_engine_playback_ended
    def _spy_eos(cid):
        eos_calls.append(int(cid))
        return real_eos(cid)
    studio._on_engine_playback_ended = _spy_eos

    studio._on_stop_next_clicked()

    assert eos_calls == [42], "StopNext must invoke the EOS path"
    # The EOS path also calls cleanup internally (line 3725); the test
    # confirms the chain at least once cleans the right channel.
    assert 42 in cleanups
    studio.deleteLater()


def test_click_clears_playback_cid(qapp, db):
    """After the EOS path runs, the deck cid is cleared so the next
    play action starts fresh."""
    class _FakeEngine:
        def cleanup(self, cid): pass

    studio = _make_studio(db)
    studio._engine = _FakeEngine()
    studio._playback_cid = 99
    studio._playback_kind = "deck"
    studio._current_track = {"id": 1}
    studio._queue_songs = []

    studio._on_stop_next_clicked()

    assert studio._playback_cid is None
    studio.deleteLater()


def test_no_engine_click_is_noop(qapp, db):
    """Even with a deck cid set, no engine → no-op (defensive)."""
    studio = _make_studio(db)
    # engine is None, but pretend a cid is set
    studio._playback_cid = 12

    studio._on_stop_next_clicked()        # must not raise

    # cid stays put because the no-op short-circuits before EOS path
    assert studio._playback_cid == 12
    studio.deleteLater()
