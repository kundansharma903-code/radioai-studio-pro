"""
Studio v3 ↔ Stitcher BREAK-TEASE wiring (2026-07-02 sequenced model).

Industry model (RadioBOSS teasers / StationPlaylist hooks): the
"Coming Up Next" montage is its OWN sequenced element built from the
songs that will ACTUALLY air after the break:

    song (natural EOS) → tease block (standalone, deck silent)
    → spot chain → the teased songs, in pinned order

This file pins:
  • Arm gates — module disabled / trigger off → no tease pinned.
  • _arm_stitcher_tease pins up to 3 SONG cards from the visible
    Up Coming preview (spot/SOTG cards skipped), hydrated from DB.
  • _maybe_play_tease_first plays the block standalone (NO deck duck),
    marks tease-playing, and respects the refire guard + running guard.
  • Assembler-empty → tease skipped, returns False (spot fires direct).
  • Tease-done continuation fires the pending spot chain.
  • _pop_next_teased_song returns pinned songs in order, skipping
    missing files.
  • _drain_pending_dispatches clears the tease pin.
  • Up Coming preview keeps SONG cards visible when a spot is pending
    and the scheduler peek is empty (the "queue tray empties" bug).
  • Sequence assembler unit behaviours (shape / fallback / caps).
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
        self.stops = 0
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
        self.stops += 1
        self._running = False

    @property
    def is_running(self):
        return self._running


class _FakeAudioEngine:
    def __init__(self):
        self.calls: list[tuple] = []
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
    """Baseline stitcher_config (enabled + before-every-break) with
    restore-after so the (shielded copy) DB stays deterministic."""
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
    from ui.studio import Studio
    eng = _FakeAudioEngine()
    sti = _FakeStitcher()
    s = Studio(db=db, engine=eng, scheduler=None,
               instant_jingle_engine=None, sweeper_engine=None,
               stitcher_engine=sti)
    qtbot.addWidget(s)
    yield s, eng, sti


def _real_song_cards(db, n=3) -> list[dict]:
    """n real (shield-copy) songs with hooks + on-disk files, shaped
    like Up-Coming preview cards."""
    rows = db._conn().execute(
        "SELECT id, title, artist, file_path, duration_ms FROM songs "
        "WHERE is_enabled = 1 AND hook_in_ms > 0 AND file_path != '' "
        "ORDER BY id LIMIT 40").fetchall()
    cards = []
    for r in rows:
        if r["file_path"] and os.path.exists(r["file_path"]):
            cards.append({
                "_item_type": "song", "id": int(r["id"]),
                "title": r["title"], "artist": r["artist"],
                "file_path": r["file_path"],
                "duration_ms": int(r["duration_ms"] or 0),
            })
        if len(cards) >= n:
            break
    if len(cards) < n:
        pytest.skip("shield DB lacks hooked on-disk songs")
    return cards


# ── Arm gates ──────────────────────────────────────────────────────────


def test_no_arm_when_module_disabled(qtbot, db, cfg_snapshot, studio):
    s, eng, sti = studio
    db.update_stitcher_config({"module_enabled": False})
    s._upcoming_preview = _real_song_cards(db)
    s._on_scheduler_break_warn(30)
    assert s._teased_songs == []


def test_no_arm_when_trigger_before_every_break_off(qtbot, db, cfg_snapshot, studio):
    s, eng, sti = studio
    db.update_stitcher_config({
        "module_enabled": True,
        "trigger_before_every_break": False,
    })
    s._upcoming_preview = _real_song_cards(db)
    s._on_scheduler_break_warn(30)
    assert s._teased_songs == []


def test_arm_pins_visible_preview_songs_in_order(qtbot, db, cfg_snapshot, studio):
    """Arm must pin the SONG cards the operator sees (spot/SOTG cards
    skipped), hydrated with hook cue points, order preserved."""
    s, eng, sti = studio
    cards = _real_song_cards(db)
    s._upcoming_preview = (
        [{"_item_type": "spot", "id": 999, "title": "AD"}] + cards)
    s._on_scheduler_break_warn(30)
    assert [t["id"] for t in s._teased_songs] == [c["id"] for c in cards]
    assert all("hook_in_ms" in t for t in s._teased_songs)


def test_arm_is_idempotent_while_armed(qtbot, db, cfg_snapshot, studio):
    s, eng, sti = studio
    cards = _real_song_cards(db)
    s._upcoming_preview = cards
    s._on_scheduler_break_warn(30)
    first = [t["id"] for t in s._teased_songs]
    s._upcoming_preview = list(reversed(cards))
    s._on_scheduler_break_warn(25)      # re-pulse — must not re-pin
    assert [t["id"] for t in s._teased_songs] == first


# ── Tease playback (standalone, before the spot chain) ─────────────────


def _arm(s, db):
    s._upcoming_preview = _real_song_cards(db)
    s._arm_stitcher_tease()
    assert s._teased_songs, "arm precondition failed"


def test_tease_plays_standalone_no_duck(qtbot, db, cfg_snapshot, studio, monkeypatch):
    """EOS-time tease: block routed to the stitcher engine with NO
    deck duck (the deck is silent at EOS — sequenced element model)."""
    s, eng, sti = studio
    _arm(s, db)
    seq = [{"file_path": "/x.mp3", "play_full": True, "label": "FALLBACK"}]
    monkeypatch.setattr(StitcherEngine, "assemble_sequence",
                        staticmethod(lambda _cfg, _songs: seq))
    s._pending_spots.append(4242)
    assert s._maybe_play_tease_first(anchor_id=11) is True
    assert len(sti.calls) == 1
    assert s._stitcher_tease_playing is True
    fades = [c for c in eng.calls if c[0] == "fade"]
    assert fades == [], "sequenced tease must NOT duck the deck"


def test_tease_skipped_when_assembler_empty(qtbot, db, cfg_snapshot, studio, monkeypatch):
    s, eng, sti = studio
    _arm(s, db)
    monkeypatch.setattr(StitcherEngine, "assemble_sequence",
                        staticmethod(lambda _cfg, _songs: []))
    assert s._maybe_play_tease_first(anchor_id=11) is False
    assert sti.calls == []


def test_tease_skipped_when_engine_running(qtbot, db, cfg_snapshot, studio):
    s, eng, sti = studio
    _arm(s, db)
    sti._running = True
    assert s._maybe_play_tease_first(anchor_id=11) is False


def test_refire_guard_blocks_second_tease(qtbot, db, cfg_snapshot, studio, monkeypatch):
    s, eng, sti = studio
    _arm(s, db)
    seq = [{"file_path": "/x.mp3", "play_full": True, "label": "FALLBACK"}]
    monkeypatch.setattr(StitcherEngine, "assemble_sequence",
                        staticmethod(lambda _cfg, _songs: seq))
    assert s._maybe_play_tease_first(anchor_id=11) is True
    # complete the first block + re-arm
    sti._running = False
    s._stitcher_tease_playing = False
    _arm(s, db)
    assert s._maybe_play_tease_first(anchor_id=12) is False, \
        "second tease within _STITCHER_REFIRE_GUARD_S must be blocked"
    assert len(sti.calls) == 1


def test_tease_done_fires_pending_spot_chain(qtbot, db, cfg_snapshot, studio, monkeypatch):
    """on_done → _stitcher_tease_done signal → the pending spot pops
    and fires with the resume anchor preserved."""
    s, eng, sti = studio
    _arm(s, db)
    seq = [{"file_path": "/x.mp3", "play_full": True, "label": "FALLBACK"}]
    monkeypatch.setattr(StitcherEngine, "assemble_sequence",
                        staticmethod(lambda _cfg, _songs: seq))
    fired: list[int] = []
    monkeypatch.setattr(s, "_do_scheduler_spot_due",
                        lambda cid: fired.append(int(cid)))
    s._pending_spots.append(4242)
    assert s._maybe_play_tease_first(anchor_id=11) is True
    sti._running = False
    sti.calls[0]["on_done"]()          # engine's completion callback
    assert fired == [4242]
    assert s._stitcher_tease_playing is False
    assert s._pre_spot_song_id == 11


# ── Pinned post-break songs ────────────────────────────────────────────


def test_pop_next_teased_song_order_and_missing_file_skip(qtbot, db, cfg_snapshot, studio, tmp_path):
    s, eng, sti = studio
    ok1 = tmp_path / "a.mp3"; ok1.write_bytes(b"\x00")
    ok2 = tmp_path / "b.mp3"; ok2.write_bytes(b"\x00")
    s._teased_songs = [
        {"id": 1, "title": "A", "file_path": str(ok1)},
        {"id": 2, "title": "GONE", "file_path": r"Z:\missing.mp3"},
        {"id": 3, "title": "B", "file_path": str(ok2)},
    ]
    assert s._pop_next_teased_song()["id"] == 1
    assert s._pop_next_teased_song()["id"] == 3    # missing skipped
    assert s._pop_next_teased_song() is None


def test_drain_clears_tease_pin(qtbot, db, cfg_snapshot, studio):
    s, eng, sti = studio
    _arm(s, db)
    s._pending_spots.append(4242)
    s._drain_pending_dispatches(reason="test")
    assert s._teased_songs == []
    assert s._pending_spots == []


# ── Queue display — the "tray empties on spot" bug ─────────────────────


def test_preview_keeps_songs_when_spot_pending_and_peek_empty(qtbot, db, cfg_snapshot, studio, monkeypatch, tmp_path):
    """BUG (operator 2026-07-02): a pending spot with an empty
    scheduler peek used to leave the preview with ONLY the spot card —
    the songs tray 'emptied'. Song cards must always be present."""
    s, eng, sti = studio
    f = tmp_path / "q.mp3"; f.write_bytes(b"\x00")
    s._queue_songs = [
        {"id": 71, "title": "QA", "artist": "x",
         "file_path": str(f), "duration_ms": 1000},
        {"id": 72, "title": "QB", "artist": "x",
         "file_path": str(f), "duration_ms": 1000},
    ]
    monkeypatch.setattr(
        s, "_pending_spot_to_card",
        lambda cid: {"_item_type": "spot", "id": cid, "title": "AD"})
    s._pending_spots.append(555)
    s._load_upcoming_queue()
    types = [(c.get("_item_type") or "song")
             for c in s._upcoming_preview]
    assert "spot" in types, "pending spot must appear in the preview"
    assert "song" in types, \
        "song cards must survive a pending spot (tray must not empty)"
    assert types.index("spot") < types.index("song"), \
        "spot shows on top, songs below"


# ── Sequence assembler unit tests (unchanged behaviour) ────────────────


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
    hooks = [s for s in seq if s.get("label") not in
             ("OPENING", "CLOSING", "SEP", "FALLBACK")]
    assert len(hooks) == 2
