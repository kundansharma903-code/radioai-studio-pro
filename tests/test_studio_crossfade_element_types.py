"""
Song → next-element transitions at the mix point (QA ⚠24, operator
decision 2026-10-18).

  • Jingles / station IDs / deck sweepers crossfade IN over the song's
    tail, like a song does. That has always been the on-air behaviour (the
    old `item_type != "song"` guard read a key real items never carry), and
    the operator wants to keep it. Pinned here: the element is picked ONCE,
    airs ONCE, is logged ONCE, and the outgoing song's EOS consumes nothing.
  • Ads from a clock Break slot never start over music: the fade is held,
    the song plays to its natural end, and the EOS path airs the spot,
    picked and logged exactly once.

Everything goes through the REAL Studio._compute_next_song /
_next_on_air_item path with scheduler items in the real pick_next_item
shape, unlike the old hand-built `{"item_type": "song"}` dicts.
"""

from __future__ import annotations

import pytest

from core.database import Database
from tests.test_studio_settings_integration import (
    _FakeEngine, _FakeScheduler)


class _Scheduler(_FakeScheduler):
    """pick_next_item consumes; peek_next does not (real contract)."""

    def __init__(self, items):
        super().__init__()
        self.items = list(items)
        self.picks = 0

    def is_running(self):
        return True

    def pick_next_item(self, *a, **k):
        self.picks += 1
        return dict(self.items.pop(0)) if self.items else None

    def peek_next(self, n=5, *a, **k):
        return [dict(i) for i in self.items[:int(n)]]


def _item(tmp_path, item_type, item_id, title, slot_idx, **extra):
    f = tmp_path / f"{item_type}_{item_id}.mp3"
    f.write_bytes(b"x")
    return {"item_type": item_type, "item_id": item_id, "title": title,
            "artist": item_type.upper(), "file_path": str(f),
            "duration_ms": 30_000, "clock_id": 4035, "slot_idx": slot_idx,
            **extra}


@pytest.fixture
def make_studio(qapp, monkeypatch):
    made = []

    def _make(items):
        from ui.studio import Studio
        eng, sch = _FakeEngine(), _Scheduler(items)
        s = Studio(Database(), engine=eng, scheduler=sch)
        logged: list = []
        monkeypatch.setattr(s._db, "log_play",
                            lambda **kw: logged.append(kw))
        monkeypatch.setattr(s, "_campaign_may_air", lambda *a, **k: True)
        s._playback_cid = 11
        s._playback_kind = "deck"
        s._current_duration_ms = 60_000
        s._cfg_fade_out_start_s = 5
        s._cfg_crossfade_dur_s = 3
        s._fade_triggered_for_cid = None
        s._current_track = {"id": 1, "title": "Song On Air",
                            "mix_point_ms": 0, "_item_type": "song"}
        made.append(s)
        return s, eng, sch, logged
    yield _make
    for s in made:
        s.deleteLater()


def _aired(logged, entry_type):
    return [k for k in logged if k.get("entry_type") == entry_type]


@pytest.mark.parametrize("element", ["jingle", "station_id", "sweeper"])
def test_element_crossfades_in_and_airs_exactly_once(make_studio, tmp_path,
                                                     element):
    extra = {"position": "Independent"} if element == "sweeper" else {}
    s, eng, sch, logged = make_studio(
        [_item(tmp_path, element, 7, f"{element} X", 2, **extra)])
    s._maybe_trigger_fade_out(11, 55_000)
    # Crossfade: the song fades while the element starts on a new channel.
    assert eng.fade_calls == [(11, 0, 3000)]
    assert len(getattr(eng, "loaded_paths", [])) == 1
    assert s._fading_cid == 11 and s._playback_cid == 101
    assert (s._current_track or {}).get("_item_type") == element
    assert sch.picks == 1                       # cursor advanced once
    assert len(_aired(logged, element)) == 1    # logged once
    # The outgoing song's EOS is the crossfade tail: nothing re-picked.
    s._on_engine_playback_ended(11)
    assert sch.picks == 1
    assert len(getattr(eng, "loaded_paths", [])) == 1
    assert len(_aired(logged, element)) == 1


def test_break_slot_spot_never_starts_over_music(make_studio, tmp_path):
    s, eng, sch, logged = make_studio(
        [_item(tmp_path, "spot", 19, "MG Mall", 3, campaign_id=19)])
    s._maybe_trigger_fade_out(11, 55_000)
    # Fade held, nothing consumed, nothing loaded: the song plays on.
    assert eng.fade_calls == []
    assert getattr(eng, "loaded_paths", []) == []
    assert sch.picks == 0
    assert s._fade_triggered_for_cid == 11      # latched, no re-eval
    # Natural EOS of the song → the spot airs, picked and logged once.
    s._on_engine_playback_ended(11)
    assert sch.picks == 1
    assert len(getattr(eng, "loaded_paths", [])) == 1
    assert (s._current_track or {}).get("_item_type") == "spot"
    spots = _aired(logged, "spot")
    assert len(spots) == 1
    assert spots[0].get("campaign_id") == 19
    assert (spots[0].get("clock_id"), spots[0].get("slot_idx")) == (4035, 3)


def test_mix_point_sync_also_holds_for_break_slot_spot(make_studio,
                                                       tmp_path):
    s, eng, sch, logged = make_studio(
        [_item(tmp_path, "spot", 19, "MG Mall", 3, campaign_id=19)])
    s._automix_mode = lambda: "mix_point"
    s._on_engine_mix_point_reached(11)
    assert eng.fade_calls == [] and sch.picks == 0
    assert s._fade_triggered_for_cid == 11


def test_song_to_song_crossfade_unchanged(make_studio, tmp_path):
    s, eng, sch, logged = make_studio(
        [_item(tmp_path, "song", 22, "Next Song", 1)])
    s._maybe_trigger_fade_out(11, 55_000)
    assert eng.fade_calls == [(11, 0, 3000)]
    assert sch.picks == 1 and s._playback_cid == 101
    assert len(_aired(logged, "song")) == 1
