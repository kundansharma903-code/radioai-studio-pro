"""
PlaylistNew (Frame 8 — Create New Playlist) AudioEngine wiring tests.

Frame 8 has no Preview button per Figma 243:2 — these tests verify
the constructor-injection contract only, so Frame 9 (Edit Playlist,
which DOES have ▶ Preview) can rely on the same shared engine
instance flowing in via MainWindow.

Contract:
  1. PlaylistNew(db, engine=eng) stores eng as self._engine
  2. Studio + PlaylistNew, given the same engine instance, share by
     identity (Option C DI — one engine per app, passed down)
  3. PlaylistNew(db) — no engine — defaults self._engine to None so
     downstream consumers (Frame 9 preview etc.) can guard cleanly
"""

from __future__ import annotations

import pytest

from core.database import Database
from ui.playlist_new import PlaylistNew
from ui.studio import Studio


@pytest.fixture
def db():
    return Database()


def test_constructor_stores_engine(qtbot, engine, db):
    """PlaylistNew(..., engine=e) must hold e on self._engine."""
    s = PlaylistNew(db=db, engine=engine)
    qtbot.addWidget(s)
    assert s._engine is engine


def test_shared_instance_with_studio(qtbot, engine, db):
    """One engine per app — Studio._engine and PlaylistNew._engine
    must be the same object when MainWindow passes the singleton to
    both. Frame 9's Preview will preview-on-monitor while Studio
    plays on-air; that only works if both screens reach into the
    same channel namespace."""
    studio = Studio(db=db, engine=engine, scheduler=None)
    qtbot.addWidget(studio)
    new = PlaylistNew(db=db, engine=engine)
    qtbot.addWidget(new)
    assert studio._engine is new._engine
    assert studio._engine is engine


def test_guard_still_fires_when_engine_none(qtbot, db):
    """Defaulting engine=None must remain a valid runtime state — the
    guard pattern used by every other screen (`if self._engine is
    None: ...`) relies on it."""
    s = PlaylistNew(db=db)    # no engine kwarg
    qtbot.addWidget(s)
    assert s._engine is None
