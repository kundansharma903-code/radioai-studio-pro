"""
Studio Libraries panel — sweeper tile wiring (Phase 2 of sweeper
ecosystem wiring).

Operator scenario: while a song is on the deck, the broadcaster wants
to manually drop a sweeper. Studio's Libraries panel has a "Sweepers"
type tile (replacing the placeholder "Folders" tile). Clicking it
swaps the table from songs to sweepers; double-clicking a sweeper row
fires it as an overlay on the deck.

Pinned behaviour:
  • The seventh tile in _LIB_TYPE_ICONS is "Sweepers" (not "Folders").
  • Clicking the Sweepers tile emits library_type_changed("Sweepers").
  • Studio listens, fetches active sweepers from DB, populates the
    table with name/position rows, and caches the (id, name, ...)
    list so the row-double-click can resolve the sweeper id.
  • Double-click on a sweeper row routes to _on_play_sweeper_overlay,
    NOT _on_queue_song_play. The deck channel stays untouched.
  • Switching back to "Songs" reloads _queue_songs.
  • active_library_type() reflects the current tile.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import Database
from ui.studio import Studio, _LIB_TYPE_ICONS


# ── Fakes from Phase 1 — keep one shape used by both files ──────────────────

class _RecordingSignal:
    def __init__(self):
        self._slots = []
    def connect(self, fn):  self._slots.append(fn)
    def emit(self, *a, **k):
        for fn in list(self._slots):
            fn(*a, **k)


class _FakeSweeperEngine:
    def __init__(self):
        self.scheduled = []
    def schedule_for_song(self, song_info, sweeper_info, deck_handle,
                          on_start=None, on_end=None):
        self.scheduled.append({"song": dict(song_info),
                               "sweeper": dict(sweeper_info),
                               "deck": deck_handle})
    def cancel(self):
        pass


@pytest.fixture
def db():
    return Database()


@pytest.fixture
def seeded_sweepers(db):
    """Insert 2 enabled + 1 disabled sweeper. Cleanup on teardown."""
    prefix = f"_test_lib_sweeper_{uuid.uuid4().hex[:8]}_"
    conn = db._conn()
    ids = []
    rows = [
        (prefix + "Alpha",  "Station", 8000, "Bridge at End", 1),
        (prefix + "Bravo",  "Station", 6000, "Before Intro",  1),
        (prefix + "Charly", "Station", 5000, "Start of Song", 0),  # disabled
    ]
    try:
        for name, cat, dur, pos, en in rows:
            cur = conn.execute(
                "INSERT INTO sweepers (name, category, file_path, "
                "duration_ms, position, is_enabled) VALUES (?, ?, "
                "'overlay.mp3', ?, ?, ?)",
                [name, cat, dur, pos, en])
            ids.append(int(cur.lastrowid))
        conn.commit()
        yield prefix, ids
    finally:
        for sid in ids:
            conn.execute("DELETE FROM sweepers WHERE id = ?", [sid])
        conn.commit()


def _make_studio(db, sweeper_engine=None) -> Studio:
    return Studio(db, parent=None, engine=None, scheduler=None,
                  instant_jingle_engine=None,
                  sweeper_engine=sweeper_engine)


# ── Tile inventory ──────────────────────────────────────────────────────────

def test_lib_type_icons_includes_sweepers():
    names = [t[0] for t in _LIB_TYPE_ICONS]
    assert "Sweepers" in names
    # The deprecated "Folders" placeholder must be gone.
    assert "Folders" not in names


# ── Type-tile click → table populates ───────────────────────────────────────

def test_clicking_sweepers_tile_loads_active_sweepers(qapp, db, seeded_sweepers):
    prefix, ids = seeded_sweepers
    studio = _make_studio(db)
    panel = studio._libraries

    panel._on_type_clicked("Sweepers")

    assert panel.active_library_type() == "Sweepers"
    cache = studio._library_sweepers
    matching = [c for c in cache if c["name"].startswith(prefix)]
    # Only the 2 enabled rows should appear (disabled row excluded).
    assert len(matching) == 2
    names = {c["name"] for c in matching}
    assert prefix + "Alpha" in names
    assert prefix + "Bravo" in names
    assert prefix + "Charly" not in names
    studio.deleteLater()


def test_switching_back_to_songs_clears_sweeper_cache(qapp, db, seeded_sweepers):
    studio = _make_studio(db)
    panel = studio._libraries
    panel._on_type_clicked("Sweepers")
    assert studio._library_sweepers, "expected sweepers loaded"
    panel._on_type_clicked("Songs")
    assert panel.active_library_type() == "Songs"
    assert studio._library_sweepers == []
    studio.deleteLater()


# ── Row double-click dispatch ──────────────────────────────────────────────

def test_row_double_click_in_sweeper_mode_routes_to_overlay(
        qapp, db, seeded_sweepers):
    prefix, ids = seeded_sweepers
    swe = _FakeSweeperEngine()
    studio = _make_studio(db, sweeper_engine=swe)
    studio._playback_cid = 17
    studio._current_track = {"id": 1, "duration_ms": 180000}
    studio._current_duration_ms = 180000

    panel = studio._libraries
    panel._on_type_clicked("Sweepers")
    # Find the index of the seeded "Alpha" row in the cached list
    alpha_idx = next(
        i for i, c in enumerate(studio._library_sweepers)
        if c["name"] == prefix + "Alpha")

    # Simulate the double-click signal that the songs table emits
    studio._on_library_song_double_clicked(alpha_idx)

    # Overlay path was invoked with the right deck handle
    assert len(swe.scheduled) == 1
    assert swe.scheduled[0]["deck"] == 17
    assert swe.scheduled[0]["sweeper"]["file_path"] == "overlay.mp3"
    assert swe.scheduled[0]["sweeper"]["position"] == "Bridge at End"
    studio.deleteLater()


def test_row_double_click_in_song_mode_uses_legacy_deck_path(qapp, db):
    """Default (Songs) tile: double-click routes to _queue_songs (existing
    behaviour). The sweeper overlay path must NOT fire."""
    swe = _FakeSweeperEngine()
    studio = _make_studio(db, sweeper_engine=swe)
    panel = studio._libraries
    assert panel.active_library_type() == "Songs"
    # _queue_songs is populated by Studio init from real DB songs.
    if not studio._queue_songs:
        pytest.skip("dev DB has no songs to drive this test")
    # Patch _on_queue_song_play to record the call instead of touching
    # the audio engine (engine=None in test ctor anyway).
    captured: list[dict] = []
    studio._on_queue_song_play = lambda song: captured.append(song)

    studio._on_library_song_double_clicked(0)

    assert captured and captured[0] is studio._queue_songs[0]
    assert len(swe.scheduled) == 0   # overlay must not fire in Songs mode
    studio.deleteLater()


# ── Signal emission contract ───────────────────────────────────────────────

def test_library_type_changed_signal_fires(qapp, db):
    studio = _make_studio(db)
    panel = studio._libraries
    captured: list[str] = []
    panel.library_type_changed.connect(captured.append)

    panel._on_type_clicked("Sweepers")
    panel._on_type_clicked("Songs")
    panel._on_type_clicked("Songs")     # idempotent — no second emit

    assert captured == ["Sweepers", "Songs"]
    studio.deleteLater()
