"""
No-overlap for non-music elements + stitcher tease top-up (2026-07-27).

BUG 1 — element overlap.
Operator: "Jingle > Sweeper > Song sequence mai jingle pura khatam nahi
hota sweepar chal jata hai... sweepar ko pura hone do phir song baje, no
overlap."

The fade threshold is ``duration - fade_out_start`` (8s default), sized
for 3-5 minute songs. On a 9-second sweeper it lands ~1s in, so the next
item was dispatched almost immediately and played over the top. Straight
from the on-air log:

    deck play ch=1 sweeper 'Sweepers_RR-Musical 01' dur_ms=9052
    fade-out triggered ch=1 trigger=fade_out_start=8s
    crossfade started - old_ch=1 new_ch=2

Non-music deck items now play to their natural EOS. Song-to-song keeps
the musical crossfade.

BUG 2 — stitcher tease dropped when its pin list ran low.
Each break consumes one pinned post-break song, but re-arming bailed out
while ANY pin remained, so the list drained 3 -> 2 -> 1 and at one pin
the montage could not meet ``min_hooks_required`` (2):

    tease armed - 3 songs pinned
    playing promised post-break song  (2 more pinned)
    playing promised post-break song  (1 more pinned)
    tease skipped - no valid sequence      <- one pin left
"""

from __future__ import annotations

import sys

import pytest

from core.database import Database
from ui.studio import Studio

_REAL_PATH = sys.executable


class _RecordingSignal:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *a, **k):
        for fn in list(self._slots):
            fn(*a, **k)


class _FakeScheduler:
    def __init__(self):
        self._items = []
        self._running = True
        for name in ("spot_due", "song_auto_advance", "break_approaching",
                     "next_break_in", "schedule_reloaded", "error_occurred",
                     "started", "stopped", "active_clock_changed"):
            setattr(self, name, _RecordingSignal())

    def is_running(self):
        return self._running

    def queue(self, *items):
        self._items.extend(items)

    def pick_next_item(self, _now=None):
        return self._items.pop(0) if self._items else None

    def peek_next(self, n=5, now=None):
        return list(self._items[:n])


class _FakeAudioEngine:
    def __init__(self):
        self.fades = []
        for name in ("position_changed", "playback_ended", "error_occurred",
                     "mix_point_reached", "fade_completed"):
            setattr(self, name, _RecordingSignal())

    def fade_volume_to(self, cid, target, ms):
        self.fades.append((int(cid), int(target), int(ms)))

    def set_volume(self, cid, vol):
        pass


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def studio(qapp, db):
    eng = _FakeAudioEngine()
    s = Studio(db, parent=None, engine=eng, scheduler=_FakeScheduler(),
               instant_jingle_engine=None, sweeper_engine=None)
    s._engine_fake = eng
    yield s
    s.deleteLater()


def _arm(studio, item_type: str, dur_ms: int = 9052, cid: int = 501):
    studio._playback_cid = cid
    studio._playback_kind = "deck"
    studio._current_duration_ms = dur_ms
    studio._current_track = {"id": 1, "duration_ms": dur_ms,
                             "_item_type": item_type}
    studio._fade_triggered_for_cid = None
    studio._fading_cid = None
    studio._pending_spots = []
    studio._pending_sotgs = []
    studio._engine_fake.fades.clear()


# -- The predicate -------------------------------------------------------


def test_non_music_types_are_recognised(studio):
    for t in ("jingle", "sweeper", "station_id", "voice_track", "voice",
              "break", "spot"):
        _arm(studio, t)
        assert studio._is_non_music_deck_item() is True, t


def test_song_is_music(studio):
    _arm(studio, "song")
    assert studio._is_non_music_deck_item() is False


def test_missing_item_type_defaults_to_music(studio):
    """A legacy track dict with no _item_type must keep the crossfade —
    absent information must not change broadcast behaviour."""
    _arm(studio, "song")
    studio._current_track = {"id": 1, "duration_ms": 200000}
    assert studio._is_non_music_deck_item() is False


def test_no_current_track_is_not_non_music(studio):
    studio._current_track = None
    assert studio._is_non_music_deck_item() is False


# -- Poll-fade backstop --------------------------------------------------


def test_poll_fade_skips_for_a_sweeper(studio):
    """The exact on-air case: 9,052 ms sweeper, 8 s fade window."""
    _arm(studio, "sweeper", dur_ms=9052)
    studio._cfg_fade_out_start_s = 8
    studio._maybe_trigger_fade_out(501, 1100)      # ~1s in - used to fade
    assert studio._engine_fake.fades == []
    assert studio._fade_triggered_for_cid == 501   # latched, won't re-eval


def test_poll_fade_skips_for_a_jingle(studio):
    _arm(studio, "jingle", dur_ms=18921)
    studio._cfg_fade_out_start_s = 8
    studio._maybe_trigger_fade_out(501, 11000)
    assert studio._engine_fake.fades == []


def test_poll_fade_still_fires_for_a_song(studio):
    """Music-to-music crossfade is the operator's segue feature — it
    must be untouched."""
    _arm(studio, "song", dur_ms=200000)
    studio._cfg_fade_out_start_s = 8
    studio._cfg_crossfade_dur_s = 8
    studio._maybe_trigger_fade_out(501, 195000)
    assert studio._engine_fake.fades, "song crossfade regressed"
    assert studio._engine_fake.fades[0][1] == 0    # fading to silence


# -- Mix-point sync ------------------------------------------------------


def test_mix_point_skips_for_non_music(studio):
    _arm(studio, "sweeper")
    studio._on_engine_mix_point_reached(501)
    assert studio._engine_fake.fades == []
    assert studio._fade_triggered_for_cid == 501


def test_mix_point_fires_for_a_song(studio):
    _arm(studio, "song", dur_ms=200000)
    studio._cfg_crossfade_dur_s = 8
    studio._on_engine_mix_point_reached(501)
    assert studio._engine_fake.fades


# -- Crossfade dispatch --------------------------------------------------


def test_crossfade_overlap_refuses_out_of_non_music(studio):
    _arm(studio, "jingle")
    assert studio._dispatch_crossfade_overlap() is False


def test_pending_dispatch_gate_still_applies(studio):
    """Invariant #2 must keep working alongside the new gate."""
    _arm(studio, "song", dur_ms=200000)
    studio._pending_spots = [1]
    studio._cfg_fade_out_start_s = 8
    studio._maybe_trigger_fade_out(501, 195000)
    assert studio._engine_fake.fades == []
    assert studio._dispatch_crossfade_overlap() is False


# -- Stitcher tease top-up -----------------------------------------------


def test_tease_arm_tops_up_a_drained_pin_list(studio, monkeypatch):
    """One pin left must not block re-arming — that is what made the
    montage skip with 'no valid sequence'."""
    studio._teased_songs = [{"id": 91, "title": "Leftover"}]
    studio._stitcher_tease_playing = False
    studio._stitcher_engine = object()
    monkeypatch.setattr(
        studio._db, "get_stitcher_config",
        lambda: {"module_enabled": 1, "trigger_before_every_break": 1})
    sched = studio._scheduler
    sched.queue(*[{"item_type": "song", "item_id": i, "title": f"S{i}",
                   "artist": "A", "file_path": _REAL_PATH,
                   "duration_ms": 180000} for i in (92, 93, 94)])

    studio._arm_stitcher_tease()

    ids = [s.get("id") for s in studio._teased_songs]
    assert len(studio._teased_songs) == Studio._TEASE_TARGET_PINS
    assert ids[0] == 91, "the already-promised song must keep its slot"
    assert len(set(ids)) == len(ids), "no duplicate pins"


def test_tease_arm_is_a_noop_when_already_full(studio, monkeypatch):
    full = [{"id": i, "title": f"P{i}"}
            for i in range(Studio._TEASE_TARGET_PINS)]
    studio._teased_songs = list(full)
    studio._stitcher_engine = object()
    called = []
    monkeypatch.setattr(
        studio._db, "get_stitcher_config",
        lambda: called.append(1) or {"module_enabled": 1,
                                     "trigger_before_every_break": 1})

    studio._arm_stitcher_tease()

    assert studio._teased_songs == full
    assert not called, "should bail out before even reading the config"


def test_tease_arm_skipped_while_a_tease_is_playing(studio, monkeypatch):
    studio._teased_songs = []
    studio._stitcher_tease_playing = True
    studio._stitcher_engine = object()
    called = []
    monkeypatch.setattr(
        studio._db, "get_stitcher_config",
        lambda: called.append(1) or {})
    studio._arm_stitcher_tease()
    assert not called
