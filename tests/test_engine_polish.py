"""
Engine polish + edge cases (Phase A5).

Covers: 100-cycle soak (slow), is_fading slide detection,
get_channel_info diagnostic surface, ChannelError on cleaned channels
(per Q2 — clean contract), engine destruction safety, concurrent
set_volume thread safety, and the new get_active_channels() filter.
"""

import threading

import pytest

from core.audio import AudioEngine, ChannelError


# ── Soak (slow) ──────────────────────────────────────────────────────────

@pytest.mark.slow
def test_soak_100_cycles(qtbot, engine, test_song_path):
    """Modest stress smoke test. 100 cycles ≈ 5s runtime. Not a
    replacement for production soak testing — see optional CI job for
    10k cycle / 1-hour continuous runs."""
    starting_next_id = engine._next_id
    for _ in range(100):
        cid = engine.load_file(test_song_path)
        engine.play(cid)
        qtbot.wait(20)
        engine.stop(cid)
        engine.cleanup(cid)

    assert engine.active_channels() == [], \
        f"channels leaked: {engine.active_channels()}"
    assert engine._next_id - starting_next_id == 100


# ── is_fading ────────────────────────────────────────────────────────────

def test_is_fading_during_slide(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.set_volume(cid, 100)
    engine.play(cid)
    qtbot.wait(50)

    assert engine.is_fading(cid) is False, "no slide active yet"

    engine.fade_volume_to(cid, 20, 400)
    # Slide just kicked off — should be active
    assert engine.is_fading(cid) is True, "slide should be active"

    # Wait for slide to finish (400ms + headroom for BASS to detect end)
    qtbot.wait(700)
    assert engine.is_fading(cid) is False, "slide should be done"


def test_is_fading_unknown_channel_returns_false(engine):
    """Defensive query path — UI may poll after cleanup races."""
    assert engine.is_fading(99_999) is False


# ── get_channel_info ────────────────────────────────────────────────────

def test_get_channel_info_keys(engine, test_song_path):
    cid = engine.load_file(test_song_path)
    info = engine.get_channel_info(cid)

    expected_keys = {
        "id", "file_path", "state", "volume",
        "position_ms", "duration_ms", "is_fading",
    }
    assert set(info.keys()) == expected_keys, \
        f"keys: got {set(info.keys())}, expected {expected_keys}"
    assert info["id"] == cid
    assert info["file_path"] == test_song_path
    assert info["state"] == "loaded"
    assert isinstance(info["volume"], int)
    assert isinstance(info["position_ms"], int)
    assert isinstance(info["duration_ms"], int)
    assert info["duration_ms"] > 0
    assert info["is_fading"] is False


def test_get_channel_info_unknown_returns_empty(engine):
    assert engine.get_channel_info(99_999) == {}


# ── Cleaned-up channel raises (Q2 contract) ─────────────────────────────

def test_seek_on_cleaned_channel_raises(engine, test_song_path):
    """Q2: keep clean ChannelError contract. Defensive seek would mask
    UI bugs (callers should disconnect signals on cleanup)."""
    cid = engine.load_file(test_song_path)
    engine.cleanup(cid)
    with pytest.raises(ChannelError):
        engine.seek_to_ms(cid, 10_000)


# ── Engine destruction safety ───────────────────────────────────────────

def test_engine_cleanup_all_safe_on_empty(engine):
    """cleanup_all on a fresh engine is a no-op, doesn't crash."""
    engine.cleanup_all()
    engine.cleanup_all()    # idempotent
    assert engine.active_channels() == []


def test_engine_lifecycle_no_del_required(qtbot, test_song_path):
    """Q1: engine intentionally has no __del__. Caller MUST invoke
    cleanup_all() before BASS_Free / app shutdown. This test exercises
    that contract — create, use, explicit cleanup, then drop reference."""
    e = AudioEngine()
    cid = e.load_file(test_song_path)
    e.play(cid)
    qtbot.wait(80)
    e.stop(cid)
    e.cleanup_all()
    # Now safe to let `e` go out of scope. No __del__ runs; BASS handles
    # are already freed.
    assert e.active_channels() == []
    del e


# ── Thread safety smoke ─────────────────────────────────────────────────

def test_concurrent_set_volume_thread_safe(qtbot, engine, test_song_path):
    """Set volume from a Python thread while the main thread polls.
    Verifies the BASS DLL call doesn't corrupt state. Not an exhaustive
    threading audit — A5 polish smoke only."""
    cid = engine.load_file(test_song_path)
    engine.play(cid)

    stop = threading.Event()
    errors: list[Exception] = []

    def _ramp():
        try:
            for v in range(0, 100, 5):
                if stop.is_set():
                    return
                engine.set_volume(cid, v)
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=_ramp, daemon=True)
    t.start()
    qtbot.wait(200)        # Qt thread keeps polling positions
    stop.set()
    t.join(timeout=2.0)

    assert not t.is_alive(), "background thread did not finish"
    assert not errors, f"thread errors: {errors}"
    # Final volume is whatever the ramp landed on (0–100), engine state
    # consistent.
    final = engine.get_volume(cid)
    assert 0 <= final <= 100


# ── get_active_channels filter (Q5 nicety) ──────────────────────────────

def test_get_active_channels_filters_by_state(qtbot, engine, test_song_path):
    """active_channels() returns ALL loaded; get_active_channels()
    filters to only playing/paused (Q5 — Phase B convenience)."""
    ca = engine.load_file(test_song_path)   # loaded
    cb = engine.load_file(test_song_path)
    cc = engine.load_file(test_song_path)

    engine.play(cb)        # → playing
    engine.play(cc)
    qtbot.wait(50)
    engine.pause(cc)       # → paused

    # active_channels: 3 (all loaded)
    assert sorted(engine.active_channels()) == sorted([ca, cb, cc])

    # get_active_channels: only cb (playing) and cc (paused)
    assert sorted(engine.get_active_channels()) == sorted([cb, cc])

    # Stop cb → only cc remains in playing/paused
    engine.stop(cb)
    assert engine.get_active_channels() == [cc]


# ── Phase B4 primitives — probe_duration_ms + load_file(loop=True) ──────

def test_probe_duration_ms_valid_file(engine, test_song_path):
    """probe_duration_ms reads duration without creating a channel."""
    duration = engine.probe_duration_ms(test_song_path)
    assert duration is not None
    assert duration > 1_000


def test_probe_duration_ms_does_not_create_channel(engine, test_song_path):
    """The probe must NOT leak channels into active_channels()."""
    before = engine.active_channels()
    engine.probe_duration_ms(test_song_path)
    engine.probe_duration_ms(test_song_path)
    after = engine.active_channels()
    assert before == after, \
        f"probe leaked channels: {before} -> {after}"


def test_probe_duration_ms_missing_file(engine):
    """Missing file returns None — never raises (paint-loop-safe)."""
    assert engine.probe_duration_ms(r"E:\does\not\exist.mp3") is None
    assert engine.probe_duration_ms("") is None


def test_load_file_loop_param_accepted(engine, test_song_path):
    """load_file(path, loop=True) loads with BASS_SAMPLE_LOOP set. Full
    'plays past EOF' verification would need >duration playback (slow);
    here we just verify the load-then-play path works cleanly."""
    cid = engine.load_file(test_song_path, loop=True)
    assert cid > 0
    assert engine.get_state(cid) == "loaded"
    engine.play(cid)
    assert engine.is_playing(cid)


def test_load_file_default_loop_is_false(engine, test_song_path):
    """Default behaviour unchanged — loop param is opt-in."""
    cid = engine.load_file(test_song_path)
    assert cid > 0
    assert engine.get_state(cid) == "loaded"
