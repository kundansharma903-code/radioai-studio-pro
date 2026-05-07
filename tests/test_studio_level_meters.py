"""
Studio LR level meters — wired to AudioEngine.get_levels.

Operator (Kavish) reported 2026-05-07: the LR indicator on the
Studio screen was dead — bars showed nothing while a song played.
The _LevelMeters widget already had a set_levels(left, right) method
+ a 30Hz internal idle-decay tick, but no caller ever pushed real
data into it.

Fix: AudioEngine gained a get_levels(channel_id) -> (float, float)
helper that reads BASS_ChannelGetLevel and normalizes to 0.0–1.0.
Studio runs a 30Hz QTimer that polls this for the active deck cid
and feeds the meter widget.

Pinned behaviour:
  • Studio's _poll_levels reads engine.get_levels for the active
    deck channel and pushes the result to _level_meters.set_levels.
  • No-op when the deck is idle (_playback_cid is None) — the meter
    widget keeps its decorative idle-decay animation.
  • No-op when the engine is missing or doesn't expose get_levels —
    test fakes / older engine variants stay silent without raising.
  • engine.get_levels returns (0,0) for unknown channel ids and on
    BASS error sentinel (0xFFFFFFFF).
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.studio import Studio


def _make_studio(db) -> Studio:
    return Studio(db, parent=None, engine=None,
                  scheduler=None, instant_jingle_engine=None,
                  sweeper_engine=None)


@pytest.fixture
def db():
    return Database()


# ── Studio _poll_levels behaviour ────────────────────────────────────────

def test_poll_levels_no_op_when_engine_missing(qapp, db):
    studio = _make_studio(db)
    # Pretend a deck is playing but no engine is wired
    studio._playback_cid = 5
    # Should not raise
    studio._poll_levels()
    studio.deleteLater()


def test_poll_levels_no_op_when_deck_idle(qapp, db):
    """Engine present, but _playback_cid is None → poll should skip
    the get_levels call entirely (deck is idle)."""
    calls: list[int] = []

    class _FakeEngine:
        def get_levels(self, cid):
            calls.append(int(cid))
            return (0.5, 0.5)

    studio = _make_studio(db)
    studio._engine = _FakeEngine()
    studio._playback_cid = None

    studio._poll_levels()

    assert calls == []
    studio.deleteLater()


def test_poll_levels_pushes_to_meter_widget(qapp, db):
    """Active deck → poll calls engine.get_levels and forwards the
    tuple to _level_meters.set_levels."""
    pushed: list[tuple[float, float]] = []

    class _FakeEngine:
        def get_levels(self, cid):
            return (0.42, 0.71)

    studio = _make_studio(db)
    studio._engine = _FakeEngine()
    studio._playback_cid = 17

    # Spy on set_levels
    real_set = studio._level_meters.set_levels
    def _spy(l, r):
        pushed.append((l, r))
        real_set(l, r)
    studio._level_meters.set_levels = _spy

    studio._poll_levels()

    assert pushed == [(0.42, 0.71)]
    studio.deleteLater()


def test_poll_levels_handles_engine_exception(qapp, db):
    """A blip in BASS_ChannelGetLevel must not crash the 30Hz timer —
    broadcast safety, same rule as scheduler tick."""
    class _FakeEngine:
        def get_levels(self, cid):
            raise RuntimeError("BASS blip")

    studio = _make_studio(db)
    studio._engine = _FakeEngine()
    studio._playback_cid = 17

    studio._poll_levels()    # must not raise
    studio.deleteLater()


# ── AudioEngine get_levels contract ──────────────────────────────────────

def test_engine_get_levels_returns_zero_for_unknown_channel(qapp):
    """AudioEngine.get_levels must return (0.0, 0.0) for ids it doesn't
    track — never raise, always a 2-tuple of floats. Paint-loop
    primitive."""
    from core.audio import AudioEngine
    eng = AudioEngine()
    try:
        levels = eng.get_levels(99999999)   # very unlikely to exist
        assert isinstance(levels, tuple) and len(levels) == 2
        assert levels == (0.0, 0.0)
    finally:
        eng.cleanup_all()
