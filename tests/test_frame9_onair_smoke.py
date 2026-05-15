"""
Frame 9 (Edit Playlist) — automated on-air smoke.

Replaces the manual click-through that would otherwise be required to
verify the Preview button + on-air confirm dialog wiring. These tests
exercise the same code paths a human would exercise:

  1. Off-air → preview fires immediately, no dialog
  2. On-air → dialog appears → Cancel blocks preview, engine never called
  3. On-air → dialog appears → OK plays preview on a NEW channel id
  4. Studio's on-air channel id is NEVER stopped/paused/cleaned during
     preview — Studio audio stays uninterrupted

The 4th case is the production-critical invariant the spec calls out:
"preview plays through cue/preview channel, Studio audio still on-air
uninterrupted." We verify that by asserting no stop/pause/cleanup call
ever lands on the Studio's channel id while preview is active.

Real audio is NOT exercised — we use a FakeEngine that records calls
so the wire shape can be asserted deterministically. The actual audio
routing on Kavish's hardware is verified by the manual smoke; this
file is the CI-runnable companion that catches wire regressions.
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from PyQt6.QtWidgets import QMessageBox

from core.database import Database
from core import dialogs as _dialogs
from ui.playlist_edit import PlaylistEdit


# ── Test doubles ────────────────────────────────────────────────────────


class _FakeEngine:
    """Records every call so we can assert wire-shape. Channel ids are
    monotonically increasing so we can prove Studio's channel id is
    distinct from a fresh preview channel id."""

    def __init__(self):
        self.calls: list[tuple] = []
        self._next_cid = 100

    @property
    def position_changed(self): return _NullSignal()
    @property
    def playback_ended(self):   return _NullSignal()
    @property
    def error_occurred(self):   return _NullSignal()

    def load_file(self, path: str) -> int:
        self._next_cid += 1
        self.calls.append(("load_file", path, self._next_cid))
        return self._next_cid

    def set_volume(self, cid: int, vol: int) -> None:
        self.calls.append(("set_volume", cid, vol))

    def play(self, cid: int) -> None:
        self.calls.append(("play", cid))

    def stop(self, cid: int) -> None:
        self.calls.append(("stop", cid))

    def pause(self, cid: int) -> None:
        self.calls.append(("pause", cid))

    def resume(self, cid: int) -> None:
        self.calls.append(("resume", cid))

    def cleanup(self, cid: int) -> None:
        self.calls.append(("cleanup", cid))

    def get_state(self, cid: int) -> str:
        return "playing"

    def get_duration_ms(self, cid: int) -> int:
        return 240_000

    def seek_to_ms(self, cid: int, ms: int) -> None:
        self.calls.append(("seek_to_ms", cid, ms))

    # ── Test helpers ─────────────────────────────────────────────────────

    def calls_against(self, channel_id: int) -> list[tuple]:
        """Every call whose first int arg matches the channel id."""
        out = []
        for c in self.calls:
            for i, v in enumerate(c[1:], start=1):
                if isinstance(v, int) and v == channel_id:
                    out.append(c); break
        return out

    def disruption_calls_for(self, channel_id: int) -> list[tuple]:
        """Calls that would interrupt audio on the given channel id —
        stop / pause / cleanup. load_file/play/set_volume/seek are NOT
        disruptions of an existing channel."""
        return [c for c in self.calls
                if c[0] in ("stop", "pause", "cleanup")
                and len(c) > 1 and c[1] == channel_id]


class _NullSignal:
    """No-op stand-in for engine signals during PlaylistEdit construction."""
    def connect(self, _slot): pass
    def disconnect(self, _slot=None): pass
    def emit(self, *_args): pass


class _StudioOnAir:
    """Stub matching the real Studio's `_current_track` / `_playback_cid`
    surface that PlaylistEdit reads. Mirrors how MainWindow injects the
    real Studio via ``set_studio()``."""

    def __init__(self, channel_id: int = 50):
        self._current_track = {"id": 1, "title": "Live Show",
                               "artist": "DJ"}
        self._playback_cid = int(channel_id)


class _StudioOffAir:
    """Stub for a Studio that's NOT on air — _current_track is None."""

    def __init__(self):
        self._current_track = None
        self._playback_cid = None


# ── Live-DB fixture (cleanup-disciplined, reuses Frame 9 prefix) ────────


class _SmokeEnv:
    def __init__(self, db: Database):
        self.db = db
        self.created_playlist_ids: list[int] = []
        rows = db._conn().execute(
            "SELECT id FROM songs WHERE is_enabled=1 "
            "AND file_path IS NOT NULL AND file_path != '' "
            "ORDER BY id LIMIT 5"
        ).fetchall()
        self.real_song_ids: list[int] = [int(r[0]) for r in rows]

    def make_playlist_with_track(self) -> int:
        prefix = f"_test_frame9smoke_{uuid.uuid4().hex[:8]}"
        pid = int(self.db.create_playlist_draft(name=f"{prefix}_pl",
                                                kind="manual"))
        self.db.commit_playlist_draft(pid)
        self.created_playlist_ids.append(pid)
        if self.real_song_ids:
            self.db.replace_playlist_songs(pid, self.real_song_ids[:1])
        return pid

    def cleanup(self) -> None:
        conn = self.db._conn()
        for pid in self.created_playlist_ids:
            try:
                conn.execute(
                    "DELETE FROM playlist_songs WHERE playlist_id = ?", [pid])
                conn.execute(
                    "DELETE FROM playlists WHERE id = ?", [pid])
                conn.commit()
            except Exception:
                pass


@pytest.fixture
def env():
    db = Database()
    e = _SmokeEnv(db)
    if not e.real_song_ids:
        pytest.skip("No enabled songs with file_path in live DB")
    try:
        yield e
    finally:
        e.cleanup()


@pytest.fixture
def screen(qtbot, env):
    """Helper to build a PlaylistEdit primed on a fresh playlist with one
    real DB-backed track. Studio is not yet wired — caller does so."""
    eng = _FakeEngine()
    s = PlaylistEdit(db=env.db, engine=eng, studio=None)
    qtbot.addWidget(s)
    pid = env.make_playlist_with_track()
    s.load_for_id(pid)
    s._table_card.table().setCurrentIndex(s._model.index(0, 0))
    yield s, eng, env


# ── Case 1 — off-air: preview fires directly, no dialog ────────────────


def test_preview_offair_plays_directly(screen, monkeypatch):
    s, eng, _env = screen
    s.set_studio(_StudioOffAir())
    # If a confirm dialog were to fire it'd block — track that.
    dialog_fired = []
    monkeypatch.setattr(
        _dialogs, "confirm",
        lambda *a, **k: (dialog_fired.append(True), False)[1])
    s._on_preview_track()
    method_calls = [c[0] for c in eng.calls]
    assert "load_file" in method_calls, \
        "off-air preview must call engine.load_file"
    assert "play" in method_calls, "off-air preview must call engine.play"
    assert dialog_fired == [], \
        "off-air preview must NOT fire the on-air confirm dialog"


# ── Case 2 — on-air + Cancel: dialog appears, engine never called ──────


def test_preview_onair_cancel_blocks_preview(screen, monkeypatch):
    s, eng, _env = screen
    s.set_studio(_StudioOnAir())
    dialog_fired = []
    def _confirm_cancel(*a, **k):
        dialog_fired.append(True)
        return False
    monkeypatch.setattr(_dialogs, "confirm", _confirm_cancel)
    calls_before = list(eng.calls)
    s._on_preview_track()
    assert dialog_fired, \
        "on-air preview MUST show the confirm dialog"
    assert eng.calls == calls_before, \
        "Cancel on the on-air dialog must produce ZERO new engine calls; " \
        f"got: {eng.calls[len(calls_before):]}"


# ── Case 3 — on-air + OK: preview plays on a NEW channel id ────────────


def test_preview_onair_ok_plays_through_cue(screen, monkeypatch):
    s, eng, _env = screen
    studio = _StudioOnAir(channel_id=50)
    s.set_studio(studio)
    monkeypatch.setattr(_dialogs, "confirm",
                        lambda *a, **k: True)
    s._on_preview_track()
    load_calls = [c for c in eng.calls if c[0] == "load_file"]
    assert load_calls, "on-air OK must call engine.load_file"
    # The cid the engine returned for the preview channel
    preview_cid = load_calls[0][2]
    assert preview_cid != studio._playback_cid, (
        f"preview cid ({preview_cid}) MUST differ from Studio's on-air "
        f"cid ({studio._playback_cid}) — preview rides its own channel")
    assert s._preview_cid == preview_cid, \
        "PlaylistEdit must remember the preview cid for transport-bar wiring"


# ── Case 4 — Studio on-air audio uninterrupted during preview ──────────


def test_studio_onair_audio_uninterrupted_during_preview(
        screen, monkeypatch):
    """The production-critical invariant: while preview is active,
    Studio's playback channel must NOT receive stop / pause / cleanup.
    Preview rides on a separate channel id; the engine's master mixer
    short-circuits them per Phase A's multi-channel contract."""
    s, eng, _env = screen
    studio = _StudioOnAir(channel_id=50)
    s.set_studio(studio)
    monkeypatch.setattr(_dialogs, "confirm",
                        lambda *a, **k: True)
    s._on_preview_track()
    disruptions = eng.disruption_calls_for(studio._playback_cid)
    assert disruptions == [], (
        f"Studio's on-air channel id={studio._playback_cid} received "
        f"disruption calls during preview: {disruptions}")
    # Sanity: preview did happen on a different cid
    assert s._preview_cid is not None
    assert s._preview_cid != studio._playback_cid


# ── Bonus regression — clearing prior preview before new one ───────────


def test_second_preview_cleans_up_first(screen, monkeypatch):
    """Two previews in a row: the first preview's cid must be cleaned
    up before the second loads. Prevents channel leaks across rapid
    clicks."""
    s, eng, _env = screen
    s.set_studio(_StudioOffAir())
    monkeypatch.setattr(_dialogs, "confirm",
                        lambda *a, **k: True)
    s._on_preview_track()
    first_cid = s._preview_cid
    s._on_preview_track()
    second_cid = s._preview_cid
    assert first_cid is not None and second_cid is not None
    assert second_cid != first_cid
    # The first cid must have been cleaned up
    cleanup_calls = [c for c in eng.calls
                     if c[0] == "cleanup" and c[1] == first_cid]
    assert cleanup_calls, \
        f"first preview cid={first_cid} must be cleaned before second"
