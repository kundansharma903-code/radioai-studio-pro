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
import shutil
import sys
import tempfile

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


# ── Live-DB shield (MUST run before any Database connection) ────────────────

@pytest.fixture(scope="session", autouse=True)
def _live_db_shield():
    """Run the ENTIRE test session against a disposable COPY of the dev
    DB — never the live operator file.

    Why: two real corruption incidents (2026-07-01 + 2026-07-02) were
    caused by test processes dying mid-WAL-write on the LIVE DB (the
    known BASS teardown segfault flake, force-killed runs, and tests
    running concurrently with the on-air app). With this shield a
    crashed run can only ever corrupt a throwaway temp file; fixture
    litter and teardown deletions also stop touching operator data.

    Mechanics: Database._conn() reads the module global DB_PATH at
    connect time and connections are created lazily, so patching the
    globals here (before the first test runs) redirects every
    connection for the whole session. The copy is byte-identical, so
    tests that rely on real library data (394 songs etc.) see exactly
    what they saw before."""
    import core.database as _cdb
    import core.constants as _cconst
    live = str(_cdb.DB_PATH)
    if not os.path.exists(live):
        yield
        return
    tmpdir = tempfile.mkdtemp(prefix="radioai_testdb_")
    copy = os.path.join(tmpdir, "radioai_test.db")
    shutil.copy2(live, copy)
    for ext in ("-wal", "-shm"):
        if os.path.exists(live + ext):
            shutil.copy2(live + ext, copy + ext)
    _cdb.DB_PATH = copy
    _cconst.DB_PATH = copy
    try:
        import core.paths as _cpaths
        _cpaths.DB_PATH = copy
    except Exception:
        pass
    print(f"\n[conftest] live-DB shield: session redirected to {copy}")
    yield
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── Qt / BASS lifecycle ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp_args():
    """pytest-qt hook: pass -platform minimal so QApplication doesn't try
    to open a display server. Tests are headless."""
    return ["-platform", "minimal"]


@pytest.fixture(scope="session", autouse=True)
def _bass(qapp, _live_db_shield):
    """BASS_Init at session start, BASS_Free at session end. Depends on
    `qapp` so QApplication exists before BASS (signals can dispatch),
    and on the live-DB shield so no test can ever open the real DB."""
    assert bass_init(), "bass_init() failed at session start"
    yield
    bass_free()


@pytest.fixture(scope="session", autouse=True)
def _aircheck_shield(_live_db_shield):
    """Force aircheck_enabled=0 for the whole test session (on the
    shielded DB copy). MainWindow schedules a 2s singleShot that starts
    REAL loopback recording — a test pumping the event loop past that
    would spin up a BASS record thread + write WAVs into the operator's
    recordings folder, and bass_free at teardown with a live record
    thread is an access violation. Recorder-specific tests re-enable
    it explicitly on their own snapshot."""
    from core.settings import Settings
    try:
        Settings().set("aircheck_enabled", "0")
    except Exception:
        pass
    yield


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
