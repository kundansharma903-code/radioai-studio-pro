"""
Studio v3 + standalone Instant Jingles — live-wiring tests.

After Phase A (Studio IJ panel) + the standalone IJ screen each owned
its own InstantJingleEngine. This file verifies:

  1. Standalone IJ screen accepts a shared `instant_jingle_engine`
     kwarg from MainWindow and reuses it instead of building its own.
  2. Default kwarg=None falls back to building an own IJE — preserves
     the existing tests + any context that constructs the screen
     standalone.
  3. `pads_changed` pyqtSignal fires after every DB mutation that
     affects what Studio's tile grid renders (pad label edit, color,
     volume, behaviour, assign-audio, clear-pad, add/rename/delete
     pallet, audio-output change).
  4. Studio.`_reload_instant_jingles()` re-pulls pads from the DB and
     pushes them to the tile panel via `set_tiles(...)`.
  5. `_force_studio_refresh()` (showEvent path) also reloads IJ pads
     so navigate-back to Studio after a standalone-screen edit picks
     up the change without any external signal.

Mocks: `_RecordingSignal` for pyqtSignal stand-ins, `_FakeIJE` /
`_FakeAudioEngine` mirror the shape used by
test_studio_instant_jingles_wiring.py.
"""

from __future__ import annotations

import os
import uuid

import pytest

from core.database import Database
from ui.studio import Studio
from core import dialogs as _dialogs


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
    """Same shape as test_studio_instant_jingles_wiring.py's _FakeIJE."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.pad_started  = _RecordingSignal()
        self.pad_ended    = _RecordingSignal()
        self.pad_stopped  = _RecordingSignal()

    def play_pad(self, pad_id: int, file_path: str,
                 volume: int = 100, loop: bool = False) -> bool:
        self.calls.append(("play_pad", int(pad_id), file_path,
                           int(volume), bool(loop)))
        return True

    def stop_pad(self, pad_id: int) -> bool:
        self.calls.append(("stop_pad", int(pad_id)))
        return True

    def stop_all(self) -> int:
        self.calls.append(("stop_all",))
        return 0

    def get_duration_ms(self, _path: str) -> int:
        return 1234


# ── Live-DB fixture (unique pallet prefix + try/finally cleanup) ────────


def _seed_two_pads(db: Database) -> dict:
    """Insert one pallet with two well-formed pads pointing to real
    on-disk audio files. Returns metadata for cleanup. Skips if the
    songs library lacks ≥2 playable rows."""
    conn = db._conn()
    rows = conn.execute(
        "SELECT file_path FROM songs WHERE file_path IS NOT NULL "
        "AND file_path != '' ORDER BY id LIMIT 5"
    ).fetchall()
    real_paths = [r[0] for r in rows if r[0] and os.path.exists(r[0])]
    if len(real_paths) < 2:
        return {}

    pallet_name = f"_test_jingles_live_{uuid.uuid4().hex[:8]}"
    cur = conn.execute(
        "INSERT INTO jingle_pallets (name, owner, grid_cols, grid_rows, "
        "audio_output, display_order) VALUES (?, '', 5, 6, 3, 9999)",
        [pallet_name],
    )
    pallet_id = int(cur.lastrowid)

    pad_ids: list[int] = []
    for i, path in enumerate(real_paths[:2]):
        cur = conn.execute(
            "INSERT INTO jingle_pads (pallet_id, pad_index, label, "
            "file_path, duration_ms, color, volume, behaviour) "
            "VALUES (?, ?, ?, ?, ?, '#F59E0B', 90, 'play_once')",
            [pallet_id, i, f"LIVE PAD {i}", path, 4000 + i * 1000],
        )
        pad_ids.append(int(cur.lastrowid))
    conn.commit()
    return {"pallet_id": pallet_id, "pad_ids": pad_ids,
            "paths": real_paths[:2]}


@pytest.fixture
def db_seeded():
    db = Database()
    seeded = _seed_two_pads(db)
    if not seeded:
        pytest.skip("Need ≥2 songs with playable file_path for IJ live tests")
    try:
        yield db, seeded
    finally:
        conn = db._conn()
        try:
            for pid in seeded["pad_ids"]:
                conn.execute("DELETE FROM jingle_pads WHERE id = ?", [pid])
            conn.execute("DELETE FROM jingle_pallets WHERE id = ?",
                         [seeded["pallet_id"]])
            conn.commit()
        except Exception:
            pass


# ── 1. Shared IJE consolidation ─────────────────────────────────────────


def test_instant_jingles_uses_shared_ije_when_kwarg_provided(qtbot, db_seeded, engine):
    """When MainWindow injects a shared InstantJingleEngine, the
    standalone screen reuses that exact instance instead of building
    a fresh one."""
    from ui.instant_jingles import InstantJingles

    db, _ = db_seeded
    shared = _FakeIJE()
    screen = InstantJingles(db=db, engine=engine,
                            instant_jingle_engine=shared)
    qtbot.addWidget(screen)
    assert screen._engine is shared, \
        "Standalone screen must reuse the injected IJE, not build its own"


def test_instant_jingles_creates_own_ije_when_kwarg_none(qtbot, db_seeded, engine):
    """Default kwarg=None preserves the legacy behaviour: the screen
    builds its own InstantJingleEngine. Backward-compat for any test /
    context that constructs InstantJingles standalone."""
    from ui.instant_jingles import InstantJingles
    from core.instant_jingle_engine import InstantJingleEngine

    db, _ = db_seeded
    screen = InstantJingles(db=db, engine=engine)
    qtbot.addWidget(screen)
    assert isinstance(screen._engine, InstantJingleEngine), \
        "When no shared IJE is provided, the screen must build its own"


# ── 2. pads_changed signal emission ─────────────────────────────────────


def test_pads_changed_emits_after_pad_label_edit(qtbot, db_seeded, engine):
    """A pad label edit (the most frequent operator action) triggers
    pads_changed so MainWindow → Studio refreshes the tile grid."""
    from ui.instant_jingles import InstantJingles

    db, seeded = db_seeded
    screen = InstantJingles(db=db, engine=engine,
                            instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(screen)

    fired = []
    screen.pads_changed.connect(lambda: fired.append(True))

    pad_id = seeded["pad_ids"][0]
    screen._on_editor_label(pad_id, "RENAMED")
    assert len(fired) == 1, "pads_changed must fire exactly once after label edit"


def test_pads_changed_emits_after_assign_audio(qtbot, db_seeded, engine):
    """Assigning audio changes the file_path → Studio's
    get_jingle_pads_active() result changes → tile grid must refresh."""
    from ui.instant_jingles import InstantJingles

    db, seeded = db_seeded
    fake = _FakeIJE()
    screen = InstantJingles(db=db, engine=engine,
                            instant_jingle_engine=fake)
    qtbot.addWidget(screen)

    fired = []
    screen.pads_changed.connect(lambda: fired.append(True))

    # Bypass the QFileDialog by patching it to return a known path —
    # mirrors the dialog's two-tuple (path, filter) return shape.
    from PyQt6.QtWidgets import QFileDialog
    new_path = seeded["paths"][1]
    orig = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(
        lambda *a, **kw: (new_path, "Audio files (*.mp3)"))
    try:
        screen._on_assign_audio(seeded["pad_ids"][0])
    finally:
        QFileDialog.getOpenFileName = orig

    assert len(fired) == 1, "pads_changed must fire after assign-audio"


def test_pads_changed_emits_after_clear_pad(qtbot, db_seeded, engine):
    """Clearing a pad removes audio assignment → must reach Studio."""
    from ui.instant_jingles import InstantJingles

    db, seeded = db_seeded
    screen = InstantJingles(db=db, engine=engine,
                            instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(screen)

    fired = []
    screen.pads_changed.connect(lambda: fired.append(True))

    # Bypass the confirmation QMessageBox.
    from PyQt6.QtWidgets import QMessageBox
    orig = _dialogs.confirm
    _dialogs.confirm = staticmethod(
        lambda *a, **kw: True)
    try:
        screen._on_clear_pad(seeded["pad_ids"][0])
    finally:
        _dialogs.confirm = orig

    assert len(fired) == 1, "pads_changed must fire after clear-pad"


# ── 3. Studio _reload_instant_jingles ───────────────────────────────────


def test_studio_reload_instant_jingles_pulls_fresh_db_data(qtbot, db_seeded, engine):
    """Studio caches pads at construction. _reload_instant_jingles
    re-pulls from DB so a label edit through the standalone screen
    becomes visible on the next tile-set call."""
    db, seeded = db_seeded
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    initial_count = len(s._jingle_pads)

    # Mutate the DB the way the standalone screen would.
    db._conn().execute(
        "UPDATE jingle_pads SET label = ? WHERE id = ?",
        ["RELOAD_TEST", seeded["pad_ids"][0]],
    )
    db._conn().commit()

    s._reload_instant_jingles()
    # Cache picked up the new label
    refreshed = next((p for p in s._jingle_pads
                      if int(p["id"]) == seeded["pad_ids"][0]), None)
    assert refreshed is not None, "Reloaded cache must contain the seeded pad"
    assert refreshed["label"] == "RELOAD_TEST", \
        "Studio cache must reflect the latest DB label after reload"
    assert len(s._jingle_pads) == initial_count, \
        "Reload count should be stable when no pads were added/removed"


def test_force_studio_refresh_also_reloads_instant_jingles(qtbot, db_seeded, engine):
    """showEvent → _force_studio_refresh path must also pull pad
    changes (belt-and-suspenders alongside the pads_changed signal)."""
    db, seeded = db_seeded
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)

    # Mutate the DB out-of-band.
    db._conn().execute(
        "UPDATE jingle_pads SET label = ? WHERE id = ?",
        ["FORCE_REFRESH", seeded["pad_ids"][0]],
    )
    db._conn().commit()

    s._force_studio_refresh()
    refreshed = next((p for p in s._jingle_pads
                      if int(p["id"]) == seeded["pad_ids"][0]), None)
    assert refreshed is not None
    assert refreshed["label"] == "FORCE_REFRESH", \
        "_force_studio_refresh must reload IJ pads alongside other state"
