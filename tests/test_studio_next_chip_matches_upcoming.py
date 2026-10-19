"""
Studio NEXT chip ↔ Up Coming NEXT card — one source of truth (QA ⚠14).

Operator-style test 2026-10-18 08:40: the master-strip NEXT chip said
"Jingle _Trending" while the first Up Coming card — also labelled NEXT —
said "Mere Sapno ki Rani". A spot was held for the 08:45 break window and
the break tease had pinned three post-break songs. The pinned songs only
air AFTER their break (_pop_next_teased_song returns None while
_tease_waiting_for_break), so the jingle really aired next: the chip was
right and the card was wrong.

Contract pinned here: the item on the NEXT chip, the Up Coming card that
carries the NEXT glow, and what the song-EOS chain would really air are
the SAME item — in every state the EOS chain distinguishes:
  • tease waiting for its break  → scheduler item (jingle) is next
  • break on air (tease released) → pinned song is next
  • pending spot                 → spot is next
  • pending SOTG                 → SOTG is next (SOTG > spot)
  • T-60s preview spot (not due) → shown, but NOT glowing as NEXT
None of this may advance the scheduler cursor.
"""

from __future__ import annotations

import sys

import pytest

from core.database import Database
from ui.studio import Studio

_REAL_PATH = sys.executable     # exists on disk; engine=None never decodes


@pytest.fixture(autouse=True)
def _no_live_spot_schedule(monkeypatch):
    """Keep the live spot/SOTG schedule out (same isolation as the
    Up Coming tests — QA ⚠9)."""
    def _no_preview(self, *, now=None):
        self._upcoming_preview_spots = []
        self._upcoming_preview_sotgs = []
        return False
    monkeypatch.setattr(Studio, "_check_upcoming_dispatches", _no_preview)
    monkeypatch.setattr(Studio, "_sotg_check_tick", lambda self: None)


class _Sig:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *a, **k):
        for fn in list(self._slots):
            fn(*a, **k)


class _Scheduler:
    """pick_next_item advances a cursor; peek_next never does."""

    def __init__(self, items):
        self._items = list(items)
        self.cursor = 0
        for name in ("spot_due", "song_auto_advance", "break_approaching",
                     "next_break_in", "schedule_reloaded", "error_occurred",
                     "started", "stopped", "active_clock_changed",
                     "queue_changed"):
            setattr(self, name, _Sig())

    def is_running(self):
        return True

    def start(self):
        pass

    def stop(self):
        pass

    def pick_next_item(self, _now=None):
        if self.cursor >= len(self._items):
            return None
        item = self._items[self.cursor]
        self.cursor += 1
        return item

    def peek_next(self, n=5, now=None):
        return list(self._items[self.cursor:self.cursor + int(n)])


def _item(item_type, item_id, title):
    return {"item_type": item_type, "item_id": int(item_id),
            "title": title, "artist": item_type.upper(),
            "file_path": _REAL_PATH, "duration_ms": 30_000,
            "clock_id": 1, "slot_idx": item_id}


def _real_song_ids(n):
    """Enabled songs from the session DB copy — pinned songs must pass
    the same 'still in the library' check dispatch applies."""
    rows = Database()._conn().execute(
        "SELECT id FROM songs WHERE is_enabled = 1 ORDER BY id LIMIT ?",
        [int(n)]).fetchall()
    if len(rows) < n:
        pytest.skip(f"need {n} enabled songs in the DB copy")
    return [int(r[0]) for r in rows]


def _teased(song_id, title):
    # Title is the test's own label; the file is a real path on disk.
    return {"id": int(song_id), "title": title, "artist": "Pinned",
            "file_path": _REAL_PATH, "duration_ms": 200_000}


_DELETED_SONG_ID = 2_000_000_000     # no such row in songs


@pytest.fixture
def studio(qapp):
    sched = _Scheduler([_item("jingle", 7, "Jingle _Trending"),
                        _item("song", 22, "Next Scheduler Song")])
    s = Studio(Database(), parent=None, engine=None, scheduler=sched,
               instant_jingle_engine=None)
    s._manual_queue = []
    s._pending_spots = []
    s._pending_sotgs = []
    s._teased_songs = []
    s._tease_waiting_for_break = False
    yield s, sched
    s.deleteLater()


def _refresh(s):
    """The display refreshes that run on every song start."""
    s._apply_playing_state({"id": 999, "title": "On Air Now",
                            "artist": "X", "duration_ms": 180_000})


def _chip_title(s):
    return s._next_chip._title


def _glowing_card_title(s):
    glowing = [c.song() for c in s._upcoming._cards
               if c.song() is not None and c._is_next]
    assert len(glowing) == 1, f"exactly one NEXT card, got {len(glowing)}"
    return glowing[0].get("title")


def _eos_pick_title(s):
    """What the song-EOS chain would air (mirrors the deck branch of
    _on_engine_playback_ended), evaluated on a throwaway cursor."""
    if s._pending_sotgs:
        return s._pending_sotg_to_card(dict(s._pending_sotgs[0]))["title"]
    if s._pending_spots:
        return s._pending_spot_to_card(int(s._pending_spots[0]))["title"]
    if not s._tease_waiting_for_break:
        for t in s._teased_songs:
            if s._teased_song_will_air(t):
                return t["title"]
    head = s._scheduler.peek_next(1)
    return head[0]["title"] if head else None


def _assert_one_truth(s, expected):
    assert _chip_title(s) == expected
    assert _glowing_card_title(s) == expected
    assert _eos_pick_title(s) == expected


def test_tease_waiting_for_break_jingle_is_next(studio):
    """The 08:40 scenario: pinned songs wait for the break, so the
    scheduler's jingle airs next — chip, NEXT card and EOS agree."""
    s, sched = studio
    a, b = _real_song_ids(2)
    s._teased_songs = [_teased(a, "Mere Sapno ki Rani"),
                       _teased(b, "Suraj Hua Madham")]
    s._tease_waiting_for_break = True
    _refresh(s)
    _assert_one_truth(s, "Jingle _Trending")
    # The pinned songs are still shown — after the pre-break items.
    titles = [c.get("title") for c in s._upcoming_preview]
    assert titles.index("Mere Sapno ki Rani") > titles.index(
        "Jingle _Trending")
    assert all(c.get("_after_break") for c in s._upcoming_preview
               if c.get("_teased"))
    # The real EOS gate agrees: no pinned song is released yet.
    assert s._pop_next_teased_song() is None
    assert sched.cursor == 0


def test_break_on_air_pinned_song_is_next(studio):
    s, sched = studio
    (a,) = _real_song_ids(1)
    s._teased_songs = [_teased(a, "Mere Sapno ki Rani")]
    s._tease_waiting_for_break = False      # the break went to air
    _refresh(s)
    _assert_one_truth(s, "Mere Sapno ki Rani")
    assert s._upcoming_preview[0].get("title") == "Mere Sapno ki Rani"
    assert sched.cursor == 0


def test_deleted_pinned_song_is_not_promised(studio):
    """Dispatch skips a pin whose song was deleted since the tease was
    armed — so neither the chip nor any card may promise it."""
    s, sched = studio
    (a,) = _real_song_ids(1)
    s._teased_songs = [_teased(_DELETED_SONG_ID, "Deleted Since Pinned"),
                       _teased(a, "Still In Library")]
    s._tease_waiting_for_break = False
    _refresh(s)
    assert _chip_title(s) == _glowing_card_title(s) == "Still In Library"
    assert "Deleted Since Pinned" not in [
        c.get("title") for c in s._upcoming_preview]
    # ...and the real EOS pop agrees.
    assert s._pop_next_teased_song()["title"] == "Still In Library"


def test_pending_spot_is_next(studio, monkeypatch):
    s, sched = studio
    monkeypatch.setattr(
        s, "_pending_spot_to_card",
        lambda cid: {"_item_type": "spot", "id": cid,
                     "title": f"Spot {cid}", "artist": "Ad Break",
                     "duration_ms": 30_000})
    s._pending_spots = [19]
    _refresh(s)
    _assert_one_truth(s, "Spot 19")
    assert sched.cursor == 0


def test_pending_sotg_beats_pending_spot(studio, monkeypatch):
    s, sched = studio
    monkeypatch.setattr(
        s, "_pending_spot_to_card",
        lambda cid: {"_item_type": "spot", "id": cid,
                     "title": f"Spot {cid}", "artist": "Ad Break",
                     "duration_ms": 30_000})
    monkeypatch.setattr(
        s, "_pending_sotg_to_card",
        lambda a: {"_item_type": "sotg", "id": a["assignment_id"],
                   "title": f"SOTG {a['assignment_id']}", "artist": "SOTG",
                   "duration_ms": 20_000})
    s._pending_spots = [19]
    s._pending_sotgs = [{"assignment_id": 4}]
    _refresh(s)
    _assert_one_truth(s, "SOTG 4")
    assert sched.cursor == 0


def test_preview_spot_is_shown_but_not_glowing(studio, monkeypatch):
    """A T-60s preview spot is not due yet, so it is not 'next': it may
    render first, but the NEXT glow stays on what the chip shows."""
    s, sched = studio
    monkeypatch.setattr(
        s, "_pending_spot_to_card",
        lambda cid: {"_item_type": "spot", "id": cid,
                     "title": f"Spot {cid}", "artist": "Ad Break",
                     "duration_ms": 30_000})
    s._upcoming_preview_spots = [{"campaign_id": 33, "break_time": "08:45"}]
    s._load_upcoming_queue()
    _refresh(s)
    assert s._upcoming_preview[0].get("_preview") is True
    assert not s._upcoming._cards[0]._is_next
    assert _chip_title(s) == _glowing_card_title(s) == "Jingle _Trending"
    assert sched.cursor == 0
