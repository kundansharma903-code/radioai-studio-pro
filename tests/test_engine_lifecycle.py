"""
Engine lifecycle hardening (Phase B5).

5 tests:
  1. cleanup_all is idempotent (call twice, no error)
  2. Per-channel error isolation — when one channel cleanup raises, the
     others still get cleaned up
  3. Stale channel access after cleanup_all raises ChannelError
  4. _cleanup_engine method on MainWindow exists and is wired
  5. Engine survives cleanup_all and is reusable (load_file works again)

These tests cover the contract documented in core/audio/engine.py:
  "Caller MUST invoke cleanup_all() before BASS_Free / app shutdown.
   The engine intentionally does NOT implement __del__ — Python GC
   ordering is unreliable with Qt teardown."
"""

from __future__ import annotations

import pytest

from core.audio import AudioEngine, ChannelError


# ── Test 1: idempotent cleanup_all ──────────────────────────────────────

def test_cleanup_all_is_idempotent(engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.play(cid)
    assert cid in engine.active_channels()

    engine.cleanup_all()
    assert engine.active_channels() == []

    # Second call must be a no-op — engine has no channels left
    engine.cleanup_all()
    engine.cleanup_all()
    assert engine.active_channels() == []


# ── Test 2: per-channel error isolation ─────────────────────────────────

def test_cleanup_all_isolates_per_channel_errors(engine, test_song_path,
                                                 monkeypatch):
    """When one channel cleanup raises, the others still get cleaned up.

    Simulates a BASS-side failure by monkey-patching the engine's cleanup
    method to raise on a specific channel id. cleanup_all should catch
    the exception, log it, and continue with the remaining channels."""
    cid_a = engine.load_file(test_song_path)
    cid_b = engine.load_file(test_song_path)
    cid_c = engine.load_file(test_song_path)
    assert sorted(engine.active_channels()) == sorted([cid_a, cid_b, cid_c])

    # Monkey-patch cleanup to raise specifically on cid_b
    real_cleanup = engine.cleanup

    def buggy_cleanup(channel_id: int):
        if channel_id == cid_b:
            # Force-remove from map so the channel doesn't leak forever,
            # then raise — simulates a partial-failure state.
            engine._channels.pop(channel_id, None)
            raise RuntimeError("simulated BASS cleanup failure")
        return real_cleanup(channel_id)

    monkeypatch.setattr(engine, "cleanup", buggy_cleanup)

    # cleanup_all must NOT propagate the exception — it should log and
    # continue. After the call, ALL three channels must be gone.
    engine.cleanup_all()
    assert engine.active_channels() == [], \
        f"channels remained after cleanup_all: {engine.active_channels()}"


# ── Test 3: stale channel access raises ChannelError ───────────────────

def test_stale_channel_access_after_cleanup_raises(engine, test_song_path):
    """A channel id that was cleaned up cannot be reused. UI consumers
    holding stale ids should see ChannelError, not silent no-ops."""
    cid = engine.load_file(test_song_path)
    engine.cleanup_all()

    with pytest.raises(ChannelError):
        engine.play(cid)
    with pytest.raises(ChannelError):
        engine.pause(cid)
    with pytest.raises(ChannelError):
        engine.seek_to_ms(cid, 1000)


# ── Test 4: MainWindow exposes _cleanup_engine + aboutToQuit hook ──────

def test_main_window_cleanup_engine_method_exists():
    """Sanity check that the lifecycle wiring methods exist with the
    expected signatures. Not a runtime test — just a contract pin."""
    from ui.main_window import MainWindow
    # Methods exist
    assert callable(getattr(MainWindow, "closeEvent", None))
    assert callable(getattr(MainWindow, "_on_about_to_quit", None))
    assert callable(getattr(MainWindow, "_cleanup_engine", None))


# ── Test 5: engine survives cleanup_all (reusable, not single-shot) ────

def test_engine_survives_cleanup_all(engine, test_song_path):
    """cleanup_all should clear channels but leave the engine usable.
    A subsequent load_file should succeed and produce a fresh channel."""
    cid_first = engine.load_file(test_song_path)
    engine.play(cid_first)
    engine.cleanup_all()
    assert engine.active_channels() == []

    # Engine must still be usable
    cid_second = engine.load_file(test_song_path)
    assert cid_second > cid_first       # never-reused id contract holds
    assert engine.get_state(cid_second) == "loaded"

    engine.play(cid_second)
    assert engine.is_playing(cid_second)
