"""
Up Coming AT times and the previewed clock follow the real air time
(QA ⚠27, seen live 2026-10-19).

  • 15:58 — the song had 3:29 left but the NEXT card's AT showed the
    current wall clock: the first card now starts at the on-air track's
    transition (mix point / fade start for a crossfading song, the end of
    the track for anything that plays out).
  • 15:59 — the preview showed the 15:00 clock's jingle while the 16:00
    clock aired: previews now peek at the projected air time, so they
    resolve the clock of the hour the next item actually airs in.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.database import Database
from tests.test_studio_settings_integration import (
    _FakeEngine, _FakeScheduler)


class _PeekRecorder(_FakeScheduler):
    def __init__(self):
        super().__init__()
        self.peek_nows: list = []

    def is_running(self):
        return True

    def peek_next(self, n=5, now=None):
        self.peek_nows.append(now)
        return [{"item_type": "song", "item_id": 22, "title": "Next",
                 "artist": "A", "file_path": "x.mp3", "duration_ms": 200_000,
                 "clock_id": 1, "slot_idx": 0}]


@pytest.fixture
def studio(qapp):
    from ui.studio import Studio
    sch = _PeekRecorder()
    s = Studio(Database(), engine=_FakeEngine(), scheduler=sch)
    s._playback_cid = 11
    s._playback_kind = "deck"
    s._current_duration_ms = 300_000          # 5:00 song
    s._cfg_fade_out_start_s = 8
    s._cfg_automix_trigger = "At song MIX POINT marker"
    s._current_track = {"id": 1, "title": "On Air", "_item_type": "song",
                        "mix_point_ms": 0}
    s._last_position_ms = 300_000 - 209_000   # 3:29 left
    yield s, sch
    s.deleteLater()


def test_crossfading_song_counts_to_its_fade_start(studio):
    s, _ = studio
    # fade_out_start 8 s → the next item starts 8 s before the end.
    assert s._ms_until_next_starts() == 209_000 - 8_000


def test_mix_point_wins_over_fade_out_start(studio):
    s, _ = studio
    s._current_track["mix_point_ms"] = 280_000
    assert s._ms_until_next_starts() == 280_000 - (300_000 - 209_000)


@pytest.mark.parametrize("setup", ["eos_mode", "jingle_on_deck", "spot",
                                   "pending_spot"])
def test_play_out_items_count_to_the_end(studio, setup):
    s, _ = studio
    if setup == "eos_mode":
        s._cfg_automix_trigger = "At end of song"
    elif setup == "jingle_on_deck":
        s._current_track["_item_type"] = "jingle"
    elif setup == "spot":
        s._playback_kind = "spot"
    else:
        s._pending_spots = [19]
    assert s._ms_until_next_starts() == 209_000


def test_idle_deck_is_now(studio):
    s, _ = studio
    s._playback_cid = None
    assert s._ms_until_next_starts() == 0


def test_first_card_at_is_the_projected_air_time(studio):
    s, _ = studio
    s._load_upcoming_queue()
    s._refresh_upcoming_panel()
    expect = datetime.now() + timedelta(milliseconds=209_000 - 8_000)
    at = s._upcoming._cards[0]._at_text
    got = datetime.combine(expect.date(),
                           datetime.strptime(at, "%H:%M:%S").time())
    assert abs((got - expect).total_seconds()) <= 2, at


def test_previews_peek_at_the_projected_air_time(studio):
    """Both the Up Coming load and the NEXT chip peek with now = the
    projected air time, so near :59 they resolve the next hour's clock."""
    s, sch = studio
    sch.peek_nows.clear()
    s._load_upcoming_queue()
    s._peek_next_for_display(after_id=None)
    expect = datetime.now() + timedelta(milliseconds=209_000 - 8_000)
    assert len(sch.peek_nows) >= 2
    for got in sch.peek_nows:
        assert got is not None and abs((got - expect).total_seconds()) <= 2


def test_preview_resolves_next_hours_clock_near_the_hour(qapp):
    """Engine-level proof of the 15:59 symptom: peeking at the projected
    16:00:30 air time resolves the 16:00 clock, not the 15:00 one."""
    from core.scheduler.engine import SchedulerEngine
    db = Database()
    day = (datetime.now() + timedelta(days=7)).replace(
        minute=0, second=0, microsecond=0)
    mk = lambda tag: int(db.create_clock(  # noqa: E731
        f"_test_airhour_{tag}_{datetime.now():%H%M%S%f}"))
    a, b = mk("a"), mk("b")
    for cid in (a, b):
        db.save_clock_slots(cid, [{"slot_type": "Song", "category_id": None,
                                   "energy_pref": "Any", "vocal_pref": "Any",
                                   "priority_pref": "Normal", "is_break": 0,
                                   "item_id": 0}])
    h15 = day.replace(hour=15)
    db.set_auto_schedule_cell(h15.weekday(), 15, a)
    db.set_auto_schedule_cell(h15.weekday(), 16, b)
    try:
        eng = SchedulerEngine(db=db)
        at_1559 = eng.peek_next(1, now=h15.replace(minute=59, second=40))
        at_1600 = eng.peek_next(1, now=h15.replace(hour=16, second=30))
        if not at_1559 or not at_1600:
            pytest.skip("no songs in the DB copy to feed the picker")
        assert at_1559[0]["clock_id"] == a
        assert at_1600[0]["clock_id"] == b
    finally:
        db.clear_auto_schedule_cell(h15.weekday(), 15)
        db.clear_auto_schedule_cell(h15.weekday(), 16)
        db.delete_clock(a)
        db.delete_clock(b)
