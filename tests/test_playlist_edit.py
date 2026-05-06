"""
Edit Playlist (Figma 248:2 — Frame 9) — load, save, queue CRUD,
preview wiring, on-air protection.

Live-DB tests with strict cleanup discipline:
  - Every test-created playlist prefixed ``_test_playlistedit_<uuid8>``
    (distinct from Frame 8's ``_test_playlist_<uuid8>`` to avoid
    parallel-run collision)
  - try/finally cleanup deletes auto_schedule references, song-list
    rows, and playlists rows in order
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtWidgets import QMessageBox

from core.database import Database
from ui.playlist_edit import (
    PlaylistEdit, _QueueModel, _ToolbarButton, _ActionStack,
    _PlaylistTableCard, _FilterPanel,
    ELEMENT_TYPES, FUNCTIONAL_TYPES,
)


# ── Fixtures ────────────────────────────────────────────────────────────


class _PEditEnv:
    """Tracks created playlist ids for cleanup."""

    def __init__(self, db: Database):
        self.db = db
        self.created_playlist_ids: list[int] = []
        # Cache a couple of real song ids we can reference in tests
        rows = db._conn().execute(
            "SELECT id FROM songs WHERE is_enabled=1 "
            "AND file_path IS NOT NULL AND file_path != '' "
            "ORDER BY id LIMIT 5"
        ).fetchall()
        self.real_song_ids: list[int] = [int(r[0]) for r in rows]

    def make_playlist(self, suffix: str = "pl") -> int:
        prefix = f"_test_playlistedit_{uuid.uuid4().hex[:8]}"
        pid = int(self.db.create_playlist_draft(
            name=f"{prefix}_{suffix}", kind="manual"))
        # Promote to active so it acts like a real playlist
        self.db.commit_playlist_draft(pid)
        self.created_playlist_ids.append(pid)
        return pid

    def seed_tracks(self, playlist_id: int, count: int = 3) -> list[int]:
        ids = self.real_song_ids[:count]
        if len(ids) < count:
            ids = ids + ids   # duplicate if DB short on songs
            ids = ids[:count]
        self.db.replace_playlist_songs(int(playlist_id), ids)
        return list(ids)

    def cleanup(self) -> None:
        conn = self.db._conn()
        for pid in list(self.created_playlist_ids):
            try:
                conn.execute(
                    "DELETE FROM playlist_songs WHERE playlist_id = ?",
                    [int(pid)])
                conn.execute(
                    "DELETE FROM playlists WHERE id = ?", [int(pid)])
                conn.commit()
            except Exception:
                pass


@pytest.fixture
def pe_env():
    db = Database()
    env = _PEditEnv(db)
    if not env.real_song_ids:
        pytest.skip("No enabled songs in live DB — cannot exercise edit flow")
    try:
        yield env
    finally:
        env.cleanup()


class _FakeEngine:
    """Tiny stand-in for AudioEngine that records calls. No BASS, no
    real channels — sufficient for asserting wiring."""

    def __init__(self):
        from PyQt6.QtCore import QObject, pyqtSignal
        self.calls: list[tuple] = []
        self._next_cid = 100

    # Signals (tests don't connect to them but the screen subscribes)
    @property
    def position_changed(self):
        return _NullSignal()

    @property
    def playback_ended(self):
        return _NullSignal()

    @property
    def error_occurred(self):
        return _NullSignal()

    def load_file(self, path: str) -> int:
        self._next_cid += 1
        self.calls.append(("load_file", path))
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


class _NullSignal:
    """Stub for engine signals — connect() is a no-op."""
    def connect(self, _slot): pass
    def disconnect(self, _slot=None): pass
    def emit(self, *_args): pass


@pytest.fixture
def screen(qtbot, pe_env):
    eng = _FakeEngine()
    s = PlaylistEdit(db=pe_env.db, scheduler=None, engine=eng, studio=None)
    qtbot.addWidget(s)
    s.show()
    yield s, pe_env, eng
    s.hide()


# ── Smoke + constructor wiring ──────────────────────────────────────────


def test_screen_mounts(qtbot, pe_env):
    s = PlaylistEdit(db=pe_env.db, scheduler=None, engine=None)
    qtbot.addWidget(s)
    assert s.width() == 1440
    assert s.height() == 900
    assert s._engine is None
    assert s._toolbar is not None
    assert s._table_card is not None
    assert s._filter is not None
    assert s._analyze is not None
    assert s._bottom is not None


def test_constructor_stores_engine(qtbot, pe_env):
    eng = _FakeEngine()
    s = PlaylistEdit(db=pe_env.db, engine=eng)
    qtbot.addWidget(s)
    assert s._engine is eng


# ── Load / model ────────────────────────────────────────────────────────


def test_load_for_id_populates_meta_and_queue(screen):
    s, env, _ = screen
    pid = env.make_playlist("loadme")
    seeded = env.seed_tracks(pid, count=3)
    s.load_for_id(pid)
    assert s._playlist_id == pid
    assert s._meta.get("name", "").startswith("_test_playlistedit_")
    assert s._model.rowCount() == 3
    # Queue order matches DB-seeded order
    assert s._model.song_ids() == seeded
    assert s._dirty is False


def test_load_for_unknown_id_routes_back(qtbot, pe_env):
    """An invalid id pops a dialog + emits 'playlists' route. Stub the
    QMessageBox so it doesn't actually block the test."""
    eng = _FakeEngine()
    s = PlaylistEdit(db=pe_env.db, engine=eng)
    qtbot.addWidget(s)
    # Replace QMessageBox.warning with a no-op so we don't block
    import PyQt6.QtWidgets as qw
    orig = qw.QMessageBox.warning
    qw.QMessageBox.warning = staticmethod(
        lambda *a, **kw: qw.QMessageBox.StandardButton.Ok)
    routes: list[str] = []
    s.screen_requested.connect(routes.append)
    try:
        # An id that almost certainly doesn't exist
        s.load_for_id(999_999_999)
    finally:
        qw.QMessageBox.warning = orig
    assert "playlists" in routes


# ── Queue CRUD ──────────────────────────────────────────────────────────


def test_add_appends_to_queue(screen):
    s, env, _ = screen
    pid = env.make_playlist("add"); env.seed_tracks(pid, count=2)
    s.load_for_id(pid)
    n_before = s._model.rowCount()
    s._on_add()
    # Filter resolves to ANY song by default (no constraints) — at least
    # one song in the 14k library, so add should succeed
    assert s._model.rowCount() == n_before + 1
    assert s._dirty is True


def test_insert_at_selected_row(screen):
    s, env, _ = screen
    pid = env.make_playlist("ins"); env.seed_tracks(pid, count=3)
    s.load_for_id(pid)
    # Select row 1 (middle)
    s._table_card.table().setCurrentIndex(s._model.index(1, 0))
    n_before = s._model.rowCount()
    s._on_insert()
    assert s._model.rowCount() == n_before + 1


def test_replace_at_selected_row(screen):
    s, env, _ = screen
    pid = env.make_playlist("rep"); env.seed_tracks(pid, count=2)
    s.load_for_id(pid)
    s._table_card.table().setCurrentIndex(s._model.index(0, 0))
    orig_len = s._model.rowCount()
    s._on_replace()
    # Replace must NOT change count
    assert s._model.rowCount() == orig_len


def test_delete_removes_selected_row(screen):
    s, env, _ = screen
    pid = env.make_playlist("del"); env.seed_tracks(pid, count=3)
    s.load_for_id(pid)
    s._table_card.table().setCurrentIndex(s._model.index(0, 0))
    s._on_delete()
    assert s._model.rowCount() == 2


def test_drag_reorder_via_moveRows(screen):
    """Move row 0 to position 2 — model.moveRows should pop and reinsert."""
    s, env, _ = screen
    pid = env.make_playlist("move"); env.seed_tracks(pid, count=3)
    s.load_for_id(pid)
    ids_before = s._model.song_ids()
    ok = s._model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 3)
    assert ok is True
    ids_after = s._model.song_ids()
    # Element that was at index 0 should now be at index 2
    assert ids_after[2] == ids_before[0]


# ── Save / round-trip ───────────────────────────────────────────────────


def test_save_round_trip_unchanged(screen):
    """Load → no edits → save → DB diff is zero."""
    s, env, _ = screen
    pid = env.make_playlist("rt"); seeded = env.seed_tracks(pid, count=3)
    s.load_for_id(pid)
    ok = s._save()
    assert ok is True
    after_rows = list(env.db.get_playlist_songs(pid))
    after_ids = [int(r["id"]) for r in after_rows]
    assert after_ids == seeded


def test_save_with_edits_persists(screen):
    s, env, _ = screen
    pid = env.make_playlist("edit"); env.seed_tracks(pid, count=2)
    s.load_for_id(pid)
    s._on_delete_via_index = None    # placeholder
    # Mutate: delete row 0
    s._table_card.table().setCurrentIndex(s._model.index(0, 0))
    s._on_delete()
    ok = s._save()
    assert ok is True
    after = list(env.db.get_playlist_songs(pid))
    assert len(after) == 1


def test_save_validation_blocks_empty_queue(screen, qtbot, monkeypatch):
    """Empty queue → save should warn + abort. Stub QMessageBox.warning
    so it's non-blocking."""
    s, env, _ = screen
    pid = env.make_playlist("empty")    # no tracks seeded
    s.load_for_id(pid)
    assert s._model.rowCount() == 0
    warned = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **kw: warned.append(a) or
                     QMessageBox.StandardButton.Ok))
    s._on_save()
    assert warned, "expected QMessageBox.warning to fire on empty queue"


def test_save_error_surfaces_messagebox(screen, monkeypatch):
    """Mock db.update_playlist_draft to raise — save must surface a
    QMessageBox.warning, NOT silently swallow the error (lesson from
    the clock-save-bug NIGHT_LOG)."""
    s, env, _ = screen
    pid = env.make_playlist("err"); env.seed_tracks(pid, count=2)
    s.load_for_id(pid)
    boom = []
    def raising_update(*a, **kw):
        raise RuntimeError("simulated DB write failure")
    monkeypatch.setattr(env.db, "update_playlist_draft", raising_update)
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **kw: boom.append(a) or
                     QMessageBox.StandardButton.Ok))
    ok = s._save()
    assert ok is False
    assert boom, "expected QMessageBox.warning to fire on save failure"


# ── Preview wiring (engine integration) ─────────────────────────────────


def test_preview_invokes_engine_with_track_path(screen):
    """Click ▶ Preview on a selected queue row → engine.load_file is
    called with the track's file_path."""
    s, env, eng = screen
    pid = env.make_playlist("prev"); env.seed_tracks(pid, count=2)
    s.load_for_id(pid)
    s._table_card.table().setCurrentIndex(s._model.index(0, 0))
    selected_path = s._model.all_rows()[0]["file_path"]
    assert selected_path, "test prerequisite: seeded song has a file_path"
    s._on_preview_track()
    method_calls = [c[0] for c in eng.calls]
    assert "load_file" in method_calls
    # The path passed to load_file matches the selected track's file_path
    load_call = next(c for c in eng.calls if c[0] == "load_file")
    assert load_call[1] == selected_path
    # Engine.play was called too
    assert "play" in method_calls


def test_preview_without_engine_pops_messagebox(qtbot, pe_env, monkeypatch):
    """Frame 9 with engine=None must show 'unavailable' toast — never
    silently fail."""
    s = PlaylistEdit(db=pe_env.db, engine=None)
    qtbot.addWidget(s)
    pid = pe_env.make_playlist("noeng"); pe_env.seed_tracks(pid, count=1)
    s.load_for_id(pid)
    s._table_card.table().setCurrentIndex(s._model.index(0, 0))
    fired = []
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *a, **kw: fired.append(a) or
                     QMessageBox.StandardButton.Ok))
    s._on_preview_track()
    assert fired, "expected QMessageBox.information when engine is None"


# ── On-air protection ──────────────────────────────────────────────────


def test_preview_with_studio_on_air_shows_confirm_dialog(screen, monkeypatch):
    """When studio._current_track is non-None, preview must pop a
    confirm dialog. Cancel → engine NOT called. OK → engine called."""
    s, env, eng = screen
    pid = env.make_playlist("onair"); env.seed_tracks(pid, count=1)
    s.load_for_id(pid)
    s._table_card.table().setCurrentIndex(s._model.index(0, 0))

    # Inject a fake studio currently on-air
    class _StudioStub:
        _current_track = {"title": "Live Show", "artist": "DJ"}
    s.set_studio(_StudioStub())

    # Capture exec() result — first sim Cancel, then OK
    calls_before = len(eng.calls)
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda self_box: QMessageBox.StandardButton.Cancel)
    s._on_preview_track()
    # No engine calls — user cancelled
    assert len(eng.calls) == calls_before, \
        "Cancel on confirm dialog must NOT trigger preview"

    # Now sim OK → engine fires
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda self_box: QMessageBox.StandardButton.Ok)
    s._on_preview_track()
    assert any(c[0] == "load_file" for c in eng.calls)


# ── Element-icon row + decorative tiles ────────────────────────────────


def test_decorative_icons_emit_coming_soon(screen, monkeypatch):
    """📁 and ♥ are render-only per Figma fidelity; click → toast."""
    s, env, _ = screen
    pid = env.make_playlist("dec"); env.seed_tracks(pid, count=1)
    s.load_for_id(pid)
    fired = []
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *a, **kw: fired.append(a) or
                     QMessageBox.StandardButton.Ok))
    s._on_decorative_icon("folder")
    s._on_decorative_icon("heart")
    assert len(fired) == 2


def test_functional_types_set_current(screen):
    s, _, _ = screen
    s._icon_row.set_current("jingle")
    assert s._icon_row.current() == "jingle"
    # Decorative key is rejected
    s._icon_row.set_current("folder")
    assert s._icon_row.current() == "jingle"   # unchanged


# ── Cancel / dirty ─────────────────────────────────────────────────────


def test_cancel_clean_routes_back(screen):
    s, env, _ = screen
    pid = env.make_playlist("clean"); env.seed_tracks(pid, count=1)
    s.load_for_id(pid)
    routes: list[str] = []
    s.screen_requested.connect(routes.append)
    s._cancel_then_route("playlists")
    assert routes == ["playlists"]


def test_cancel_dirty_prompts_confirm(screen, monkeypatch):
    s, env, _ = screen
    pid = env.make_playlist("dirty"); env.seed_tracks(pid, count=2)
    s.load_for_id(pid)
    # Mutate
    s._table_card.table().setCurrentIndex(s._model.index(0, 0))
    s._on_delete()
    assert s._dirty is True
    # Sim user clicks Cancel on the confirm dialog
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda self_box: QMessageBox.StandardButton.Cancel)
    routes: list[str] = []
    s.screen_requested.connect(routes.append)
    s._cancel_then_route("playlists")
    assert routes == [], "Cancel on confirm should not route"
