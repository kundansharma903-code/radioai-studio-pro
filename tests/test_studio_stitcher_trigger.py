"""
Studio v3 ↔ Stitcher pre-break trigger wiring.

When the scheduler's ``break_approaching`` signal fires + the
operator has the Stitcher module enabled with ``trigger_before_every_break``,
Studio should assemble a hook sequence and route it through the
shared StitcherEngine. This file pins:

  • Disabled module → no fire.
  • Enabled but no audio paths / no hooks → no fire (assembler
    returns []).
  • Enabled + valid config → engine.play_block called with a
    sequence shape (opening + N hooks + separator-between + closing).
  • Refire guard — break_approaching can pulse multiple times for the
    same break, the engine fires only once within the guard window.
  • Engine already running → next pulse skips (no stacking).
  • Deck ducks via engine.fade_volume_to + restores via the on_done
    callback.
  • Fallback path — when fewer than min_hooks_required hooks are
    available, the assembled sequence is just [fallback].

Mocks: minimal `_FakeStitcherEngine` recording play_block + a
`_FakeAudioEngine` recording fade_volume_to. The DB layer is real
(tests snapshot + restore stitcher_config) so the wiring exercises
the end-to-end config path.
"""

from __future__ import annotations

import os

import pytest

from core.database import Database
from core.stitcher_engine import StitcherEngine


# ── Test doubles ────────────────────────────────────────────────────────


class _RecordingSignal:
    def __init__(self):
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class _FakeStitcher:
    def __init__(self):
        self.calls: list[dict] = []
        self._running = False

    def play_block(self, sequence, target_vol=85, on_step=None,
                   on_done=None):
        self.calls.append({
            "sequence":   list(sequence),
            "target_vol": int(target_vol),
            "on_done":    on_done,
        })
        self._running = True

    def stop(self):
        self._running = False

    @property
    def is_running(self):
        return self._running


class _FakeAudioEngine:
    def __init__(self):
        self.calls: list[tuple] = []
        # Studio's __init__ wires these on the real engine — provide
        # signal-shaped attrs so connect() doesn't AttributeError.
        self.position_changed = _RecordingSignal()
        self.playback_ended   = _RecordingSignal()
        self.error_occurred   = _RecordingSignal()

    def load_file(self, path, loop=False):
        self.calls.append(("load", path)); return 7

    def set_volume(self, cid, vol):
        self.calls.append(("vol", int(cid), int(vol)))

    def play(self, cid):
        self.calls.append(("play", int(cid)))

    def fade_volume_to(self, cid, target, ms):
        self.calls.append(("fade", int(cid), int(target), int(ms)))

    def cleanup(self, cid):
        self.calls.append(("cleanup", int(cid)))

    def cleanup_all(self):
        self.calls.append(("cleanup_all",))

    def get_levels(self, _cid): return (0.0, 0.0)
    def get_state(self, _cid):  return "playing"


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def cfg_snapshot(db):
    """Snapshot stitcher_config row before each test — restore after
    so the dev DB stays clean. Sets a known baseline (module_enabled=1
    + trigger_before_every_break=1) so assertions about the gate
    behaviour are deterministic."""
    before = db.get_stitcher_config()
    db.update_stitcher_config({
        "module_enabled": True,
        "trigger_before_every_break": True,
        "min_hooks_required": 2,
        "max_hooks": 4,
        "hook_duration_seconds": 8,
    })
    yield before
    restore = {k: v for k, v in before.items()
               if k in db.STITCHER_EDITABLE_FIELDS}
    if restore:
        db.update_stitcher_config(restore)


@pytest.fixture
def studio(qtbot, db):
    """Studio with FakeAudioEngine + FakeStitcher; no real scheduler.
    Tests drive the scheduler signal manually via _on_scheduler_break_warn."""
    from ui.studio import Studio
    eng = _FakeAudioEngine()
    sti = _FakeStitcher()
    s = Studio(db=db, engine=eng, scheduler=None,
               instant_jingle_engine=None, sweeper_engine=None,
               stitcher_engine=sti) if "stitcher_engine" in \
                  Studio.__init__.__code__.co_varnames \
               else Studio(db=db, engine=eng, scheduler=None)
    qtbot.addWidget(s)
    # Studio.__init__ doesn't currently take a stitcher_engine kwarg —
    # inject it directly the way MainWindow would in production.
    s._stitcher_engine = sti
    yield s, eng, sti


# ── Trigger gates ──────────────────────────────────────────────────────


def test_no_fire_when_module_disabled(qtbot, db, cfg_snapshot, studio):
    s, eng, sti = studio
    db.update_stitcher_config({"module_enabled": False})
    s._on_scheduler_break_warn(30)
    assert sti.calls == []


def test_no_fire_when_trigger_before_every_break_off(qtbot, db, cfg_snapshot, studio):
    s, eng, sti = studio
    db.update_stitcher_config({
        "module_enabled": True,
        "trigger_before_every_break": False,
    })
    s._on_scheduler_break_warn(30)
    assert sti.calls == []


def test_no_fire_when_assembled_sequence_is_empty(qtbot, db, cfg_snapshot, studio):
    """Audio paths empty + no hooks present → assembler returns [],
    Studio must NOT call play_block."""
    s, eng, sti = studio
    db.update_stitcher_config({
        "opening_audio":  "",
        "separator_audio": "",
        "closing_audio":  "",
        "fallback_audio": "",
    })
    s._on_scheduler_break_warn(30)
    assert sti.calls == []


def test_no_fire_when_engine_already_running(qtbot, db, cfg_snapshot, studio):
    s, eng, sti = studio
    sti._running = True
    s._on_scheduler_break_warn(30)
    assert sti.calls == []


def test_refire_guard_blocks_within_window(qtbot, db, cfg_snapshot, studio, monkeypatch):
    """break_approaching can pulse multiple times for the same break.
    The refire guard must clamp to one fire per window."""
    s, eng, sti = studio
    # Stub assemble_sequence + DB so the trigger reaches play_block.
    seq = [{"file_path": "/x.mp3", "play_full": True, "label": "FALLBACK"}]
    monkeypatch.setattr(StitcherEngine, "assemble_sequence",
                        staticmethod(lambda _cfg, _songs: seq))
    monkeypatch.setattr(s, "_collect_upcoming_songs_for_stitcher",
                        lambda count: [{"id": 1, "file_path": "/x.mp3"}])
    s._on_scheduler_break_warn(30)
    assert len(sti.calls) == 1
    s._on_scheduler_break_warn(28)   # second pulse within guard window
    assert len(sti.calls) == 1, \
        "Refire guard must keep the count at 1 within _STITCHER_REFIRE_GUARD_S"


# ── Happy path: assembled sequence + deck duck/restore ────────────────


def test_fire_routes_sequence_to_stitcher_engine(qtbot, db, cfg_snapshot, studio, monkeypatch):
    s, eng, sti = studio
    seq = [
        {"file_path": "/op.mp3", "play_full": True, "label": "OPENING"},
        {"file_path": "/h1.mp3", "seek_sec": 1.0,    "label": "Hook 1"},
        {"file_path": "/sep.mp3", "play_full": True, "label": "SEP"},
        {"file_path": "/h2.mp3", "seek_sec": 2.0,    "label": "Hook 2"},
        {"file_path": "/cl.mp3", "play_full": True, "label": "CLOSING"},
    ]
    monkeypatch.setattr(StitcherEngine, "assemble_sequence",
                        staticmethod(lambda _cfg, _songs: seq))
    monkeypatch.setattr(s, "_collect_upcoming_songs_for_stitcher",
                        lambda count: [{"id": 1, "file_path": "/h1.mp3"},
                                       {"id": 2, "file_path": "/h2.mp3"}])
    # Pretend the deck is active so the duck path runs.
    s._playback_cid = 99
    s._on_scheduler_break_warn(30)
    assert len(sti.calls) == 1
    payload = sti.calls[0]
    labels = [step.get("label") for step in payload["sequence"]]
    assert "OPENING" in labels
    assert "CLOSING" in labels
    assert labels.count("SEP") == 1
    assert payload["target_vol"] == 85


def test_fire_ducks_deck_then_restores_on_done(qtbot, db, cfg_snapshot, studio, monkeypatch):
    s, eng, sti = studio
    seq = [{"file_path": "/x.mp3", "play_full": True, "label": "FALLBACK"}]
    monkeypatch.setattr(StitcherEngine, "assemble_sequence",
                        staticmethod(lambda _cfg, _songs: seq))
    monkeypatch.setattr(s, "_collect_upcoming_songs_for_stitcher",
                        lambda count: [{"id": 1, "file_path": "/x.mp3"}])
    s._playback_cid = 99
    s._on_scheduler_break_warn(30)
    fades = [c for c in eng.calls if c[0] == "fade"]
    # First fade is the duck — target should be the duck volume.
    assert fades, "Expected a fade_volume_to call to duck the deck"
    assert fades[0][2] == s._STITCHER_DECK_DUCK_VOL
    # Fire the on_done callback the engine would normally invoke at end.
    on_done = sti.calls[0]["on_done"]
    assert on_done is not None
    on_done()
    fades = [c for c in eng.calls if c[0] == "fade"]
    # Second fade is the restore — target should be the master volume.
    assert len(fades) >= 2
    assert fades[1][2] == s.DEFAULT_VOLUME or fades[1][2] == \
           int(getattr(s, "_master_volume", s.DEFAULT_VOLUME))


def test_fire_skips_duck_when_deck_idle(qtbot, db, cfg_snapshot, studio, monkeypatch):
    s, eng, sti = studio
    seq = [{"file_path": "/x.mp3", "play_full": True, "label": "FALLBACK"}]
    monkeypatch.setattr(StitcherEngine, "assemble_sequence",
                        staticmethod(lambda _cfg, _songs: seq))
    monkeypatch.setattr(s, "_collect_upcoming_songs_for_stitcher",
                        lambda count: [{"id": 1, "file_path": "/x.mp3"}])
    s._playback_cid = None
    s._on_scheduler_break_warn(30)
    fades = [c for c in eng.calls if c[0] == "fade"]
    assert fades == [], \
        "No deck active → no duck call should fire"
    assert len(sti.calls) == 1, \
        "Stitcher must still fire even if the deck is idle"


# ── Sequence assembler unit tests ───────────────────────────────────────


def test_assemble_sequence_returns_empty_when_no_audio_paths(tmp_path):
    cfg = {"opening_audio": "", "separator_audio": "",
           "closing_audio": "", "fallback_audio": "",
           "min_hooks_required": 2, "max_hooks": 4}
    seq = StitcherEngine.assemble_sequence(cfg, [])
    assert seq == []


def test_assemble_sequence_uses_fallback_when_min_hooks_not_met(tmp_path):
    fb = tmp_path / "fallback.wav"; fb.write_bytes(b"\x00\x00")
    cfg = {"opening_audio": "", "separator_audio": "",
           "closing_audio": "", "fallback_audio": str(fb),
           "min_hooks_required": 2, "max_hooks": 4}
    seq = StitcherEngine.assemble_sequence(cfg, [])
    assert len(seq) == 1
    assert seq[0]["label"] == "FALLBACK"
    assert seq[0]["file_path"] == str(fb)


def test_assemble_sequence_inserts_separator_between_hooks(tmp_path):
    op = tmp_path / "open.wav"; op.write_bytes(b"\x00")
    sp = tmp_path / "sep.wav";  sp.write_bytes(b"\x00")
    cl = tmp_path / "close.wav"; cl.write_bytes(b"\x00")
    h1 = tmp_path / "h1.wav";   h1.write_bytes(b"\x00")
    h2 = tmp_path / "h2.wav";   h2.write_bytes(b"\x00")
    h3 = tmp_path / "h3.wav";   h3.write_bytes(b"\x00")
    cfg = {"opening_audio": str(op), "separator_audio": str(sp),
           "closing_audio": str(cl), "fallback_audio": "",
           "min_hooks_required": 2, "max_hooks": 4}
    songs = [
        {"id": 1, "file_path": str(h1),
         "hook_in_ms": 1000, "hook_out_ms": 9000, "title": "T1"},
        {"id": 2, "file_path": str(h2),
         "hook_in_ms": 2000, "hook_out_ms": 10000, "title": "T2"},
        {"id": 3, "file_path": str(h3),
         "hook_in_ms": 3000, "hook_out_ms": 11000, "title": "T3"},
    ]
    seq = StitcherEngine.assemble_sequence(cfg, songs)
    labels = [s.get("label") for s in seq]
    assert labels[0] == "OPENING"
    assert labels[-1] == "CLOSING"
    # 3 hooks → 2 separators between them
    assert labels.count("SEP") == 2


def test_assemble_sequence_caps_at_max_hooks(tmp_path):
    op = tmp_path / "op.wav"; op.write_bytes(b"\x00")
    cl = tmp_path / "cl.wav"; cl.write_bytes(b"\x00")
    cfg = {"opening_audio": str(op), "separator_audio": "",
           "closing_audio": str(cl), "fallback_audio": "",
           "min_hooks_required": 1, "max_hooks": 2}
    songs = []
    for i in range(5):
        f = tmp_path / f"h{i}.wav"; f.write_bytes(b"\x00")
        songs.append({
            "id": i, "file_path": str(f),
            "hook_in_ms": 1000, "hook_out_ms": 9000,
            "title": f"T{i}",
        })
    seq = StitcherEngine.assemble_sequence(cfg, songs)
    # Filter to non-OPENING / non-CLOSING / non-SEP entries — those
    # are the hooks. Should be exactly max_hooks (=2).
    hooks = [s for s in seq if s.get("label") not in
             ("OPENING", "CLOSING", "SEP", "FALLBACK")]
    assert len(hooks) == 2
