"""
Playback / on-air fixes (2026-10-17 audit).

  1  cue points read from the DB at load → mix point drives the sync,
     cue-in seeks the start
  2  SOTG: a deferred drop is queued ONCE, not marked MISSED while
     queued, and re-checked (status) before it airs
  3  spot / SOTG / break-policy release never start over the tease
  4  a stopped tease (drain / AUTO off) does not continue the chain
  5  StitcherEngine pre-builds the montage and skips on_done after stop
  6  fallback alert never blocks before the next / fallback track
  7  channel-cap eviction never evicts the protected deck channels
  8  automix trigger "At end of song" / "Manual only" / "At fade-out start"
  9  boot honours Settings → Soundcard audio_output_1
  10 deleted / disabled songs never air from manual / tease / fallback
  11 scheduler.error_occurred lands in the Problems panel
"""

from __future__ import annotations

import ast
import logging
import os
import threading
import time

import pytest
from PyQt6.QtCore import QCoreApplication

from core.database import Database


def _pump(n=4):
    for _ in range(n):
        QCoreApplication.processEvents()


class _Sig:
    def __init__(self):
        self._s = []

    def connect(self, f):
        self._s.append(f)

    def disconnect(self, *_):
        self._s.clear()

    def emit(self, *a):
        for f in list(self._s):
            f(*a)


class _Eng:
    """Recording fake AudioEngine."""

    def __init__(self, dur=30_000):
        self.calls: list[tuple] = []
        self._n = 0
        self.dur = dur
        self.position_changed = _Sig()
        self.playback_ended = _Sig()
        self.error_occurred = _Sig()

    def load_file(self, p, loop=False):
        self._n += 1
        self.calls.append(("load", p))
        return self._n

    def set_volume(self, *a): self.calls.append(("vol",) + a)
    def play(self, cid): self.calls.append(("play", cid))
    def cleanup(self, cid): self.calls.append(("cleanup", cid))
    def cleanup_all(self): pass
    def seek_to_ms(self, cid, ms): self.calls.append(("seek", cid, ms))
    def fade_volume_to(self, cid, v, ms): self.calls.append(("fade", cid, v))
    def get_duration_ms(self, *_): return self.dur
    def get_levels(self, *_): return (0.0, 0.0)
    def get_state(self, *_): return "playing"
    def get_position_ms(self, *_): return 0

    def set_position_sync(self, cid, ms):
        self.calls.append(("sync", cid, ms))
        return 99

    def loads(self):
        return [c[1] for c in self.calls if c[0] == "load"]


@pytest.fixture
def make_studio(qtbot, monkeypatch):
    import core.dialogs as D
    monkeypatch.setattr(D, "warning", lambda *a, **k: None)
    from ui.studio import Studio

    def make(eng=None):
        s = Studio(db=Database(), engine=eng or _Eng(), scheduler=None)
        qtbot.addWidget(s)
        monkeypatch.setattr(s, "_break_policy_enabled", lambda: False)
        monkeypatch.setattr(s._db, "log_play", lambda **k: None)
        if hasattr(s, "_campaign_may_air"):     # another fix's gate
            monkeypatch.setattr(s, "_campaign_may_air", lambda *a, **k: True)
        return s
    return make


@pytest.fixture
def audio(tmp_path):
    p = tmp_path / "a.mp3"
    p.write_bytes(b"\x00")
    return str(p)


def _fake_song_rows(monkeypatch, db, rows: dict):
    """db.get_song(id) → rows.get(id) (None = deleted)."""
    monkeypatch.setattr(db, "get_song", lambda sid: rows.get(int(sid)))


# ── 1. cue points ──────────────────────────────────────────────────────


def test_cue_points_read_from_db_at_load(make_studio, monkeypatch, audio):
    eng = _Eng(dur=200_000)
    s = make_studio(eng)
    _fake_song_rows(monkeypatch, s._db, {5: {
        "id": 5, "is_enabled": 1, "mix_point_ms": 180_000,
        "start_point_ms": 1_500}})
    s._cfg_automix_trigger = "At song MIX POINT marker"
    s._on_queue_song_play({"id": 5, "title": "S", "file_path": audio,
                           "_item_type": "song"})
    kinds = [c[0] for c in eng.calls]
    assert ("seek", 1, 1_500) in eng.calls
    assert kinds.index("seek") < kinds.index("play"), "cue-in before play"
    assert ("sync", 1, 180_000) in eng.calls, "per-song mix point armed"


def test_no_cue_data_keeps_global_fade_fallback(make_studio, monkeypatch,
                                                audio):
    eng = _Eng(dur=200_000)
    s = make_studio(eng)
    _fake_song_rows(monkeypatch, s._db, {5: {"id": 5, "is_enabled": 1,
                                              "mix_point_ms": 0,
                                              "start_point_ms": 0}})
    s._cfg_automix_trigger = ""
    s._cfg_fade_out_start_s = 8
    s._on_queue_song_play({"id": 5, "title": "S", "file_path": audio})
    assert not [c for c in eng.calls if c[0] == "seek"]
    assert ("sync", 1, 192_000) in eng.calls


# ── 8. automix trigger ─────────────────────────────────────────────────


def _deck(s, mp=0):
    s._playback_cid = 1
    s._playback_kind = "deck"
    s._current_duration_ms = 200_000
    s._current_track = {"id": 5, "title": "S", "_item_type": "song",
                        "mix_point_ms": mp}
    s._fade_triggered_for_cid = None
    s._pending_spots = []
    s._pending_sotgs = []
    s._cfg_fade_out_start_s = 8


@pytest.mark.parametrize("trigger", ["At end of song", "Manual only"])
def test_automix_no_early_crossfade(make_studio, trigger):
    eng = _Eng()
    s = make_studio(eng)
    _deck(s, mp=100_000)
    s._cfg_automix_trigger = trigger
    s._maybe_trigger_fade_out(1, 199_000)
    s._on_engine_mix_point_reached(1)
    assert not [c for c in eng.calls if c[0] == "fade"]
    s._register_mix_point_sync(1, s._current_track)
    assert not [c for c in eng.calls if c[0] == "sync"]


def test_automix_fade_out_start_ignores_mix_point(make_studio):
    eng = _Eng()
    s = make_studio(eng)
    _deck(s, mp=100_000)
    s._cfg_automix_trigger = "At fade-out start"
    s._dispatch_crossfade_overlap = lambda: False
    s._maybe_trigger_fade_out(1, 150_000)       # past mix point only
    assert not [c for c in eng.calls if c[0] == "fade"]
    s._maybe_trigger_fade_out(1, 193_000)       # past fade_out_start
    assert [c for c in eng.calls if c[0] == "fade"]


def test_automix_default_still_uses_mix_point(make_studio):
    eng = _Eng()
    s = make_studio(eng)
    _deck(s, mp=100_000)
    s._cfg_automix_trigger = "At song MIX POINT marker"
    s._dispatch_crossfade_overlap = lambda: False
    s._maybe_trigger_fade_out(1, 100_500)
    assert [c for c in eng.calls if c[0] == "fade"]


# ── 2. SOTG ────────────────────────────────────────────────────────────


def _sotg(audio, aid=321, prio="Low", sharp=None):
    from datetime import datetime, timedelta
    now = datetime.now() + timedelta(seconds=30)   # nearest minute → in window
    return {"assignment_id": aid, "file_path": audio,
            "sharp_time": sharp or f"{now.hour:02d}:{now.minute:02d}",
            "priority": prio, "status": "READY", "link_name": "L"}


def test_deferred_sotg_is_queued_once(make_studio, monkeypatch, audio):
    s = make_studio()
    a = _sotg(audio)
    monkeypatch.setattr(s._db, "get_sotg_assignments_for_date",
                        lambda d, status=None: [dict(a)])
    s._playback_kind = "deck"
    s._playback_cid = 9
    s._current_track = {"id": 1, "title": "Song"}
    for _ in range(4):
        s._sotg_check_tick()
    assert [p["assignment_id"] for p in s._pending_sotgs] == [321]


def test_queued_sotg_not_marked_missed(make_studio, monkeypatch, audio):
    from datetime import datetime, timedelta
    s = make_studio()
    old = (datetime.now() - timedelta(minutes=5)).strftime("%H:%M")
    a = _sotg(audio, sharp=old)
    s._pending_sotgs = [dict(a)]
    monkeypatch.setattr(s._db, "get_sotg_assignments_for_date",
                        lambda d, status=None: [dict(a)])
    missed = []
    monkeypatch.setattr(s._db, "mark_sotg_assignment_missed",
                        lambda aid: missed.append(aid))
    s._sotg_check_tick()
    assert missed == []


def test_sotg_already_fired_is_not_played_again(make_studio, monkeypatch,
                                                audio):
    eng = _Eng()
    s = make_studio(eng)
    monkeypatch.setattr(s._db, "get_sotg_assignment_by_id",
                        lambda aid: {"id": aid, "status": "FIRED"})
    monkeypatch.setattr(s, "_continue_break_chain", lambda a: None)
    s._play_sotg_file(_sotg(audio))
    assert eng.loads() == []


# ── 3. tease counts as busy ────────────────────────────────────────────


def test_spot_due_during_tease_is_queued(make_studio, monkeypatch, audio):
    eng = _Eng()
    s = make_studio(eng)
    monkeypatch.setattr(s._db, "get_spot_files",
                        lambda cid: [{"file_path": audio, "is_active": 1}])
    s._stitcher_tease_playing = True
    s._do_scheduler_spot_due(77, _policy_exempt=True)
    assert s._pending_spots == [77]
    assert eng.loads() == []


def test_sotg_due_during_tease_is_queued(make_studio, audio):
    eng = _Eng()
    s = make_studio(eng)
    s._stitcher_tease_playing = True
    s._do_sotg_fire(_sotg(audio, prio="High"))
    assert [p["assignment_id"] for p in s._pending_sotgs] == [321]
    assert eng.loads() == []


def test_break_policy_release_waits_for_tease(make_studio, monkeypatch):
    from datetime import datetime
    s = make_studio()
    fired = []
    monkeypatch.setattr(s, "_do_scheduler_spot_due",
                        lambda cid, _policy_exempt=False: fired.append(cid))
    monkeypatch.setattr(s, "_arm_stitcher_tease", lambda: None)
    s._stitcher_tease_playing = True
    s._break_pool = [{"campaign_id": 5, "category": "", "duration_ms": 1}]
    s._release_break_pool(datetime.now(), budget_check=False)
    assert fired == [] and s._pending_spots == [5]


# ── 4. stopped tease ───────────────────────────────────────────────────


def test_tease_done_after_drain_does_not_continue(make_studio, monkeypatch):
    s = make_studio()
    called = []
    monkeypatch.setattr(s, "_continue_break_chain",
                        lambda a: called.append(a))
    class _Sti:
        stops = 0
        def stop(self): self.stops += 1
    s._stitcher_engine = _Sti()
    s._stitcher_tease_playing = True
    s._pending_spots = [3]
    s._drain_pending_dispatches(reason="AUTO off")
    assert s._stitcher_engine.stops == 1
    s._on_stitcher_tease_done()          # late on_done from the engine
    assert called == []


def test_tease_done_with_auto_off_does_not_continue(make_studio,
                                                    monkeypatch):
    s = make_studio()
    called = []
    monkeypatch.setattr(s, "_continue_break_chain",
                        lambda a: called.append(a))
    s._stitcher_tease_playing = True
    s._auto_advance_enabled = False
    s._on_stitcher_tease_done()
    assert called == []
    s._stitcher_tease_playing = True
    s._auto_advance_enabled = True
    s._on_stitcher_tease_done()
    assert len(called) == 1


# ── 5. StitcherEngine ──────────────────────────────────────────────────


def test_stitcher_stop_skips_on_done(monkeypatch):
    from core.stitcher_engine import StitcherEngine
    eng = StitcherEngine()
    gate = threading.Event()

    def _slow(*a, **k):
        gate.wait(2)
    monkeypatch.setattr(eng, "_build_and_play", _slow)
    done = []
    eng.play_block([{"file_path": "x"}], on_done=lambda: done.append(1))
    eng.stop()
    gate.set()
    eng._thread.join(2)
    assert done == []
    # A normal (un-stopped) block still reports completion.
    eng.play_block([{"file_path": "x"}], on_done=lambda: done.append(2))
    eng._thread.join(2)
    assert done == [2]


def test_stitcher_prebuild_is_used_at_play(monkeypatch, tmp_path):
    from core.stitcher_engine import StitcherEngine
    eng = StitcherEngine()
    builds = []

    def _fake_build(seq, on_step):
        p = tmp_path / f"m{len(builds)}.wav"
        p.write_bytes(b"RIFF")
        builds.append(str(p))
        return str(p), 12.0
    played = []
    monkeypatch.setattr(eng, "_build_wav", _fake_build)
    monkeypatch.setattr(eng, "_play_wav",
                        lambda path, total, vol: played.append(path))
    seq = [{"file_path": "a.mp3", "seek_sec": 30.0},
           {"file_path": "b.mp3", "play_full": True}]
    eng.prebuild(seq)
    for _ in range(100):
        if eng._pre_path:
            break
        time.sleep(0.02)
    assert eng._pre_path == builds[0]
    eng.prebuild(seq)                    # idempotent
    time.sleep(0.05)
    assert len(builds) == 1
    eng.play_block(list(seq))
    eng._thread.join(2)
    assert played == [builds[0]], "cached montage played, no rebuild"
    assert len(builds) == 1
    assert not os.path.exists(builds[0]), "temp WAV cleaned after play"


def test_stitcher_changed_sequence_builds_inline(monkeypatch, tmp_path):
    from core.stitcher_engine import StitcherEngine
    eng = StitcherEngine()
    builds = []

    def _fake_build(seq, on_step):
        p = tmp_path / f"m{len(builds)}.wav"
        p.write_bytes(b"RIFF")
        builds.append(str(p))
        return str(p), 1.0
    monkeypatch.setattr(eng, "_build_wav", _fake_build)
    monkeypatch.setattr(eng, "_play_wav", lambda *a: None)
    eng._pre_key = eng._sequence_key([{"file_path": "old.mp3"}])
    eng._pre_path = None                 # still building / failed
    eng.play_block([{"file_path": "new.mp3"}])
    eng._thread.join(2)
    assert len(builds) == 1


def test_studio_prebuilds_when_tease_armed(make_studio, monkeypatch):
    s = make_studio()

    class _Sti:
        is_running = False
        def __init__(self): self.pre = []
        def prebuild(self, seq): self.pre.append(seq)
    sti = _Sti()
    s._stitcher_engine = sti
    monkeypatch.setattr(s, "_arm_stitcher_tease_pins", lambda: None)
    s._teased_songs = [{"id": 1}, {"id": 2}]
    monkeypatch.setattr(s._db, "get_stitcher_config",
                        lambda: {"module_enabled": 1})
    from core.stitcher_engine import StitcherEngine
    seq = [{"file_path": "x", "play_full": True}]
    monkeypatch.setattr(StitcherEngine, "assemble_sequence",
                        staticmethod(lambda c, songs: seq))
    s._arm_stitcher_tease()
    assert sti.pre == [seq]


# ── 6. fallback alert ──────────────────────────────────────────────────


@pytest.mark.parametrize("action", ["Play default fallback track",
                                    "Re-queue the same song"])
def test_fallback_alert_never_blocks_before_next_track(
        make_studio, monkeypatch, audio, action):
    import core.dialogs as D
    eng = _Eng()
    s = make_studio(eng)
    from core.settings import Settings
    real_get = Settings.get
    monkeypatch.setattr(
        Settings, "get",
        lambda self, k, d=None: "" if k == "default_fallback_path"
        else real_get(self, k, d))
    shown = []
    monkeypatch.setattr(D, "warning", lambda *a, **k: shown.append(a))
    s._cfg_fallback_action = action
    s._cfg_missing_file_alert = True
    s._auto_advance_enabled = True
    nxt = {"id": 0, "title": "Next", "file_path": audio}
    monkeypatch.setattr(s, "_compute_next_song", lambda after_id: nxt)
    monkeypatch.setattr(s, "_pop_next_teased_song", lambda: None)
    s._handle_missing_file({"id": 9, "title": "Broken"}, "/missing.mp3")
    assert shown == [], "no modal before the next track starts"
    _pump()
    assert eng.loads() == [audio], "next track airs (empty path = Skip)"
    assert shown, "alert still reaches the operator afterwards"
    assert any("Broken" in i for i in s._problems._items)


# ── 7. eviction ────────────────────────────────────────────────────────


def test_eviction_skips_protected_channels(engine, test_song_path):
    ids = [engine.load_file(test_song_path) for _ in range(8)]
    engine.set_eviction_protect_provider(lambda: [ids[0], ids[2]])
    new_id = engine.load_file(test_song_path)
    act = engine.active_channels()
    assert ids[0] in act and ids[2] in act, "deck channels kept"
    assert ids[1] not in act, "oldest UNPROTECTED evicted"
    assert new_id in act


def test_eviction_refuses_when_all_protected(engine, test_song_path):
    from core.audio import AudioEngineError
    ids = [engine.load_file(test_song_path) for _ in range(8)]
    engine.set_eviction_protect_provider(lambda: list(ids))
    with pytest.raises(AudioEngineError):
        engine.load_file(test_song_path)
    assert sorted(engine.active_channels()) == sorted(ids)


def test_studio_registers_deck_protection(make_studio):
    class _PEng(_Eng):
        provider = None
        def set_eviction_protect_provider(self, f):
            self.provider = f
    eng = _PEng()
    s = make_studio(eng)
    s._playback_cid, s._fading_cid = 4, 3
    assert sorted(eng.provider()) == [3, 4]


# ── 9. soundcard output at boot ────────────────────────────────────────


def _main_funcs(bass_init):
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name in ("configured_output_device",
                           "_bass_init_configured_device")]
    ns = {"bass_init": bass_init, "log": logging.getLogger("t")}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "main", "exec"), ns)
    return ns


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def test_boot_uses_configured_output_device():
    calls = []
    ns = _main_funcs(lambda device=-1, freq=44100:
                     calls.append(device) or True)
    assert ns["configured_output_device"](_S()) == -1
    assert ns["configured_output_device"](_S(audio_output_1="")) == -1
    assert ns["configured_output_device"](_S(audio_output_1="x")) == -1
    assert ns["_bass_init_configured_device"](_S(audio_output_1="3"))
    assert calls == [3]


def test_boot_falls_back_to_default_when_device_fails(caplog):
    calls = []
    ns = _main_funcs(lambda device=-1, freq=44100:
                     calls.append(device) or device == -1)
    with caplog.at_level(logging.ERROR):
        assert ns["_bass_init_configured_device"](_S(audio_output_1="4"))
    assert calls == [4, -1]
    assert any("FAILED" in r.message for r in caplog.records)


# ── 10. deleted / disabled songs ───────────────────────────────────────


def test_manual_queue_skips_disabled_and_deleted(make_studio, monkeypatch,
                                                 audio):
    s = make_studio()
    _fake_song_rows(monkeypatch, s._db, {
        1: {"id": 1, "is_enabled": 0}, 3: {"id": 3, "is_enabled": 1}})
    s._manual_queue = [
        {"id": 1, "title": "Disabled", "file_path": audio,
         "_item_type": "song"},
        {"id": 2, "title": "Deleted", "file_path": audio,
         "_item_type": "song"},
        {"id": 3, "title": "OK", "file_path": audio, "_item_type": "song"}]
    assert s._pop_next_manual()["id"] == 3


def test_tease_pin_skips_disabled(make_studio, monkeypatch, audio):
    s = make_studio()
    _fake_song_rows(monkeypatch, s._db, {
        1: {"id": 1, "is_enabled": 0}, 2: {"id": 2, "is_enabled": 1}})
    s._tease_waiting_for_break = False
    s._teased_songs = [{"id": 1, "file_path": audio},
                       {"id": 2, "file_path": audio}]
    assert s._pop_next_teased_song()["id"] == 2


def test_fallback_queue_skips_disabled(make_studio, monkeypatch, audio):
    s = make_studio()
    _fake_song_rows(monkeypatch, s._db, {
        1: {"id": 1, "is_enabled": 0}, 2: {"id": 2, "is_enabled": 1}})
    s._played_song_ids = set()
    s._queue_songs = [{"id": 1, "file_path": audio},
                      {"id": 2, "file_path": audio}]
    assert s._static_next_after(None)["id"] == 2


def test_fallback_queue_sql_filters_disabled(make_studio):
    s = make_studio()
    ids = [q["id"] for q in s._load_queue_from_db()]
    if not ids:
        pytest.skip("no playable songs in DB copy")
    marks = ",".join("?" * len(ids))
    disabled = s._db._conn().execute(
        f"SELECT COUNT(*) FROM songs WHERE id IN ({marks}) "
        f"AND is_enabled = 0", ids).fetchone()[0]
    assert disabled == 0


# ── 11. scheduler errors → Problems panel ──────────────────────────────


def test_scheduler_error_lands_in_problems_panel(make_studio):
    s = make_studio()
    s._on_scheduler_error("tick failed: boom")
    s._on_scheduler_error("tick failed: boom")     # de-duplicated
    items = [i for i in s._problems._items if "boom" in i]
    assert len(items) == 1


def test_studio_connects_scheduler_error_occurred():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "ui", "studio.py"),
        encoding="utf-8").read()
    assert "error_occurred.connect(\n                    self._on_scheduler_error)" in src \
        or "error_occurred.connect(self._on_scheduler_error)" in src
