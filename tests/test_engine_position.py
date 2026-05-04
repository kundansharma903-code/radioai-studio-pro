"""
Engine position tracking + volume + seek (Phase A2 functionality, pytest).

Covers: shared poll timer driving position_changed, seek_to_ms with
immediate feedback, set_volume silent clamp, get_duration / get_position,
state transitions, EOS via seek-near-end trick (Q2), stop position reset.
"""

import pytest

from core.audio import AudioEngine


# ── Position emission ────────────────────────────────────────────────────

def test_position_emits_during_playback(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    pos_log: list[tuple[int, int]] = []
    engine.position_changed.connect(lambda c, p: pos_log.append((c, p)))
    engine.play(cid)
    qtbot.wait(600)
    assert len(pos_log) >= 3, f"expected ≥3 events, got {len(pos_log)}"


def test_position_silent_during_pause(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    pos_log: list[int] = []
    engine.position_changed.connect(lambda c, p: pos_log.append(p))
    engine.play(cid)
    qtbot.wait(400)
    engine.pause(cid)
    pos_log.clear()
    qtbot.wait(500)
    assert len(pos_log) == 0, f"position emitted during pause: {len(pos_log)}"


# ── Seek ─────────────────────────────────────────────────────────────────

def test_seek_moves_position(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.play(cid)
    qtbot.wait(200)
    engine.seek_to_ms(cid, 30_000)
    qtbot.wait(150)
    pos = engine.get_position_ms(cid)
    assert abs(pos - 30_000) < 600, f"seek landed at {pos}, expected ~30000"


def test_seek_emits_immediate_position_changed(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.play(cid)
    qtbot.wait(150)

    pos_log: list[tuple[int, int]] = []
    engine.position_changed.connect(lambda c, p: pos_log.append((c, p)))
    pos_log.clear()
    engine.seek_to_ms(cid, 45_000)
    # No qtbot.wait — emission is synchronous (same thread)
    assert any(abs(p - 45_000) < 600 for _, p in pos_log), \
        f"no immediate position_changed near 45000ms; log={pos_log}"


# ── Volume ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("input_vol,expected", [
    (-5, 0), (0, 0), (50, 50), (100, 100), (150, 100),
])
def test_set_volume_clamps(engine, test_song_path, input_vol, expected):
    cid = engine.load_file(test_song_path)
    engine.set_volume(cid, input_vol)
    assert engine.get_volume(cid) == expected


# ── Duration ─────────────────────────────────────────────────────────────

def test_get_duration_matches_db(engine, test_song_with_db_dur):
    path, db_duration = test_song_with_db_dur
    cid = engine.load_file(path)
    bass_dur = engine.get_duration_ms(cid)
    assert bass_dur > 1000, f"bass duration too short: {bass_dur}ms"
    # 2s tolerance — DB sometimes stores ID3-tag-rounded values
    assert abs(bass_dur - db_duration) < 2000, \
        f"duration mismatch: DB={db_duration} BASS={bass_dur}"


# ── EOS detection ────────────────────────────────────────────────────────

def test_playback_ended_at_eof(qtbot, engine, test_song_path):
    """Seek-near-end trick (Q2) — avoids needing a short-clip fixture."""
    cid = engine.load_file(test_song_path)
    dur = engine.get_duration_ms(cid)
    assert dur > 2000

    with qtbot.waitSignal(engine.playback_ended, timeout=4_000) as blocker:
        engine.seek_to_ms(cid, dur - 1500)
        engine.play(cid)
    assert blocker.signal_triggered, "playback_ended did not fire"
    assert engine.get_state(cid) == "ended"
    final_pos = engine.get_position_ms(cid)
    # Position stays at duration on natural EOS (vs reset to 0 on stop())
    assert final_pos > dur - 500, \
        f"position {final_pos} not near end (dur={dur})"


# ── State machine + stop semantics ──────────────────────────────────────

def test_state_transitions(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    states: list[str] = []
    engine.channel_state_changed.connect(
        lambda c, s: states.append(s) if c == cid else None)

    engine.play(cid)
    qtbot.wait(150)
    engine.pause(cid)
    qtbot.wait(80)
    engine.resume(cid)
    qtbot.wait(150)
    engine.stop(cid)

    assert states == ["playing", "paused", "playing", "stopped"], \
        f"unexpected log: {states}"


def test_stop_resets_position_to_zero(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.play(cid)
    qtbot.wait(500)
    pos_during = engine.get_position_ms(cid)
    engine.stop(cid)
    pos_after = engine.get_position_ms(cid)
    assert pos_during > 100, f"pre-stop pos too low: {pos_during}"
    assert pos_after < 200, f"post-stop pos {pos_after} not reset"


# ── Multi-channel preview (real test in test_engine_multi) ──────────────

def test_two_channels_emit_independently(qtbot, engine, test_song_path):
    cid_a = engine.load_file(test_song_path)
    cid_b = engine.load_file(test_song_path)
    counts = {cid_a: 0, cid_b: 0}
    engine.position_changed.connect(
        lambda c, _p: counts.update({c: counts.get(c, 0) + 1})
        if c in counts else None)
    engine.play(cid_a)
    engine.play(cid_b)
    qtbot.wait(600)
    assert counts[cid_a] >= 2, f"ch A events: {counts[cid_a]}"
    assert counts[cid_b] >= 2, f"ch B events: {counts[cid_b]}"
