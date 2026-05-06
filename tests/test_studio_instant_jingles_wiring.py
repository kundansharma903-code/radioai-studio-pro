"""
Studio v3 — Instant Jingles wiring tests (Phase A).

Studio's Instant Jingles panel was visual-only until Phase A. This
file verifies the wire shape with a `_FakeIJE` mock so the engine
contract can be asserted deterministically — no real audio routed.

Coverage:
  1. Tile click invokes engine.play_pad with the correct pad_id +
     file_path + volume + loop derived from the DB pad row.
  2. Hotkeys 1-5 trigger tiles 0-4 through the same dispatcher.
  3. Esc invokes engine.stop_all (emergency dump).
  4. pad_started signal lights up the DEMO display + spins up the
     10Hz countdown timer.
  5. pad_ended signal clears the DEMO display + stops the timer.
  6. Edit Bank link click emits breadcrumb_clicked('instant_jingles').
  7. Studio constructed without an IJE doesn't crash on tile click —
     decorative fallback path (existing 9 EOS / item-dispatch tests
     already construct Studio without IJE; this one asserts the
     no-crash contract explicitly).

Pattern mirrors tests/test_frame9_onair_smoke.py:_FakeEngine — record
calls, expose pyqtSignal-shaped attributes the production code can
.connect() to.
"""

from __future__ import annotations

import os
from typing import Optional

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtCore import QPoint, QEvent, QPointF

from core.database import Database
from ui.studio import Studio


# ── Test doubles ────────────────────────────────────────────────────────


class _RecordingSignal:
    """Stand-in for a pyqtSignal that records every connect target so
    tests can fire it manually via emit(...). Mirrors the connect/emit
    surface the production code uses."""

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
    """Fake InstantJingleEngine — records every play_pad / stop_pad /
    stop_all call, exposes pad_started/ended/stopped signals."""

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


# ── Fixtures ────────────────────────────────────────────────────────────


def _seed_three_pads(db: Database) -> list[dict]:
    """Insert (or upsert) 3 well-formed jingle_pads rows in a dedicated
    test pallet, each pointing to a real on-disk audio file lifted from
    the songs table. The DEMO countdown + tile binding tests rely on
    `os.path.exists(file_path)` returning True so the dispatcher
    keeps the row.

    Cleanup is the caller's responsibility — yield via a fixture that
    deletes the inserted rows in a `finally`."""
    conn = db._conn()
    rows = conn.execute(
        "SELECT file_path FROM songs WHERE file_path IS NOT NULL "
        "AND file_path != '' ORDER BY id LIMIT 5"
    ).fetchall()
    real_paths = [r[0] for r in rows if r[0] and os.path.exists(r[0])]
    if len(real_paths) < 3:
        return []

    # Use a uniquely-named test pallet to avoid collisions with real
    # KISS FM data. The pallet itself is also cleaned up.
    import uuid as _uuid
    pallet_name = f"_test_studio_ije_{_uuid.uuid4().hex[:8]}"
    cur = conn.execute(
        "INSERT INTO jingle_pallets (name, owner, grid_cols, grid_rows, "
        "audio_output, display_order) VALUES (?, '', 5, 6, 3, 9999)",
        [pallet_name],
    )
    pallet_id = int(cur.lastrowid)

    inserted_ids: list[int] = []
    pad_dicts: list[dict] = []
    for i, path in enumerate(real_paths[:3]):
        cur = conn.execute(
            "INSERT INTO jingle_pads (pallet_id, pad_index, label, "
            "file_path, duration_ms, color, volume, behaviour) "
            "VALUES (?, ?, ?, ?, ?, '#F59E0B', ?, ?)",
            [pallet_id, i, f"TEST PAD {i}", path,
             5000 + i * 1000, 80 + i * 5,
             "loop" if i == 1 else "play_once"],
        )
        pad_id = int(cur.lastrowid)
        inserted_ids.append(pad_id)
        pad_dicts.append({
            "id":          pad_id,
            "label":       f"TEST PAD {i}",
            "file_path":   path,
            "duration_ms": 5000 + i * 1000,
            "volume":      80 + i * 5,
            "behaviour":   "loop" if i == 1 else "play_once",
        })
    conn.commit()
    return [{"_pallet_id": pallet_id,
             "_pad_ids":   inserted_ids,
             "_pads":      pad_dicts}]


@pytest.fixture
def db_with_pads():
    """Live-DB fixture — inserts 3 jingle_pads pointing at real audio
    files, yields (db, [pad dicts]), cleans up on teardown.

    Test-cleanup discipline matches AutoSchedule / ClockEditor pattern:
    unique pallet prefix + try/finally."""
    db = Database()
    seeded = _seed_three_pads(db)
    if not seeded:
        pytest.skip("Need ≥3 songs with playable file_path for IJE tests")
    state = seeded[0]
    try:
        yield db, state["_pads"]
    finally:
        conn = db._conn()
        try:
            for pid in state["_pad_ids"]:
                conn.execute("DELETE FROM jingle_pads WHERE id = ?", [pid])
            conn.execute("DELETE FROM jingle_pallets WHERE id = ?",
                         [state["_pallet_id"]])
            conn.commit()
        except Exception:
            pass


@pytest.fixture
def studio_wired(qtbot, db_with_pads, engine):
    """Studio constructed with the shared AudioEngine + a fresh
    `_FakeIJE`. Returns (studio, ije, pads)."""
    db, pads = db_with_pads
    ije = _FakeIJE()
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=ije)
    qtbot.addWidget(s)
    yield s, ije, pads
    if s._playback_cid is not None:
        try:
            engine.cleanup(s._playback_cid)
        except Exception:
            pass


# ── Helpers ─────────────────────────────────────────────────────────────


def _first_pad_index_in_studio(studio: Studio, target_pad_id: int) -> int:
    """Find which tile index the seeded pad ended up at. Studio's
    _load_jingle_pads_from_db filters by file_path existence, so the
    seeded pads may not appear at indices 0/1/2 if the DB has other
    active pads. We anchor on pad_id."""
    for i, p in enumerate(studio._jingle_pads):
        if int(p["id"]) == int(target_pad_id):
            return i
    return -1


# ── Tests ───────────────────────────────────────────────────────────────


def test_jingle_tile_click_calls_engine_play_pad_with_correct_args(studio_wired):
    """Tile click → engine.play_pad(pad_id, file_path, volume, loop)
    derived from the DB row. We seed pads 0/1/2; pad index 1 has
    behaviour='loop' so loop should propagate."""
    studio, ije, pads = studio_wired
    target_pad = pads[1]   # the loop-enabled one
    tile_idx = _first_pad_index_in_studio(studio, target_pad["id"])
    if tile_idx < 0:
        pytest.skip("Seeded pad not in Studio's loaded set "
                    "(other active pads in live DB)")

    # Drive the panel signal directly — equivalent to a tile click but
    # bypasses the QPainter hit-test geometry.
    studio._instant_jingles.tile_clicked.emit(tile_idx)

    play_calls = [c for c in ije.calls if c[0] == "play_pad"]
    assert len(play_calls) == 1
    op, pid, fp, vol, loop = play_calls[0]
    assert pid == int(target_pad["id"])
    assert fp == target_pad["file_path"]
    assert vol == int(target_pad["volume"])
    assert loop is True   # behaviour == 'loop'


def test_hotkey_1_through_5_triggers_corresponding_tile_handler(studio_wired):
    """Hotkey N (1..5) → tile index N-1. We assert the dispatch maps
    correctly for each key by hooking _play_jingle_at_index and
    confirming it sees the expected indices."""
    studio, _ije, _pads = studio_wired
    seen_indices: list[int] = []
    studio._play_jingle_at_index = (   # monkey-patch the dispatcher
        lambda idx: seen_indices.append(idx))

    for n in (1, 2, 3, 4, 5):
        studio._on_jingle_hotkey_clicked(n)

    assert seen_indices == [0, 1, 2, 3, 4]


def test_esc_calls_engine_stop_all(studio_wired):
    """Esc-for-stop-all is the broadcast emergency-dump path."""
    studio, ije, _pads = studio_wired
    studio._on_jingle_stop_all()
    assert ("stop_all",) in ije.calls


def test_demo_display_updates_on_pad_started_signal(qtbot, studio_wired):
    """When the engine reports pad_started, the panel's DEMO display
    becomes active with the pad's label + total duration, and the
    countdown timer spins up."""
    studio, ije, pads = studio_wired
    # Pick a pad that's actually loaded into Studio (live DB may have
    # other active pads ahead of our seeded ones).
    if not studio._jingle_pads:
        pytest.skip("No jingle pads loaded in this DB")
    pad = studio._jingle_pads[0]

    ije.pad_started.emit(int(pad["id"]))

    panel = studio._instant_jingles
    assert panel._demo_active is True
    assert panel._demo_label == pad["label"]
    assert panel._demo_remaining_s == pytest.approx(
        (pad["duration_ms"] or 0) / 1000.0, abs=0.05)
    assert studio._jingle_demo_timer is not None
    assert studio._jingle_demo_timer.isActive() is True

    # Tick the countdown one slice (10Hz) — remaining should decrease
    qtbot.wait(150)
    assert panel._demo_remaining_s < (pad["duration_ms"] or 0) / 1000.0


def test_demo_display_clears_on_pad_ended_signal(qtbot, studio_wired):
    """pad_ended → DEMO clears + countdown timer stops."""
    studio, ije, _pads = studio_wired
    if not studio._jingle_pads:
        pytest.skip("No jingle pads loaded in this DB")
    pad = studio._jingle_pads[0]

    ije.pad_started.emit(int(pad["id"]))
    qtbot.wait(50)
    assert studio._instant_jingles._demo_active is True

    ije.pad_ended.emit(int(pad["id"]))
    qtbot.wait(50)

    panel = studio._instant_jingles
    assert panel._demo_active is False
    assert panel._demo_label == ""
    assert panel._demo_remaining_s == 0.0
    assert studio._jingle_demo_timer is not None
    assert studio._jingle_demo_timer.isActive() is False


def test_edit_bank_link_emits_breadcrumb_clicked(qtbot, studio_wired):
    """Edit Bank link routes to the standalone Instant Jingles screen
    via the existing 'instant_jingles' breadcrumb route registered at
    ui/main_window.py:261."""
    studio, _ije, _pads = studio_wired
    captured: list[str] = []
    studio.breadcrumb_clicked.connect(captured.append)

    studio._instant_jingles.edit_bank_clicked.emit()

    assert "instant_jingles" in captured


def test_studio_constructed_without_ije_does_not_crash(qtbot):
    """Decorative fallback — if Studio is built with
    instant_jingle_engine=None (existing tests do this), tile clicks
    + hotkeys + Esc must all be no-ops, not raise."""
    db = Database()
    s = Studio(db=db, engine=None, scheduler=None,
               instant_jingle_engine=None)
    qtbot.addWidget(s)

    # Tile click via panel signal — must not raise even when engine is None
    s._instant_jingles.tile_clicked.emit(0)
    s._on_jingle_hotkey_clicked(1)
    s._on_jingle_stop_all()
    # And the dispatcher itself when called with an out-of-range index
    s._play_jingle_at_index(99)

    # Edit Bank link is engine-independent — should still emit the breadcrumb.
    captured: list[str] = []
    s.breadcrumb_clicked.connect(captured.append)
    s._instant_jingles.edit_bank_clicked.emit()
    assert "instant_jingles" in captured
