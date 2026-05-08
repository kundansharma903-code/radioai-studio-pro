"""
Studio v3 → Libraries panel: $ Spots tile wiring.

Pinned behaviour after the Spots-tile wiring:
  • Clicking the $ Spots tile loads active campaigns into the Studio
    table (was a no-op stub before).
  • Studio's `_library_spots` cache holds the resolved campaign rows.
  • Switching back to Songs (or any other tile) clears the spots
    cache so subsequent double-clicks can't fall through to a stale
    set.
  • Row double-click while the Spots tile is active reuses the
    existing scheduler spot-due dispatch path (`_do_scheduler_spot_due`)
    so the broadcast-correct defer-vs-immediate logic is shared with
    scheduled spots.

Mocks: minimal — just monkeypatch `_do_scheduler_spot_due` on the
Studio instance to record the campaign id passed in.
"""

from __future__ import annotations

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
        self.pad_started  = _RecordingSignal()
        self.pad_ended    = _RecordingSignal()
        self.pad_stopped  = _RecordingSignal()

    def play_pad(self, *a, **k):
        self.calls.append(("play_pad",) + a + tuple(k.items()))
        return True

    def stop_pad(self, _id):
        return True

    def stop_all(self):
        return 0

    def is_playing(self, _id):
        return False


# ── Fixture ─────────────────────────────────────────────────────────────


@pytest.fixture
def db_with_campaign():
    db = Database()
    prefix = f"_test_studio_spots_{uuid.uuid4().hex[:8]}_"
    name = prefix + "Brand X"
    cur = db._conn().execute(
        "INSERT INTO campaigns (name, auto_code, is_active) "
        "VALUES (?, ?, 1)",
        [name, "AC-9100"])
    cid = int(cur.lastrowid)
    db._conn().commit()
    try:
        yield db, cid, name
    finally:
        try:
            db._conn().execute("DELETE FROM campaigns WHERE id = ?", [cid])
            db._conn().commit()
        except Exception:
            pass


# ── Tests ───────────────────────────────────────────────────────────────


def test_spots_tile_loads_active_campaigns(qtbot, db_with_campaign, engine):
    db, cid, name = db_with_campaign
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Spots")
    matching = [c for c in s._library_spots if int(c["id"]) == cid]
    assert len(matching) == 1
    assert matching[0]["name"] == name
    # Other library caches must be cleared so dispatch can't crosswire.
    assert s._library_sweepers == []
    assert s._library_jingles == []


def test_switching_back_to_songs_clears_spots_cache(qtbot, db_with_campaign, engine):
    db, cid, _name = db_with_campaign
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Spots")
    assert len(s._library_spots) >= 1
    s._libraries._on_type_clicked("Songs")
    assert s._library_spots == []


def test_spot_row_double_click_invokes_spot_due_dispatch(qtbot, db_with_campaign, engine):
    """The double-click handler must reuse the scheduler spot-due path
    so the broadcast-correct defer-vs-immediate logic is consistent
    between manual + scheduled spot fires."""
    db, cid, _name = db_with_campaign
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Spots")
    # Patch out the dispatcher so the test doesn't actually try to
    # hit BASS / file I/O.
    fired: list[int] = []
    s._do_scheduler_spot_due = lambda c: fired.append(int(c))
    idx = next((i for i, c in enumerate(s._library_spots)
                if int(c["id"]) == cid), -1)
    assert idx >= 0
    s._on_library_song_double_clicked(idx)
    assert fired == [cid]


def test_spot_double_click_with_zero_id_is_noop(qtbot, db_with_campaign, engine):
    """Defensive guard: a stale cache row with id=0 must not invoke
    the spot dispatcher."""
    db, _cid, _name = db_with_campaign
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Spots")
    # Inject a synthetic zero-id entry at the head.
    s._library_spots.insert(0, {"id": 0, "name": "_invalid",
                                "auto_code": "", "file_count": 0,
                                "end_date": ""})
    fired: list[int] = []
    s._do_scheduler_spot_due = lambda c: fired.append(int(c))
    s._on_library_song_double_clicked(0)
    assert fired == [], "id=0 must not trigger spot dispatch"
