"""
Engine load + playback control (Phase A1 functionality, now under pytest).

Covers: load_file, play, pause, resume, stop, cleanup, channel id
non-reuse, ChannelError + AudioEngineError surfaces.

Cross-thread BASS sync callbacks are exercised indirectly via natural
EOS in test_engine_position.test_playback_ended_at_eof — A1 tests
focus on manual control paths only.
"""

import pytest

from core.audio import AudioEngine, AudioEngineError, ChannelError


def test_engine_construction_is_clean(engine):
    """Fresh engine has zero active channels (no side effects in __init__)."""
    assert engine.active_channels() == []


def test_load_file_returns_loaded_state(engine, test_song_path):
    cid = engine.load_file(test_song_path)
    assert cid > 0
    assert engine.get_state(cid) == "loaded"
    assert cid in engine.active_channels()


def test_play_transitions_to_playing(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.play(cid)
    assert engine.is_playing(cid)
    assert engine.get_state(cid) == "playing"
    qtbot.wait(200)   # let actual decode tick run


def test_pause_resume_cycle(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.play(cid)
    qtbot.wait(150)

    engine.pause(cid)
    assert engine.get_state(cid) == "paused"
    assert not engine.is_playing(cid)

    engine.resume(cid)
    assert engine.get_state(cid) == "playing"
    assert engine.is_playing(cid)


def test_stop_transitions_to_stopped(qtbot, engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.play(cid)
    qtbot.wait(150)
    engine.stop(cid)
    assert engine.get_state(cid) == "stopped"
    assert not engine.is_playing(cid)


def test_cleanup_removes_channel(engine, test_song_path):
    cid = engine.load_file(test_song_path)
    engine.cleanup(cid)
    assert cid not in engine.active_channels()


def test_never_reused_channel_ids(engine, test_song_path):
    """A cleaned-up channel id is never recycled — second load gets a
    strictly higher id, regardless of cleanup order."""
    cid1 = engine.load_file(test_song_path)
    engine.cleanup(cid1)
    cid2 = engine.load_file(test_song_path)
    assert cid2 > cid1


def test_unknown_channel_raises_channel_error(engine):
    with pytest.raises(ChannelError):
        engine.play(99_999)


def test_missing_file_raises_audio_engine_error(engine):
    with pytest.raises(AudioEngineError):
        engine.load_file(r"E:\does\not\exist.mp3")
