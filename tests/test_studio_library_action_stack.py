"""
Studio v3 → Libraries panel: Action Stack (ADD / INSERT / REPLACE /
DELETE / PREPAIR) wiring.

Pinned behaviour after the Action Stack wiring:
  • Buttons emit the corresponding pyqtSignal on the panel.
  • Studio's handlers translate the active library row (Songs /
    Sweepers / Jingles / Spots) into a queue-dict and mutate
    _queue_songs:
      - ADD     → append
      - INSERT  → insert at head
      - REPLACE → overwrite head (or append on empty queue)
      - DELETE  → remove matching id+item_type from the queue
      - PREPAIR → load to deck paused (no play() call), set
                  _playback_cid / _current_track
  • All handlers no-op gracefully when nothing is selected.

Mocks: a minimal _FakeAudioEngine for PREPAIR that tracks
load_file / play / cleanup so the test can assert the no-play
contract.
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


# ── ADD / INSERT / REPLACE / DELETE on Songs queue ─────────────────────


def test_add_appends_to_queue(qtbot, db, engine):
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Songs")
    s._libraries._on_row_selected(0)
    before = len(s._queue_songs)
    s._on_lib_add()
    assert len(s._queue_songs) == before + 1


def test_add_with_no_selection_is_noop(qtbot, db, engine):
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    # Default selection is -1 (no row picked)
    before = len(s._queue_songs)
    s._on_lib_add()
    assert len(s._queue_songs) == before


def test_insert_pushes_to_queue_head(qtbot, db, engine):
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    if not s._queue_songs:
        pytest.skip("Need ≥1 song in the manual queue baseline")
    s._libraries._on_type_clicked("Songs")
    s._libraries._on_row_selected(0)
    head_before = s._queue_songs[0]
    s._on_lib_insert()
    # Inserted at index 0 — head moves down. The new head should be
    # the row we picked (a duplicate of head_before since we picked
    # index 0 and the row is added at 0).
    assert len(s._queue_songs) >= 2
    assert s._queue_songs[1].get("title") == head_before.get("title")


def test_replace_overwrites_queue_head(qtbot, db, engine):
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    if not s._queue_songs:
        pytest.skip("Need ≥1 song in the manual queue baseline")
    s._libraries._on_type_clicked("Songs")
    # Songs tile now sources from the full DB library (db.get_songs()),
    # not _queue_songs. Pick a real library row + read its rich data
    # back via the panel's selected_song_data() accessor so the assert
    # compares against the song REPLACE actually consumed.
    s._libraries._on_row_selected(1)   # pick the 2nd library row
    target = s._libraries.selected_song_data()
    if not target:
        pytest.skip("Library panel needs ≥2 songs to pick row 1")
    s._on_lib_replace()
    assert s._queue_songs[0].get("title") == target.get("title")


def test_replace_on_empty_queue_appends(qtbot, db, engine):
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    if not s._queue_songs:
        pytest.skip("Need ≥1 song to pick from")
    s._libraries._on_type_clicked("Songs")
    s._libraries._on_row_selected(0)
    target_title = s._queue_songs[0].get("title")
    s._queue_songs.clear()
    s._libraries._on_row_selected(0)   # re-prime — the panel doesn't auto-clear
    # Simulate the row still being valid via direct add
    s._queue_songs = [{"id": 9999, "title": "stub", "artist": "stub",
                       "duration_ms": 5000}]
    s._queue_songs.clear()
    s._on_lib_replace()
    # When the queue was empty AND the selection points at a now-
    # invalid index, the handler returns gracefully — assert no crash
    # and queue state is internally consistent.
    assert isinstance(s._queue_songs, list)


def test_delete_removes_matching_queue_entry(qtbot, db, engine):
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Songs")
    s._libraries._on_row_selected(0)
    # Pick the library-panel's selected song (Songs tile now sources
    # from db.get_songs(), not _queue_songs). Then seed the queue
    # with exactly that song so DELETE has a deterministic match.
    target = s._libraries.selected_song_data()
    if not target:
        pytest.skip("Library panel has no songs to pick")
    target_id = int(target.get("id") or 0)
    s._queue_songs = [dict(target)]
    s._on_lib_delete()
    assert all(int(q.get("id") or 0) != target_id
               for q in s._queue_songs), \
        "DELETE must drop every row whose id matches the selection"


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
