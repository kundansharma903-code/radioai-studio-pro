"""
Studio v3 → Libraries panel: Action Stack (ADD / INSERT / REPLACE /
DELETE / PREPAIR) wiring.

Contract since 2026-10-16 (operator decision — the stack used to edit
only the DISPLAY list, so an inserted song showed in Up Coming while
the scheduler's pick aired instead):
  • ADD / INSERT put the library item in Studio._manual_queue, which
    _compute_next_song consumes BEFORE the scheduler. It really airs.
      - ADD     → after the selected manual card, else at the end
      - INSERT  → before the selected manual card, else at the head
  • REPLACE / DELETE on a manual card edit _manual_queue in place.
  • REPLACE / DELETE on a scheduler card arm a one-shot skip: the next
    time the scheduler hands that item out it is not aired (2 h TTL).
    REPLACE also queues the library item manually.
  • Spots are refused (they air from their own schedule); a library row
    whose audio file is missing is refused with a warning.
  • PREPAIR → load to deck paused (no play() call), set
    _playback_cid / _current_track.
  • All handlers no-op gracefully when nothing is selected.

Mocks: a minimal _FakeAudioEngine for PREPAIR that tracks
load_file / play / cleanup so the test can assert the no-play
contract; _FakeScheduler hands out a fixed song rotation.
"""

from __future__ import annotations

import os
import uuid

import pytest

from core.database import Database
from ui.studio import Studio


# ── Test doubles ────────────────────────────────────────────────────────


class _RecordingSignal:
    def __init__(self):
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def disconnect(self, _slot=None) -> None:
        self._slots.clear()

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class _FakeIJE:
    def __init__(self):
        self.calls: list[tuple] = []
        self.pad_started = _RecordingSignal()
        self.pad_ended   = _RecordingSignal()
        self.pad_stopped = _RecordingSignal()

    def play_pad(self, *a, **k): return True
    def stop_pad(self, _id):    return True
    def stop_all(self):         return 0
    def is_playing(self, _id):  return False


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    return Database()


# ── Helpers ─────────────────────────────────────────────────────────────


class _FakeScheduler:
    """Running scheduler that hands out `songs` round-robin. peek_next
    shows the upcoming picks without consuming them."""

    def __init__(self, songs):
        self.songs = songs
        self.i = 0
        for n in ("spot_due", "song_auto_advance", "break_approaching",
                  "next_break_in", "schedule_reloaded", "error_occurred",
                  "started", "stopped", "active_clock_changed",
                  "queue_changed"):
            setattr(self, n, _RecordingSignal())

    def is_running(self):
        return True

    def start(self):
        pass

    def stop(self):
        pass

    def _item(self, s):
        return {"item_type": "song", "item_id": s["id"],
                "title": s["title"], "artist": s["artist"],
                "file_path": s["file_path"],
                "duration_ms": s["duration_ms"],
                "clock_id": None, "slot_idx": 1}

    def pick_next_item(self, _now=None):
        s = self.songs[self.i % len(self.songs)]
        self.i += 1
        return self._item(s)

    def peek_next(self, n=5, now=None):
        return [self._item(self.songs[(self.i + k) % len(self.songs)])
                for k in range(n)]


def _playable_songs(db, n, exclude=()):
    out = []
    for r in db._conn().execute(
            "SELECT id, title, artist, file_path, duration_ms FROM songs "
            "WHERE is_enabled = 1 ORDER BY id"):
        if r["file_path"] and os.path.exists(r["file_path"]) \
                and int(r["id"]) not in exclude:
            out.append({k: r[k] for k in r.keys()})
            if len(out) >= n:
                break
    if len(out) < n:
        pytest.skip(f"Need {n} playable songs in the DB")
    return out


def _select_playable(s, exclude_ids=(), nth=0) -> dict:
    """Select the nth Songs-library row with an on-disk file whose id is
    not in exclude_ids. Returns the row dict (skips if none)."""
    s._libraries._on_type_clicked("Songs")
    seen = 0
    for i in range(len(s._libraries._rows)):
        s._libraries._on_row_selected(i)
        d = s._libraries.selected_song_data()
        if (d and d.get("file_path") and os.path.exists(d["file_path"])
                and int(d.get("id") or 0) not in exclude_ids):
            if seen == nth:
                return d
            seen += 1
    pytest.skip("No playable library song to select")


def _studio(qtbot, db, engine, scheduler=None):
    s = Studio(db=db, engine=engine, scheduler=scheduler,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    return s


def _ids(items):
    return [int(x.get("id") or 0) for x in items]


@pytest.fixture
def quiet_dialogs(monkeypatch):
    """Record dialogs.info / dialogs.warning instead of opening them."""
    calls = []
    import core.dialogs as _d
    monkeypatch.setattr(_d, "info",
                        lambda *a, **k: calls.append(("info", a)))
    monkeypatch.setattr(_d, "warning",
                        lambda *a, **k: calls.append(("warning", a)))
    return calls


# ── ADD / INSERT — the operator's item really airs next ────────────────


def test_add_queues_item_and_it_airs_next(qtbot, db, engine):
    s = _studio(qtbot, db, engine)
    row = _select_playable(s)
    s._on_lib_add()
    assert _ids(s._manual_queue) == [int(row["id"])]
    nxt = s._compute_next_song(after_id=None)
    assert int(nxt["id"]) == int(row["id"])
    assert nxt["file_path"] == row["file_path"]
    assert nxt["_item_type"] == "song"
    assert s._manual_queue == [], "aired item must leave the manual queue"


def test_add_with_no_selection_is_noop(qtbot, db, engine):
    s = _studio(qtbot, db, engine)
    s._on_lib_add()
    s._on_lib_insert()
    assert s._manual_queue == []


def test_insert_goes_to_head(qtbot, db, engine):
    s = _studio(qtbot, db, engine)
    a = _select_playable(s, nth=0)
    s._on_lib_add()
    b = _select_playable(s, nth=1)
    s._on_lib_insert()
    assert _ids(s._manual_queue) == [int(b["id"]), int(a["id"])]
    aired = [s._compute_next_song(after_id=None) for _ in range(2)]
    assert _ids(aired) == [int(b["id"]), int(a["id"])]


def test_add_lands_after_selected_manual_card(qtbot, db, engine):
    s = _studio(qtbot, db, engine)
    a = _select_playable(s, nth=0); s._on_lib_add()
    c = _select_playable(s, nth=2); s._on_lib_add()
    s._queue_selected_song = dict(s._manual_queue[0])     # card A
    b = _select_playable(s, nth=1); s._on_lib_add()
    assert _ids(s._manual_queue) == [int(a["id"]), int(b["id"]),
                                     int(c["id"])]


def test_insert_lands_before_selected_manual_card(qtbot, db, engine):
    s = _studio(qtbot, db, engine)
    a = _select_playable(s, nth=0); s._on_lib_add()
    c = _select_playable(s, nth=2); s._on_lib_add()
    s._queue_selected_song = dict(s._manual_queue[1])     # card C
    b = _select_playable(s, nth=1); s._on_lib_insert()
    assert _ids(s._manual_queue) == [int(a["id"]), int(b["id"]),
                                     int(c["id"])]


def test_manual_item_beats_the_scheduler(qtbot, db, engine):
    sched_songs = _playable_songs(db, 3)
    s = _studio(qtbot, db, engine, _FakeScheduler(sched_songs))
    row = _select_playable(s, exclude_ids=set(_ids(sched_songs)))
    s._on_lib_insert()
    # Up Coming and the NEXT chip both show the operator's item first.
    s._load_upcoming_queue()
    manual_cards = [c for c in s._upcoming_preview if c.get("_manual")]
    assert _ids(manual_cards) == [int(row["id"])]
    assert int(s._peek_next_for_display(None)["id"]) == int(row["id"])
    # ...and it is what actually airs, then the scheduler resumes.
    aired = [s._compute_next_song(after_id=None) for _ in range(2)]
    assert int(aired[0]["id"]) == int(row["id"])
    assert int(aired[1]["id"]) == int(sched_songs[0]["id"])


# ── REPLACE / DELETE on manual cards ────────────────────────────────────


def test_replace_manual_card_in_place(qtbot, db, engine):
    s = _studio(qtbot, db, engine)
    a = _select_playable(s, nth=0); s._on_lib_add()
    b = _select_playable(s, nth=1); s._on_lib_add()
    s._queue_selected_song = dict(s._manual_queue[0])     # card A
    c = _select_playable(s, nth=2); s._on_lib_replace()
    assert _ids(s._manual_queue) == [int(c["id"]), int(b["id"])]
    assert s._scheduler_skips == {}


def test_delete_selected_manual_card(qtbot, db, engine):
    s = _studio(qtbot, db, engine)
    a = _select_playable(s, nth=0); s._on_lib_add()
    b = _select_playable(s, nth=1); s._on_lib_add()
    s._queue_selected_song = dict(s._manual_queue[0])
    s._on_lib_delete()
    assert _ids(s._manual_queue) == [int(b["id"])]
    assert s._scheduler_skips == {}


def test_delete_without_card_removes_library_item_from_manual(
        qtbot, db, engine):
    s = _studio(qtbot, db, engine)
    _select_playable(s, nth=0); s._on_lib_add()
    s._queue_selected_song = None
    s._on_lib_delete()                     # library row A still selected
    assert s._manual_queue == []
    assert s._scheduler_skips == {}


# ── REPLACE / DELETE on scheduler cards → one-shot skip ─────────────────


def test_delete_scheduler_card_skips_that_song_once(qtbot, db, engine):
    sched_songs = _playable_songs(db, 3)
    s = _studio(qtbot, db, engine, _FakeScheduler(sched_songs))
    s._load_upcoming_queue()
    card = next(c for c in s._upcoming_preview
                if s._is_scheduler_card(c))
    assert int(card["id"]) == int(sched_songs[0]["id"])
    s._queue_selected_song = dict(card)
    s._on_lib_delete()
    # Gone from the NEXT chip ...
    assert int(s._peek_next_for_display(None)["id"]) != int(card["id"])
    # ... and it does not air; the skip is used up, so the song airs
    # normally the next time rotation brings it round.
    aired = _ids(s._compute_next_song(after_id=None) for _ in range(3))
    assert aired == [int(sched_songs[1]["id"]), int(sched_songs[2]["id"]),
                     int(sched_songs[0]["id"])]
    assert s._scheduler_skips == {}


def test_replace_scheduler_card_skips_it_and_airs_library_item(
        qtbot, db, engine):
    sched_songs = _playable_songs(db, 3)
    s = _studio(qtbot, db, engine, _FakeScheduler(sched_songs))
    s._load_upcoming_queue()
    card = next(c for c in s._upcoming_preview
                if s._is_scheduler_card(c))
    s._queue_selected_song = dict(card)
    row = _select_playable(s, exclude_ids=set(_ids(sched_songs)))
    s._on_lib_replace()
    aired = _ids(s._compute_next_song(after_id=None) for _ in range(2))
    assert aired == [int(row["id"]), int(sched_songs[1]["id"])]


def test_scheduler_skip_expires(qtbot, db, engine):
    s = _studio(qtbot, db, engine)
    s._arm_scheduler_skip({"id": 4242, "_item_type": "song",
                           "title": "x"})
    assert s._is_scheduler_skipped("song", 4242)
    s._scheduler_skips[("song", 4242)] = 0.0          # already expired
    assert not s._is_scheduler_skipped("song", 4242)
    assert s._scheduler_skips == {}


# ── Refusals ────────────────────────────────────────────────────────────


def test_spot_is_not_accepted_in_manual_queue(qtbot, db, engine,
                                              quiet_dialogs):
    s = _studio(qtbot, db, engine)
    assert s._make_manual_item({"id": 1, "title": "Ad",
                                "_item_type": "spot"}) is None
    assert [c[0] for c in quiet_dialogs] == ["info"]
    assert s._manual_queue == []


def test_missing_audio_file_is_refused(qtbot, db, engine, quiet_dialogs):
    s = _studio(qtbot, db, engine)
    assert s._make_manual_item({"id": 0, "title": "Ghost",
                                "_item_type": "song",
                                "file_path": r"Z:\nope\ghost.mp3"}) is None
    assert [c[0] for c in quiet_dialogs] == ["warning"]


def test_spot_card_cannot_be_deleted(qtbot, db, engine, quiet_dialogs):
    s = _studio(qtbot, db, engine)
    s._queue_selected_song = {"id": 7, "title": "Ad",
                              "_item_type": "spot"}
    s._on_lib_delete()
    assert [c[0] for c in quiet_dialogs] == ["info"]
    assert s._scheduler_skips == {}


# ── PREPAIR — load to deck paused, no play() ────────────────────────────


def test_prepair_loads_deck_paused(qtbot, db):
    """PREPAIR must call engine.load_file + set_volume but NOT play().
    The operator triggers play via the transport ▶ when ready."""
    from core.audio import AudioEngine

    class _FakeAudioEngine:
        def __init__(self):
            self.calls: list[tuple] = []
            # pyqtSignal-shaped attrs Studio's __init__ wires.
            self.position_changed = _RecordingSignal()
            self.playback_ended   = _RecordingSignal()
            self.error_occurred   = _RecordingSignal()

        def load_file(self, path, loop=False):
            self.calls.append(("load", path)); return 42

        def set_volume(self, cid, vol):
            self.calls.append(("vol", int(cid), int(vol)))

        def play(self, cid):
            self.calls.append(("play", int(cid)))

        def cleanup(self, cid):
            self.calls.append(("cleanup", int(cid)))

        def cleanup_all(self):
            self.calls.append(("cleanup_all",))

        def get_levels(self, _cid): return (0.0, 0.0)

        def get_state(self, _cid): return "stopped"

    eng = _FakeAudioEngine()
    s = Studio(db=db, engine=eng, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Songs")
    # Walk the library rows to find one with a playable file_path —
    # the dev DB has some entries pointing at deleted files, can't
    # PREPAIR those.
    row = None
    for i in range(len(s._libraries._all_rows)):
        s._libraries._on_row_selected(i)
        candidate = s._libraries.selected_song_data()
        if (candidate and candidate.get("file_path")
                and os.path.exists(candidate["file_path"])):
            row = candidate
            break
    if row is None:
        pytest.skip("No library song with a playable file_path")
    s._on_lib_prepair()
    sequence = [c[0] for c in eng.calls]
    assert "load" in sequence
    assert "vol" in sequence
    assert "play" not in sequence, \
        "PREPAIR must NOT auto-play — operator triggers play themselves"
    assert s._playback_cid == 42
    assert s._playback_kind == "deck"
    assert s._current_track is not None
    assert s._current_track.get("title") == row.get("title")
    assert s._current_track.get("file_path") == row.get("file_path")
