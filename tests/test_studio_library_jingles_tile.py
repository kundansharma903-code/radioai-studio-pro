"""
Studio v3 → Libraries panel: 🔔 Jingles tile wiring.

Pinned behaviour after the Studio-side jingles wiring:
  • Clicking the 🔔 Jingles type tile loads the master `jingles`
    library into the Studio table (was a no-op stub before).
  • Studio's `_library_jingles` cache holds the resolved rows.
  • Switching back to Songs (or any other tile) clears the jingles
    cache so subsequent double-clicks can't fall through to a stale
    set.
  • Row double-click while the Jingles tile is active fires the
    jingle through the InstantJingleEngine using a high-offset
    pad-key (LIBRARY_JINGLE_PAD_OFFSET + jingle_id) so it never
    collides with a real `jingle_pads.id`.
  • Re-double-click on the same row toggles the fade-stop path
    (matches the tile-click behaviour the operator already knows).

Mocks: `_FakeIJE` mirrors the wiring-test fake and now also tracks
`is_playing` per pad-key so the toggle logic can be asserted.
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
    """IJE fake that records play_pad / fade_stop_pad / stop_all and
    tracks is_playing per pad-key."""

    def __init__(self):
        self.calls: list[tuple] = []
        self._playing: set[int] = set()
        self.pad_started  = _RecordingSignal()
        self.pad_ended    = _RecordingSignal()
        self.pad_stopped  = _RecordingSignal()

    def play_pad(self, pad_id, file_path, volume=100, loop=False):
        self.calls.append(("play_pad", int(pad_id), file_path,
                           int(volume), bool(loop)))
        self._playing.add(int(pad_id))
        return True

    def stop_pad(self, pad_id):
        self.calls.append(("stop_pad", int(pad_id)))
        self._playing.discard(int(pad_id))
        return True

    def fade_stop_pad(self, pad_id, fade_ms=1500):
        self.calls.append(("fade_stop_pad", int(pad_id), int(fade_ms)))
        self._playing.discard(int(pad_id))
        return True

    def stop_all(self):
        self.calls.append(("stop_all",))
        n = len(self._playing); self._playing.clear()
        return n

    def is_playing(self, pad_id):
        return int(pad_id) in self._playing

    def get_duration_ms(self, _path):
        return 1234


# ── Fixture ─────────────────────────────────────────────────────────────


@pytest.fixture
def db_with_jingle():
    """Insert one library jingle pointing at a real on-disk audio file
    so the dispatch path's file_path check passes."""
    db = Database()
    row = db._conn().execute(
        "SELECT file_path FROM songs WHERE file_path IS NOT NULL "
        "AND file_path != '' ORDER BY id LIMIT 1"
    ).fetchone()
    real_path = row[0] if row and os.path.exists(row[0] or "") else None
    if real_path is None:
        pytest.skip("Need a song with playable file_path")
    db._ensure_jingles_columns()
    prefix = f"_test_studio_libj_{uuid.uuid4().hex[:8]}_"
    jid = db.add_jingle({
        "name": prefix + "Open",
        "category": "Station ID",
        "file_path": real_path,
        "duration_ms": 4000,
        "is_enabled": 1,
    })
    try:
        yield db, jid, prefix, real_path
    finally:
        try:
            db._conn().execute("DELETE FROM jingles WHERE id = ?", [jid])
            db._conn().commit()
        except Exception:
            pass


# ── Tests ───────────────────────────────────────────────────────────────


def test_jingles_tile_loads_library_into_table_cache(qtbot, db_with_jingle, engine):
    db, jid, prefix, _path = db_with_jingle
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    # Activate the 🔔 Jingles tile
    s._libraries._on_type_clicked("Jingles")
    # Cache should contain at least the seeded row
    matching = [j for j in s._library_jingles
                if int(j["id"]) == jid]
    assert len(matching) == 1
    assert matching[0]["name"] == prefix + "Open"
    # Sweeper cache is cleared so the dispatcher can't crosswire.
    assert s._library_sweepers == []


def test_switching_back_to_songs_clears_jingle_cache(qtbot, db_with_jingle, engine):
    db, jid, _prefix, _path = db_with_jingle
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Jingles")
    assert len(s._library_jingles) >= 1
    s._libraries._on_type_clicked("Songs")
    assert s._library_jingles == [], (
        "Songs tile must clear the jingle cache so a stale row can't "
        "leak into a Songs-mode double-click")


def test_jingle_row_double_click_fires_through_ije(qtbot, db_with_jingle, engine):
    db, jid, _prefix, real_path = db_with_jingle
    ije = _FakeIJE()
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=ije)
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Jingles")
    # Find the seeded row's index in the cache.
    idx = next((i for i, j in enumerate(s._library_jingles)
                if int(j["id"]) == jid), -1)
    assert idx >= 0
    s._on_library_song_double_clicked(idx)
    plays = [c for c in ije.calls if c[0] == "play_pad"]
    assert len(plays) == 1
    pad_key, fp, _vol, _loop = plays[0][1], plays[0][2], plays[0][3], plays[0][4]
    assert pad_key == s.LIBRARY_JINGLE_PAD_OFFSET + jid, (
        "Library jingles must be namespaced by LIBRARY_JINGLE_PAD_OFFSET "
        "so they can't collide with a real jingle_pads.id")
    assert fp == real_path


def test_redouble_click_on_same_row_fades_out(qtbot, db_with_jingle, engine):
    db, jid, _prefix, _path = db_with_jingle
    ije = _FakeIJE()
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=ije)
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Jingles")
    idx = next((i for i, j in enumerate(s._library_jingles)
                if int(j["id"]) == jid), -1)
    s._on_library_song_double_clicked(idx)   # play
    s._on_library_song_double_clicked(idx)   # toggle → fade-stop
    fades = [c for c in ije.calls if c[0] == "fade_stop_pad"]
    assert len(fades) == 1
    assert fades[0][1] == s.LIBRARY_JINGLE_PAD_OFFSET + jid
    assert fades[0][2] == s.JINGLE_FADE_MS
    plays = [c for c in ije.calls if c[0] == "play_pad"]
    assert len(plays) == 1, \
        "Second double-click must fade-stop, NOT play_pad again"


def test_jingle_with_no_file_path_is_skipped(qtbot, db_with_jingle, engine):
    """A library row without a file_path must not reach play_pad
    (it'd just be a dead click)."""
    db, _jid, prefix, _path = db_with_jingle
    db._ensure_jingles_columns()
    bad_id = db.add_jingle({
        "name": prefix + "Empty",
        "category": "Promo",
        "file_path": "",   # empty
        "duration_ms": 2000,
        "is_enabled": 1,
    })
    try:
        ije = _FakeIJE()
        s = Studio(db=db, engine=engine, scheduler=None,
                   instant_jingle_engine=ije)
        qtbot.addWidget(s)
        s._libraries._on_type_clicked("Jingles")
        idx = next((i for i, j in enumerate(s._library_jingles)
                    if int(j["id"]) == bad_id), -1)
        assert idx >= 0
        s._on_library_song_double_clicked(idx)
        assert not any(c[0] == "play_pad" for c in ije.calls), \
            "Empty file_path must skip play_pad (dead click prevention)"
    finally:
        db._conn().execute("DELETE FROM jingles WHERE id = ?", [bad_id])
        db._conn().commit()


def test_no_ije_no_crash(qtbot, db_with_jingle, engine):
    """Studio constructed without an IJE instance must not crash on a
    library-jingle double-click — same defensive contract as the
    sweeper path."""
    db, jid, _prefix, _path = db_with_jingle
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=None)
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Jingles")
    idx = next((i for i, j in enumerate(s._library_jingles)
                if int(j["id"]) == jid), -1)
    s._on_library_song_double_clicked(idx)   # must not raise
