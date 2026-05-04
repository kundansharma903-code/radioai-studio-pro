"""
Shared pytest fixtures for the audio engine test suite.

  - qapp_args     — pytest-qt: launch QApplication with -platform minimal
                    so headless test runners don't need a display
  - _bass         — session-scoped autouse: bass_init at start, bass_free
                    at end (matches Q6 from A1 — engine constructor stays
                    side-effect-free; the test session owns BASS lifecycle)
  - engine        — fresh AudioEngine per test, cleanup_all on teardown
  - test_song_path        — a real DB song with on-disk file (any duration)
  - test_long_song_path   — a real DB song > 60s (for position-isolation
                            and EOS-via-seek-near-end tests)
  - test_song_with_db_dur — (path, db_duration_ms) tuple for the duration
                            cross-check test in engine_position
"""

from __future__ import annotations

import os
import sys

import pytest

# Note: pytest captures stdout/stderr itself — DO NOT wrap them here
# (replacing the buffer breaks pytest's CaptureManager).

# Project root on sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from core.audio import AudioEngine
from core.audio_engine import bass_init, bass_free
from core.database import Database


# ── Qt / BASS lifecycle ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp_args():
    """pytest-qt hook: pass -platform minimal so QApplication doesn't try
    to open a display server. Tests are headless."""
    return ["-platform", "minimal"]


@pytest.fixture(scope="session", autouse=True)
def _bass(qapp):
    """BASS_Init at session start, BASS_Free at session end. Depends on
    `qapp` so QApplication exists before BASS (signals can dispatch)."""
    assert bass_init(), "bass_init() failed at session start"
    yield
    bass_free()


# ── AudioEngine fixture ─────────────────────────────────────────────────────

@pytest.fixture
def engine():
    """Fresh AudioEngine per test. cleanup_all on teardown so leaked
    channels don't pollute later tests."""
    e = AudioEngine()
    yield e
    e.cleanup_all()


# ── Song path fixtures (skip cleanly if DB has no playable file) ────────────

def _pick_song(min_duration_ms: int) -> str | None:
    db = Database()
    rows = db._conn().execute(
        "SELECT file_path FROM songs "
        "WHERE file_path IS NOT NULL AND file_path != '' "
        "AND duration_ms > ? "
        "ORDER BY id LIMIT 200",
        [min_duration_ms],
    ).fetchall()
    for r in rows:
        if r[0] and os.path.exists(r[0]):
            return r[0]
    return None


@pytest.fixture(scope="session")
def test_song_path() -> str:
    """A real DB song with on-disk file (>5s)."""
    path = _pick_song(min_duration_ms=5_000)
    if path is None:
        pytest.skip("No DB song with playable file found (>5s)")
    return path


@pytest.fixture(scope="session")
def test_long_song_path() -> str:
    """A real DB song > 60s — needed for position-isolation tests
    (seek to 10s/30s/60s on three channels)."""
    path = _pick_song(min_duration_ms=60_000)
    if path is None:
        pytest.skip("No DB song > 60s with playable file found")
    return path


@pytest.fixture(scope="session")
def test_song_with_db_dur() -> tuple[str, int]:
    """(path, db_duration_ms) — used by the duration cross-check test."""
    db = Database()
    rows = db._conn().execute(
        "SELECT file_path, duration_ms FROM songs "
        "WHERE file_path IS NOT NULL AND duration_ms > 5000 "
        "ORDER BY id LIMIT 200"
    ).fetchall()
    for r in rows:
        if r[0] and os.path.exists(r[0]):
            return r[0], int(r[1])
    pytest.skip("No DB song with non-zero duration_ms found")
