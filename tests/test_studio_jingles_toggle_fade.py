"""
Studio v3 — Instant Jingles toggle-fade behaviour.

Operator workflow: clicking a jingle tile that's already playing
fades the jingle out gracefully instead of cutting hard. This file
verifies:

  1. First click on an idle pad → engine.play_pad(...) (existing path).
  2. Re-click on the SAME pad while it's playing →
     engine.fade_stop_pad(pad_id, fade_ms=Studio.JINGLE_FADE_MS) and
     NOT a second play_pad.
  3. Hotkey re-press follows the same toggle.
  4. fade_stop_pad failure is non-fatal (engine.play_pad still
     attempted? — no, fade-stop is the click's intent, swallow + log).
  5. InstantJingleEngine.fade_stop_pad immediately removes pad_id
     from the active map (so is_playing is False right after) and
     emits pad_stopped after the QTimer.singleShot fires.
  6. fade_ms <= 0 falls through to instant stop_pad path.
  7. fade_stop_pad on a not-playing pad is a no-op (returns False).

Mocks: ``_FakeIJE`` extends the wiring-test fake with ``is_playing``
+ ``fade_stop_pad`` so the toggle path can be asserted without a real
audio engine.
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
    """Adds is_playing + fade_stop_pad on top of the wiring fake.

    Default ``is_playing`` returns False; tests flip the playing set
    explicitly to simulate "pad is currently playing"."""

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


# ── Fixtures ────────────────────────────────────────────────────────────


def _seed_pad_with_audio(db: Database) -> tuple[int, int, str] | None:
    """Insert one well-formed jingle_pads row pointing at a real
    on-disk file. Returns (pallet_id, pad_id, file_path) or None
    if the songs table lacks playable rows."""
    row = db._conn().execute(
        "SELECT file_path FROM songs WHERE file_path IS NOT NULL "
        "AND file_path != '' ORDER BY id LIMIT 1"
    ).fetchone()
    if not row or not row[0] or not os.path.exists(row[0]):
        return None
    pallet_name = f"_test_jingles_toggle_{uuid.uuid4().hex[:8]}"
    cur = db._conn().execute(
        "INSERT INTO jingle_pallets (name, owner, grid_cols, grid_rows, "
        "audio_output, display_order) VALUES (?, '', 5, 6, 3, 9999)",
        [pallet_name],
    )
    pallet_id = int(cur.lastrowid)
    cur = db._conn().execute(
        "INSERT INTO jingle_pads (pallet_id, pad_index, label, file_path, "
        "duration_ms, color, volume, behaviour) "
        "VALUES (?, 0, 'TOGGLE PAD', ?, 5000, '#3b82f6', 90, 'play_once')",
        [pallet_id, row[0]],
    )
    db._conn().commit()
    return pallet_id, int(cur.lastrowid), row[0]


@pytest.fixture
def studio_with_pad(qtbot, engine):
    db = Database()
    seeded = _seed_pad_with_audio(db)
    if seeded is None:
        pytest.skip("Need a song with playable file_path for toggle-fade tests")
    pallet_id, pad_id, file_path = seeded
    ije = _FakeIJE()
    s = Studio(db=db, engine=engine, scheduler=None,
               instant_jingle_engine=ije)
    qtbot.addWidget(s)
    # Resolve the tile index Studio assigned to our seeded pad.
    tile_idx = next((i for i, p in enumerate(s._jingle_pads)
                     if int(p["id"]) == pad_id), -1)
    if tile_idx < 0:
        pytest.skip("Seeded pad not in Studio's loaded set")
    try:
        yield s, ije, pad_id, tile_idx
    finally:
        try:
            db._conn().execute(
                "DELETE FROM jingle_pads WHERE id = ?", [pad_id])
            db._conn().execute(
                "DELETE FROM jingle_pallets WHERE id = ?", [pallet_id])
            db._conn().commit()
        except Exception:
            pass


# ── Tests — Studio toggle behaviour ─────────────────────────────────────


def test_first_click_on_idle_pad_calls_play_pad(studio_with_pad):
    """Idle tile → engine.play_pad with the pad's DB-driven args."""
    s, ije, pad_id, tile_idx = studio_with_pad
    s._on_jingle_tile_clicked(tile_idx)
    play_calls = [c for c in ije.calls if c[0] == "play_pad"]
    assert len(play_calls) == 1
    assert play_calls[0][1] == pad_id
    fade_calls = [c for c in ije.calls if c[0] == "fade_stop_pad"]
    assert fade_calls == [], "First click on idle must NOT fade-stop"


def test_reclick_on_playing_pad_calls_fade_stop_pad(studio_with_pad):
    """Re-click on the SAME tile while playing → fade_stop_pad with
    Studio.JINGLE_FADE_MS, NOT a second play_pad."""
    s, ije, pad_id, tile_idx = studio_with_pad
    # First click — pad starts playing (fake updates _playing set).
    s._on_jingle_tile_clicked(tile_idx)
    assert ije.is_playing(pad_id)
    # Second click — should fade-stop, no second play_pad.
    s._on_jingle_tile_clicked(tile_idx)
    fade_calls = [c for c in ije.calls if c[0] == "fade_stop_pad"]
    assert len(fade_calls) == 1
    assert fade_calls[0][1] == pad_id
    assert fade_calls[0][2] == Studio.JINGLE_FADE_MS
    play_calls = [c for c in ije.calls if c[0] == "play_pad"]
    assert len(play_calls) == 1, \
        "Second click while playing must NOT trigger another play_pad"


def test_third_click_after_fade_stops_starts_fresh_play(studio_with_pad):
    """fade_stop_pad pops the pad from _playing immediately. The
    third click sees is_playing=False → fresh play_pad. Mirrors the
    operator workflow: tap, tap (fade), tap (re-trigger / crossfade)."""
    s, ije, pad_id, tile_idx = studio_with_pad
    s._on_jingle_tile_clicked(tile_idx)   # play
    s._on_jingle_tile_clicked(tile_idx)   # fade-stop
    assert not ije.is_playing(pad_id), \
        "fade_stop_pad fake must clear is_playing immediately"
    s._on_jingle_tile_clicked(tile_idx)   # play again
    play_calls = [c for c in ije.calls if c[0] == "play_pad"]
    assert len(play_calls) == 2


def test_hotkey_repress_also_toggles(studio_with_pad):
    """Hotkey 1 maps to tile index 0; the dispatcher is the same
    so the toggle semantic must hold for hotkeys too."""
    s, ije, pad_id, tile_idx = studio_with_pad
    if tile_idx >= 5:
        pytest.skip("Hotkey 1-5 maps to tiles 0-4 only")
    hotkey_n = tile_idx + 1
    s._on_jingle_hotkey_clicked(hotkey_n)
    s._on_jingle_hotkey_clicked(hotkey_n)
    play_calls = [c for c in ije.calls if c[0] == "play_pad"]
    fade_calls = [c for c in ije.calls if c[0] == "fade_stop_pad"]
    assert len(play_calls) == 1
    assert len(fade_calls) == 1


def test_fade_stop_pad_failure_is_non_fatal(studio_with_pad):
    """If engine.fade_stop_pad raises, Studio swallows the exception
    and keeps the deck stable — the click intent was a fade-out;
    don't escalate to a hard play."""
    s, ije, pad_id, tile_idx = studio_with_pad
    s._on_jingle_tile_clicked(tile_idx)   # plays once
    def _broken(*a, **kw): raise RuntimeError("boom")
    ije.fade_stop_pad = _broken
    # Must NOT crash the click handler.
    s._on_jingle_tile_clicked(tile_idx)


# ── Tests — InstantJingleEngine fade_stop_pad ──────────────────────────


def test_ije_fade_stop_pad_pops_from_active_map_immediately():
    """fade_stop_pad must remove the pad from _pads before scheduling
    the cleanup so is_playing returns False and a re-click can spin
    up a fresh channel for the broadcast crossfade."""
    from core.instant_jingle_engine import InstantJingleEngine

    class _StubEngine:
        def __init__(self): self.fade_calls = []
        def fade_volume_to(self, cid, target, ms):
            self.fade_calls.append((cid, target, ms))
        def playback_ended(self): pass

    stub = _StubEngine()
    # Bypass the normal __init__-time signal connect; we don't need it.
    ije = InstantJingleEngine.__new__(InstantJingleEngine)
    from PyQt6.QtCore import QObject
    QObject.__init__(ije)
    ije._engine = stub
    ije._pads = {42: 7}
    import threading as _t
    ije._lock = _t.Lock()

    fired_stopped: list[int] = []
    ije.pad_stopped = type("S", (), {"emit": lambda self, x: fired_stopped.append(int(x))})()

    assert ije.is_playing(42) is True
    ok = ije.fade_stop_pad(42, fade_ms=200)
    assert ok is True
    assert ije.is_playing(42) is False, "Pad must leave _pads immediately"
    assert stub.fade_calls == [(7, 0, 200)], \
        "fade_volume_to must be called with target=0 and the fade duration"


def test_ije_fade_stop_pad_zero_falls_through_to_instant_stop():
    """fade_ms <= 0 → behaves identically to stop_pad (no QTimer,
    immediate cleanup)."""
    from core.instant_jingle_engine import InstantJingleEngine

    class _StubEngine:
        def fade_volume_to(self, *a, **kw):
            raise AssertionError("must NOT slide when fade_ms <= 0")
        def playback_ended(self): pass

    stub = _StubEngine()
    ije = InstantJingleEngine.__new__(InstantJingleEngine)
    from PyQt6.QtCore import QObject
    QObject.__init__(ije)
    ije._engine = stub
    ije._pads = {7: 3}
    import threading as _t
    ije._lock = _t.Lock()

    cleaned: list[int] = []
    ije._cleanup_silently = lambda cid: cleaned.append(int(cid))
    ije.pad_stopped = type("S", (), {"emit": lambda self, x: None})()

    assert ije.fade_stop_pad(7, fade_ms=0) is True
    assert cleaned == [3], "Zero fade_ms must reach the instant cleanup path"


def test_ije_fade_stop_pad_on_idle_pad_returns_false():
    """No-op when the pad isn't in the active map."""
    from core.instant_jingle_engine import InstantJingleEngine

    class _StubEngine:
        def fade_volume_to(self, *a, **kw): pass
        def playback_ended(self): pass

    ije = InstantJingleEngine.__new__(InstantJingleEngine)
    from PyQt6.QtCore import QObject
    QObject.__init__(ije)
    ije._engine = _StubEngine()
    ije._pads = {}
    import threading as _t
    ije._lock = _t.Lock()
    ije.pad_stopped = type("S", (), {"emit": lambda self, x: None})()

    assert ije.fade_stop_pad(99, fade_ms=1000) is False
