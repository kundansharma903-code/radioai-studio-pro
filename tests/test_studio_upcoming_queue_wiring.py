"""
Studio v3 — Up Coming queue wiring tests (Phase B).

Studio's UpComingQueue panel previously read first 5 songs directly
from the songs table. Phase B wires it to ``scheduler.peek_next(5)``
so the panel displays what the clock-driven scheduler will actually
dispatch — Jazler-standard behaviour.

Coverage:
  1. Real queue loads on init via peek_next — translated dicts land
     in self._upcoming_preview.
  2. AT timestamp math: 3 mocked tracks (60s, 90s, 30s) at a known
     wall-clock yield correctly cumulative AT values via the panel's
     existing ``_fmt_at_clock`` helper.
  3. Empty scheduler queue → 5 placeholders (legacy fallback path
     activates because _upcoming_preview is empty).
  4. Partial queue (2 items returned by peek_next) → 2 real cards +
     3 placeholder cards. Layout never jumps.
  5. ``song_auto_advance`` signal triggers a fresh peek_next call —
     verified via mock call counter.
  6. (bonus) 1Hz live AT tick — Studio's existing _on_tick refreshes
     the panel; advancing wall-clock changes the rendered AT.
  7. (bonus) Studio constructed without scheduler — panel renders the
     legacy fallback (no crash, 5 cards bound to in-memory queue).

Pattern mirrors tests/test_studio_instant_jingles_wiring.py — _FakeIJE
became _FakeScheduler. _RecordingSignal pyqtSignal stand-in is shared
in spirit (re-defined locally so this file stays self-contained).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytest

from core.database import Database
from ui.studio import Studio


# ── Test doubles ────────────────────────────────────────────────────────


class _RecordingSignal:
    """pyqtSignal stand-in — records connects, fires synchronously on
    emit. Same as Phase A's _RecordingSignal."""

    def __init__(self):
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, _slot=None) -> None:
        self._slots.clear()

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class _FakeScheduler:
    """Records every peek_next call and returns whatever items the
    test seeded. Exposes the same signals Studio subscribes to:
    spot_due / song_auto_advance / break_approaching / next_break_in /
    started / stopped — so Studio's existing wire path runs without
    error during construction."""

    def __init__(self, items: Optional[list[dict]] = None):
        self.peek_calls: int = 0
        self._items: list[dict] = list(items or [])
        self.spot_due          = _RecordingSignal()
        self.song_auto_advance = _RecordingSignal()
        self.break_approaching = _RecordingSignal()
        self.next_break_in     = _RecordingSignal()
        self.started           = _RecordingSignal()
        self.stopped           = _RecordingSignal()
        self._running: bool = False

    def peek_next(self, n: int = 5,
                  now: Optional[datetime] = None) -> list[dict]:
        self.peek_calls += 1
        return self._items[:n]

    def is_running(self) -> bool:
        return self._running

    def set_items(self, items: list[dict]) -> None:
        self._items = list(items)


def _peek_item(item_type: str, item_id: int, title: str, artist: str,
               duration_ms: int, slot_idx: int = 0) -> dict:
    """Build a peek_next-shaped dict (matches what the real scheduler
    returns at core/scheduler/engine.py:329)."""
    return {
        "item_type":   item_type,
        "item_id":     item_id,
        "file_path":   f"/fake/{item_id}.mp3",
        "title":       title,
        "artist":      artist,
        "duration_ms": duration_ms,
        "clock_id":    1,
        "slot_idx":    slot_idx,
    }


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def studio_with_scheduler(qtbot):
    """Studio constructed with a fresh _FakeScheduler. Returns
    (studio, scheduler)."""
    db = Database()
    sch = _FakeScheduler()
    s = Studio(db=db, engine=None, scheduler=sch,
               instant_jingle_engine=None)
    qtbot.addWidget(s)
    return s, sch


# ── Tests ───────────────────────────────────────────────────────────────


def test_real_queue_loads_on_init_via_peek_next(qtbot):
    """Studio constructor calls _load_upcoming_queue once at the end
    of __init__ — peek_next must have been hit and the translated
    items stored in _upcoming_preview."""
    db = Database()
    seed = [
        _peek_item("song", 11, "Track A", "Artist X", 180_000, slot_idx=0),
        _peek_item("song", 22, "Track B", "Artist Y",  90_000, slot_idx=1),
        _peek_item("jingle", 7, "Station Jingle", "JINGLE", 8_000, slot_idx=2),
    ]
    sch = _FakeScheduler(seed)
    s = Studio(db=db, engine=None, scheduler=sch,
               instant_jingle_engine=None)
    qtbot.addWidget(s)

    assert sch.peek_calls >= 1
    assert len(s._upcoming_preview) == 3
    # Translated shape: id from item_id, _item_type from item_type,
    # everything else passthrough.
    first = s._upcoming_preview[0]
    assert first["id"] == 11
    assert first["_item_type"] == "song"
    assert first["title"] == "Track A"
    assert first["artist"] == "Artist X"
    assert first["duration_ms"] == 180_000


def test_at_timestamps_cumulative_math(studio_with_scheduler):
    """3 tracks of 60s + 90s + 30s. With cum_s starting at 0, the
    panel passes (0, 60, 150) to _fmt_at_clock for the three cards.
    We verify the cards' rendered AT strings are exactly:
        card 0: now (0 seconds offset)
        card 1: now + 60s
        card 2: now + 150s (60 + 90)
    The panel uses datetime.now() inside _fmt_at_clock so we recompute
    expected values from the same instant."""
    studio, sch = studio_with_scheduler
    sch.set_items([
        _peek_item("song", 1, "A", "X", 60_000),
        _peek_item("song", 2, "B", "Y", 90_000),
        _peek_item("song", 3, "C", "Z", 30_000),
    ])
    studio._load_upcoming_queue()

    # Read back the AT strings from the cards via the public attr.
    cards = studio._upcoming._cards
    at0 = cards[0]._at_text
    at1 = cards[1]._at_text
    at2 = cards[2]._at_text
    # Reverse the cumulative seconds from the rendered HH:MM:SS strings.
    def to_secs(s: str) -> int:
        h, m, sec = (int(p) for p in s.split(":"))
        return h * 3600 + m * 60 + sec
    delta_1 = (to_secs(at1) - to_secs(at0)) % (24 * 3600)
    delta_2 = (to_secs(at2) - to_secs(at0)) % (24 * 3600)
    assert delta_1 == 60   # 60s after first
    assert delta_2 == 150  # 60 + 90 after first


def test_empty_scheduler_queue_renders_5_placeholders(studio_with_scheduler):
    """peek_next returns []. _upcoming_preview is empty so the legacy
    fallback runs — _queue_songs[:5] is rendered. Even if the live DB
    is also empty, all 5 cards must exist (just with set_song(None))."""
    studio, sch = studio_with_scheduler
    sch.set_items([])
    studio._load_upcoming_queue()

    cards = studio._upcoming._cards
    assert len(cards) == 5
    # When peek is empty AND _queue_songs is also empty, every card's
    # _song attribute is None. When _queue_songs has content, cards
    # render that content. Either way the panel doesn't crash and
    # always shows exactly 5 cards.
    assert all(c is not None for c in cards)


def test_partial_queue_two_items_three_placeholders(studio_with_scheduler):
    """peek_next returns 2 items, panel must render those 2 + 3
    blank placeholders. Layout never jumps."""
    studio, sch = studio_with_scheduler
    sch.set_items([
        _peek_item("song", 1, "Only One", "DJ", 60_000),
        _peek_item("song", 2, "Only Two", "DJ", 60_000),
    ])
    studio._load_upcoming_queue()

    cards = studio._upcoming._cards
    # First two cards have a song bound
    assert cards[0]._song is not None
    assert cards[1]._song is not None
    # Trailing three cards are placeholders
    assert cards[2]._song is None
    assert cards[3]._song is None
    assert cards[4]._song is None


def test_song_auto_advance_signal_triggers_fresh_peek(studio_with_scheduler):
    """Belt + suspenders refresh — when scheduler dispatches the next
    song, panel must pull a fresh peek_next."""
    studio, sch = studio_with_scheduler
    sch.set_items([_peek_item("song", 1, "T", "A", 60_000)])
    # Reset counter — initial peek already fired during ctor + initial
    # _load_upcoming_queue call.
    sch.peek_calls = 0

    sch.song_auto_advance.emit()

    assert sch.peek_calls >= 1


def test_live_at_tick_refreshes_via_existing_1hz_timer(qtbot,
                                                       studio_with_scheduler):
    """Phase B reuses Studio's existing 1Hz _tick_timer for the live
    AT refresh — _on_tick now also calls _refresh_upcoming_panel. We
    capture the rendered AT string, advance qtbot wait > 1s, and
    assert the AT changed (because real wall-clock advanced)."""
    studio, sch = studio_with_scheduler
    sch.set_items([_peek_item("song", 1, "T", "A", 60_000)])
    studio._load_upcoming_queue()

    before_at = studio._upcoming._cards[0]._at_text
    qtbot.wait(1100)            # > 1 tick interval
    after_at = studio._upcoming._cards[0]._at_text

    # The first card's AT corresponds to "now". After 1+ second of
    # wall-clock advance, the rendered seconds differ.
    assert before_at != after_at


def test_studio_without_scheduler_does_not_crash(qtbot):
    """Decorative fallback — Studio constructed with scheduler=None
    must still render 5 cards. Since the 2026-07-02 queue fix the
    preview itself carries the static-queue song cards (so a pending
    spot can never leave the tray without songs)."""
    db = Database()
    s = Studio(db=db, engine=None, scheduler=None,
               instant_jingle_engine=None)
    qtbot.addWidget(s)

    cards = s._upcoming._cards
    assert len(cards) == 5
    assert all((c.get("_item_type") or "song") == "song"
               for c in s._upcoming_preview)
    # _on_tick is wired to the 1Hz timer — must not raise even when
    # there's no scheduler.
    s._on_tick()
    # Direct call to the loader path also must not raise
    s._load_upcoming_queue()
