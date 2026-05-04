"""
Engine multi-channel + eviction + fade_volume_to (Phase A3, pytest).

Covers: 8-channel concurrent loads, per-channel state isolation,
eviction policy + signal ordering, fade smoothness via BASS slide,
modest stress cycles, channel isolation on stop.

Test file uses test_long_song_path (>60s) for position-isolation coverage.
"""

import ctypes

import pytest

from core.audio import AudioEngine, ChannelError
from core.audio._bass import get_dll, BASS_ATTRIB_VOL


def _read_bass_volume(handle: int) -> float:
    """Read current BASS volume attribute (0.0–1.0). Used by fade-smoothness
    test to sample the in-flight slide value (the engine cache jumps to
    target immediately per Q4)."""
    out = ctypes.c_float(0.0)
    get_dll().BASS_ChannelGetAttribute(handle, BASS_ATTRIB_VOL, ctypes.byref(out))
    return float(out.value)


# ── Concurrent loads + per-channel isolation ────────────────────────────

def test_eight_concurrent_loads(engine, test_song_path):
    ids = [engine.load_file(test_song_path) for _ in range(8)]
    assert len(set(ids)) == 8, f"duplicate ids: {ids}"
    for cid in ids:
        assert engine.get_state(cid) == "loaded"
    assert sorted(engine.active_channels()) == sorted(ids)


def test_independent_volumes(engine, test_song_path):
    ca = engine.load_file(test_song_path)
    cb = engine.load_file(test_song_path)
    cc = engine.load_file(test_song_path)

    engine.set_volume(ca, 50)
    engine.set_volume(cb, 75)
    engine.set_volume(cc, 100)
    assert engine.get_volume(ca) == 50
    assert engine.get_volume(cb) == 75
    assert engine.get_volume(cc) == 100

    # Mutate one — others untouched
    engine.set_volume(ca, 30)
    assert engine.get_volume(ca) == 30
    assert engine.get_volume(cb) == 75
    assert engine.get_volume(cc) == 100


def test_independent_positions(engine, test_long_song_path):
    ca = engine.load_file(test_long_song_path)
    cb = engine.load_file(test_long_song_path)
    cc = engine.load_file(test_long_song_path)

    dur = engine.get_duration_ms(ca)
    assert dur > 60_000

    engine.seek_to_ms(ca, 10_000)
    engine.seek_to_ms(cb, 30_000)
    engine.seek_to_ms(cc, 60_000)

    assert abs(engine.get_position_ms(ca) - 10_000) < 700
    assert abs(engine.get_position_ms(cb) - 30_000) < 700
    assert abs(engine.get_position_ms(cc) - 60_000) < 700


# ── Eviction policy + signal ordering ────────────────────────────────────

def test_eviction_on_overflow(engine, test_song_path):
    ids = [engine.load_file(test_song_path) for _ in range(8)]
    oldest = ids[0]
    new_id = engine.load_file(test_song_path)   # 9th load → evicts oldest

    assert oldest not in engine.active_channels()
    assert new_id in engine.active_channels()
    assert len(engine.active_channels()) == 8


def test_eviction_signal_order(engine, test_song_path):
    state_log: list[tuple[int, str]] = []
    engine.channel_state_changed.connect(
        lambda c, s: state_log.append((c, s)))

    ids = [engine.load_file(test_song_path) for _ in range(8)]
    oldest = ids[0]
    state_log.clear()    # drop the noise of 8 'loaded' emits
    new_id = engine.load_file(test_song_path)

    stopped_idx = next(
        (i for i, (c, s) in enumerate(state_log)
         if c == oldest and s == "stopped"),
        None,
    )
    loaded_idx = next(
        (i for i, (c, s) in enumerate(state_log)
         if c == new_id and s == "loaded"),
        None,
    )
    assert stopped_idx is not None, f"no 'stopped' for evicted: {state_log}"
    assert loaded_idx is not None, f"no 'loaded' for new: {state_log}"
    # Q2 contract: stopped MUST precede loaded
    assert stopped_idx < loaded_idx, f"order wrong: {state_log}"


def test_evicted_channel_invalid(engine, test_song_path):
    ids = [engine.load_file(test_song_path) for _ in range(8)]
    oldest = ids[0]
    engine.load_file(test_song_path)   # evicts oldest
    with pytest.raises(ChannelError):
        engine.play(oldest)


# ── fade_volume_to ──────────────────────────────────────────────────────

def test_fade_smooth(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.set_volume(cid, 100)
    engine.play(cid)
    qtbot.wait(100)
    handle = engine._channels[cid].handle

    engine.fade_volume_to(cid, 20, 500)
    samples = [_read_bass_volume(handle)]
    qtbot.wait(100)
    samples.append(_read_bass_volume(handle))
    qtbot.wait(200)
    samples.append(_read_bass_volume(handle))
    qtbot.wait(200)
    samples.append(_read_bass_volume(handle))

    # Monotonic decrease (allow 0.01 noise)
    for prev, curr in zip(samples, samples[1:]):
        assert prev >= curr - 0.01, f"non-monotonic: {samples}"
    # End near target 0.20
    assert abs(samples[-1] - 0.20) < 0.10, \
        f"late {samples[-1]} not near 0.20"
    # Spread > 0.30 confirms motion (not instant)
    assert max(samples) - min(samples) > 0.30, \
        f"fade looks instant: spread={max(samples)-min(samples)}"


def test_fade_instant_when_zero_duration(engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.set_volume(cid, 100)
    engine.fade_volume_to(cid, 30, 0)   # duration=0 → instant
    assert engine.get_volume(cid) == 30
    handle = engine._channels[cid].handle
    assert abs(_read_bass_volume(handle) - 0.30) < 0.05


# ── Stress + isolation ──────────────────────────────────────────────────

def test_stress_20_cycles(qtbot, engine, test_song_path):
    """Modest stress smoke. See test_engine_polish.test_soak_100_cycles
    for the longer-running variant (marked `slow`)."""
    starting_next_id = engine._next_id
    for _ in range(20):
        cid = engine.load_file(test_song_path)
        engine.play(cid)
        qtbot.wait(40)
        engine.stop(cid)
        engine.cleanup(cid)
    assert engine.active_channels() == []
    assert engine._next_id - starting_next_id == 20


def test_stop_isolation(qtbot, engine, test_song_path):
    ca = engine.load_file(test_song_path)
    cb = engine.load_file(test_song_path)
    engine.play(ca)
    engine.play(cb)
    qtbot.wait(200)

    engine.stop(ca)
    assert not engine.is_playing(ca)
    assert engine.is_playing(cb)
    assert engine.get_state(ca) == "stopped"
    assert engine.get_state(cb) == "playing"
