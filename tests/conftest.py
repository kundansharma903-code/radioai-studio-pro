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


# Headless Qt backstop, set before ANY QApplication can exist (a test
# module importing a screen that builds one would otherwise get the
# real "windows" platform). See qapp_args below.
os.environ.setdefault("QT_QPA_PLATFORM", "minimal:enable_fonts")

from core.audio import AudioEngine
from core.audio_engine import bass_init, bass_free
from core.database import Database


# ── Live-DB shield (MUST run before any Database connection) ────────────────

def _drop_db_singleton_conns(_cdb) -> None:
    """Close every connection the Database singleton holds and reset its
    per-thread cache, so the next _conn() reconnects via DB_PATH."""
    inst = _cdb.Database._instance
    if inst is None:
        return
    conns = list(getattr(inst, "_foreign_conns", {}).values())
    main = getattr(inst._local, "conn", None)
    if main is not None:
        conns.append(main)
    for c in conns:
        try:
            c.close()
        except Exception:
            pass
    inst._local = __import__("threading").local()
    if hasattr(inst, "_foreign_conns"):
        inst._foreign_conns.clear()


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
    # Anything that touched Database() BEFORE this fixture — a plugin's
    # pytest_sessionstart, import-time code — left the singleton holding
    # a cached connection to the LIVE file, and every test on that thread
    # then wrote through it. A probe plugin did exactly that on
    # 2026-10-18: 7 minutes of test writes hit the real DB (Break Policy
    # off, 14 grid cells lost, clock slots scrambled; restored from the
    # 08:39 backup). Drop any such connection, then PROVE the session
    # points at the copy, or refuse to run.
    _drop_db_singleton_conns(_cdb)
    files = [os.path.normcase(os.path.abspath(r[2]))
             for r in _cdb.Database()._conn().execute(
                 "PRAGMA database_list").fetchall() if r[2]]
    if os.path.normcase(os.path.abspath(copy)) not in files:
        _drop_db_singleton_conns(_cdb)
        pytest.exit(
            f"LIVE-DB SAFETY: the test session is not on the DB copy "
            f"(connected to {files}) — refusing to run against real data.",
            returncode=3)
    print(f"\n[conftest] live-DB shield: session redirected to {copy}")
    yield
    # Close the session's SQLite connections first — Windows will not
    # delete an open file, so rmtree(ignore_errors=True) silently left
    # every copy behind (1213 folders / 1.7 GB in TEMP by 2026-10-16).
    try:
        _drop_db_singleton_conns(_cdb)
    except Exception:
        pass
    import gc
    gc.collect()
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── Qt / BASS lifecycle ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp_args():
    """pytest-qt hook: pass -platform minimal so QApplication doesn't try
    to open a display server. Tests are headless.

    argv[0] MUST be a program name: pytest-qt hands this list to
    QApplication as the whole argv, and Qt treats argv[0] as the app
    name. With ["-platform", "minimal"], Qt took "-platform" as the
    program name and ignored "minimal", so for months the suite ran on
    the real "windows" platform. Test windows and modals appeared on
    the studio's on-air screen, and a "hidden" modal blocked until
    someone clicked it (found 2026-10-18).

    ":enable_fonts" keeps it headless but loads the native font database.
    Plain "minimal" has no real fonts, so text measured about 1.6x wider
    and the text-clipping tests failed (637 px vs a 399 px box)."""
    return ["radioai-tests", "-platform", "minimal:enable_fonts"]


@pytest.fixture(scope="session", autouse=True)
def _bass(qapp, _live_db_shield):
    """BASS_Init at session start, BASS_Free at session end. Depends on
    `qapp` so QApplication exists before BASS (signals can dispatch),
    and on the live-DB shield so no test can ever open the real DB.

    Device 0 = BASS's "No sound" device: streams still decode, play,
    advance position and reach EOS, but NOTHING reaches a soundcard.
    NEVER device -1 (system default) here. On the studio PC the Windows
    default output is "OUT 1-2 (BEHRINGER UMC 404HD)" — the transmitter
    feed — so the engine tests that play real library songs were
    putting audio on air during test runs (found 2026-10-18)."""
    # On-air safety gate (QA ⚠16/⚠17): refuse to run unless Qt is headless
    # AND audio goes nowhere. Any future edit that reverts either fix
    # fails here, loudly, instead of silently putting audio or windows on
    # the studio's on-air outputs.
    from PyQt6.QtGui import QGuiApplication
    platform = QGuiApplication.platformName()
    if platform != "minimal":
        pytest.exit(
            f"ON-AIR SAFETY: Qt platform is {platform!r}, not 'minimal' — "
            "test windows/modals would appear on the studio screen. "
            "Fix qapp_args / QT_QPA_PLATFORM in tests/conftest.py.",
            returncode=3)
    assert bass_init(device=0), "bass_init(No sound) failed at session start"
    from core.audio_engine import _bm
    if _bm.BASS_GetDevice() != 0:
        bass_free()
        pytest.exit(
            "ON-AIR SAFETY: test BASS session is not on device 0 ('No "
            "sound') — tests must never play audio to a real output (this "
            "PC's default output feeds the transmitter).",
            returncode=3)
    print(f"\n[conftest] on-air safety: Qt platform={platform!r}, "
          f"BASS device={_bm.BASS_GetDevice()} (No sound)")
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

@pytest.fixture(autouse=True)
def _flush_deferred_deletes():
    """After every test, process pending deleteLater()s and collect
    garbage while the test's objects are still in a known state.

    Without this, widgets released with deleteLater() piled up and were
    torn down much later — during some other test's event processing or
    at interpreter exit — in an arbitrary order. Files that build a full
    Studio per test (settings_integration, stitcher_trigger, library
    tiles) then died with a native access violation (0xC0000005) on a
    thread with no Python frame. It depended on heap layout, so it
    showed in the main checkout and not in a fresh worktree: measured
    3/3 crashes without this flush, 0/3 with it (2026-10-16).

    Production is unaffected: the app builds one Studio for its whole
    lifetime and never tears it down mid-run."""
    yield
    try:
        from PyQt6.QtCore import QCoreApplication, QEvent
        app = QCoreApplication.instance()
        if app is not None:
            for _ in range(3):
                QCoreApplication.sendPostedEvents(
                    None, QEvent.Type.DeferredDelete.value)
                app.processEvents()
    except Exception:
        pass
    import gc
    gc.collect()


@pytest.fixture(autouse=True)
def _no_hidden_modals(request, monkeypatch):
    """No test may open a REAL modal. Under -platform minimal nobody can
    click OK, so an unstubbed dialog's exec() blocks forever: one test
    that inherited the operator's live 'Stop playback + alert operator'
    setting hung the single-process suite for 17h39m (QA ⚠12,
    2026-10-18).

    Every QDialog / QMenu exec() is intercepted, recorded and returns at
    once (Rejected / no action); the test then FAILS at teardown naming
    the dialog. Failing at teardown — not raising inside exec() —
    matters: product code often wraps the dialog call in try/except
    (Studio._handle_missing_file does), which would swallow the error
    and let the test pass silently. Tests that stub exec() or the
    core.dialogs helpers themselves override this patch and are not
    affected; mark a test @pytest.mark.allow_modal to opt out entirely.

    Not covered: static C++ helpers that run exec() natively
    (QInputDialog.getText in ui/dialogs/add_campaign_dialog.py)."""
    if request.node.get_closest_marker("allow_modal"):
        yield
        return
    from PyQt6 import QtWidgets
    opened: list[str] = []

    def _intercept(ret):
        def _exec(self, *_a, **_k):
            try:
                title = self.windowTitle()
                if not title:
                    # core.dialogs paints its title on a QLabel and
                    # leaves windowTitle empty — name it by that text.
                    labels = [w.text() for w in
                              self.findChildren(QtWidgets.QLabel)
                              if w.text().strip()]
                    title = labels[1] if len(labels) > 1 else (
                        labels[0] if labels else "")
            except Exception:
                title = "?"
            opened.append(f"{type(self).__name__}({title!r})")
            return ret
        return _exec

    for name in dir(QtWidgets):
        cls = getattr(QtWidgets, name, None)
        if (isinstance(cls, type) and "exec" in vars(cls)
                and issubclass(cls, QtWidgets.QDialog)):
            monkeypatch.setattr(cls, "exec", _intercept(0))
    monkeypatch.setattr(QtWidgets.QMenu, "exec", _intercept(None))
    yield
    if opened:
        pytest.fail(
            "test opened a real modal (would block forever headless): "
            + ", ".join(opened)
            + " — stub core.dialogs / exec(), or mark it allow_modal",
            pytrace=False)


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
