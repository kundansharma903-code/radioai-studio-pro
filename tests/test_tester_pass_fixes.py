"""
Fixes from the 2026-10-16 exploratory tester pass (sandbox crawl of
every screen + pyflakes over core/ and ui/).

  • MainWindow "Stop AI Engine", "Ungroup" and "Discard Plan" called a
    bare confirm() that was never imported → NameError, button did
    nothing (before the 07-25 excepthook it would have aborted the app).
  • core.dialogs centred parent-less dialogs with QApplication, which
    was never imported (NameError swallowed → dialog not centred).
  • Studio had TWO showEvent methods; the later one silently replaced
    the earlier, so the Libraries panel never refreshed on show — songs
    added in Songs Library stayed invisible in Studio until a restart.
  • A spot with no playable file (or a spot/SOTG file BASS could not
    open) returned with the deck already cleared → dead air until the
    next scheduler event. The break chain now continues.
"""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QShowEvent

from core.database import Database


def _pump(n=4):
    for _ in range(n):
        QCoreApplication.processEvents()


# ── MainWindow confirm handlers ─────────────────────────────────────────


@pytest.mark.parametrize("handler", ["_on_sched_ai_stop",
                                     "_on_sched_ai_ungroup",
                                     "_on_sched_ai_discard"])
def test_scheduling_ai_buttons_ask_and_respect_cancel(handler, monkeypatch):
    import core.dialogs as D
    from ui.main_window import MainWindow
    asked = []
    monkeypatch.setattr(D, "confirm",
                        lambda *a, **k: asked.append(a[1]) or False)

    class _Dummy:
        pass
    fn = getattr(MainWindow, handler)
    try:
        fn(_Dummy())
    except TypeError:
        fn(_Dummy(), None)
    assert len(asked) == 1, "the operator must be asked first"


def test_main_window_has_no_bare_confirm_calls():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "ui", "main_window.py"),
        encoding="utf-8").read()
    import re
    assert not re.search(r"(?<![\w.])confirm\(", src)


# ── dialogs centre without a parent ────────────────────────────────────


def test_parentless_dialog_builds(qapp, monkeypatch):
    import core.dialogs as D
    from PyQt6.QtWidgets import QDialog
    monkeypatch.setattr(QDialog, "exec", lambda self: 0)
    assert D.confirm(None, "T", "text") is False
    assert hasattr(D, "QApplication")


# ── Studio showEvent refreshes the Libraries panel ─────────────────────


class _FakeIJE:
    class _S:
        def connect(self, *_): pass
        def disconnect(self, *_): pass
    def __init__(self):
        self.pad_started = self._S(); self.pad_ended = self._S()
        self.pad_stopped = self._S()
    def play_pad(self, *a, **k): return True
    def stop_pad(self, _): return True
    def stop_all(self): return 0
    def is_playing(self, _): return False


def test_studio_show_refreshes_library(qtbot, engine):
    from ui.studio import Studio
    s = Studio(db=Database(), engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    s._libraries._on_type_clicked("Songs")
    calls = []
    s._load_library_songs = lambda cat=None: calls.append(cat)
    s.showEvent(QShowEvent())
    assert calls, "Libraries panel must re-read the DB when Studio shows"


# ── spot that cannot reach the deck keeps the break moving ─────────────


class _Sig:
    def __init__(self): self._s = []
    def connect(self, f): self._s.append(f)
    def disconnect(self, *_): self._s.clear()
    def emit(self, *a):
        for f in list(self._s): f(*a)


class _Eng:
    def __init__(self, bad=()):
        self.bad = set(bad); self.loaded = []; self._n = 0
        self.position_changed = _Sig(); self.playback_ended = _Sig()
        self.error_occurred = _Sig()
    def load_file(self, p, loop=False):
        if p in self.bad:
            raise RuntimeError("cannot open")
        self._n += 1; self.loaded.append(p); return self._n
    def set_volume(self, *_): pass
    def play(self, *_): pass
    def cleanup(self, *_): pass
    def cleanup_all(self): pass
    def get_duration_ms(self, *_): return 30_000
    def get_levels(self, *_): return (0.0, 0.0)
    def get_state(self, *_): return "playing"
    def get_position_ms(self, *_): return 0


def _song():
    for r in Database()._conn().execute(
            "SELECT * FROM songs WHERE is_enabled = 1 ORDER BY id"):
        if r["file_path"] and os.path.exists(r["file_path"]):
            return {"id": r["id"], "title": r["title"],
                    "artist": r["artist"], "file_path": r["file_path"],
                    "duration_ms": r["duration_ms"], "_item_type": "song"}
    pytest.skip("no playable song")


@pytest.fixture
def idle_studio(qtbot, monkeypatch):
    import core.dialogs as D
    monkeypatch.setattr(D, "warning", lambda *a, **k: None)
    from ui.studio import Studio

    def make(eng):
        s = Studio(db=Database(), engine=eng, scheduler=None)
        qtbot.addWidget(s)
        monkeypatch.setattr(s, "_break_policy_enabled", lambda: False)
        return s
    return make


def test_spot_without_file_resumes_the_queue(idle_studio, monkeypatch):
    song = _song()
    eng = _Eng()
    s = idle_studio(eng)
    s._manual_queue = [dict(song, _manual=True, _manual_uid=1)]
    monkeypatch.setattr(s._db, "get_spot_files", lambda cid: [])
    s._do_scheduler_spot_due(12345, _policy_exempt=True)
    _pump()
    assert eng.loaded == [song["file_path"]], "queue must resume"


def test_spot_that_cannot_open_moves_to_next_spot(idle_studio, monkeypatch,
                                                  tmp_path):
    bad = tmp_path / "bad.mp3"; bad.write_bytes(b"x")
    good = tmp_path / "good.mp3"; good.write_bytes(b"x")
    files = {1: [{"file_path": str(bad), "is_active": 1}],
             2: [{"file_path": str(good), "is_active": 1}]}
    eng = _Eng(bad={str(bad)})
    s = idle_studio(eng)
    monkeypatch.setattr(s._db, "get_spot_files", lambda cid: files[cid])
    # Campaign ids 1/2 are stand-ins — keep the 2026-10-17 contract
    # gate (date window / limits) out of this file-failure test.
    monkeypatch.setattr(s._db, "campaign_air_check",
                        lambda cid, *a, **kw: (True, ""))
    s._pending_spots = [2]
    s._do_scheduler_spot_due(1, _policy_exempt=True)
    _pump()
    assert eng.loaded == [str(good)]
    assert s._playback_kind == "spot"


def test_live_assist_spot_without_file_stays_idle(idle_studio, monkeypatch):
    song = _song()
    eng = _Eng()
    s = idle_studio(eng)
    s._auto_advance_enabled = False
    s._manual_queue = [dict(song, _manual=True, _manual_uid=1)]
    monkeypatch.setattr(s._db, "get_spot_files", lambda cid: [])
    s._do_scheduler_spot_due(12345, _policy_exempt=True)
    _pump()
    assert eng.loaded == []


# ── manual backup captures WAL-only changes ────────────────────────────


def test_backup_now_includes_changes_still_in_the_wal(tmp_path, monkeypatch):
    """Backup Now used checkpoint + file copy and ignored a busy
    checkpoint, so with the app's connections open the newest rows could
    miss the backup. The online backup API snapshots WAL content too."""
    import sqlite3
    import core.backup_restore as br
    live = tmp_path / "radioai.db"
    shutil_src = Database()._conn().execute("PRAGMA database_list").fetchone()[2]
    src = sqlite3.connect(shutil_src)
    dst = sqlite3.connect(str(live))
    src.backup(dst); src.close(); dst.close()
    monkeypatch.setattr(br, "_db_path", lambda: live)

    writer = sqlite3.connect(str(live))
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    reader = sqlite3.connect(str(live))
    reader.execute("BEGIN")                      # holds an old snapshot
    reader.execute("SELECT COUNT(*) FROM settings").fetchone()
    writer.execute("INSERT OR REPLACE INTO settings (key, value) "
                   "VALUES ('qa_backup_probe', 'in-wal')")
    writer.commit()
    try:
        out = br.backup_now(tmp_path / "bk")
    finally:
        reader.rollback(); reader.close(); writer.close()
    assert out
    got = sqlite3.connect(out).execute(
        "SELECT value FROM settings WHERE key = 'qa_backup_probe'"
    ).fetchone()
    assert got == ("in-wal",)


# ── Studio header Settings opens the Settings Hub ──────────────────────


def test_studio_settings_button_routes_to_settings(qtbot, engine,
                                                   monkeypatch):
    import core.dialogs as D
    from ui.studio import Studio
    shown = []
    monkeypatch.setattr(D, "info", lambda *a, **k: shown.append(a))
    s = Studio(db=Database(), engine=engine, scheduler=None,
               instant_jingle_engine=_FakeIJE())
    qtbot.addWidget(s)
    got = []
    s.breadcrumb_clicked.connect(got.append)
    s._on_settings()
    assert got == ["settings"] and shown == []


def test_main_window_breadcrumb_settings_uses_hub_router():
    from ui.main_window import MainWindow
    routed = []

    class _MW:
        _on_hub_screen_requested = staticmethod(routed.append)
    MainWindow._on_breadcrumb(_MW(), "settings")
    assert routed == ["settings"]


# ── promised post-break songs wait for the break ───────────────────────


def test_pins_are_not_consumed_before_the_break(idle_studio, monkeypatch,
                                                tmp_path):
    """Break Policy held the spot for the next window; an ordinary song
    transition then aired the 'after the break' song BEFORE the break.
    Pins now wait until a spot / SOTG / the montage actually starts."""
    song = _song()
    spot = tmp_path / "spot.mp3"; spot.write_bytes(b"x")
    eng = _Eng()
    s = idle_studio(eng)
    s._teased_songs = [dict(song)]
    s._tease_waiting_for_break = True
    assert s._pop_next_teased_song() is None, "break not aired yet"
    assert len(s._teased_songs) == 1, "pin kept for after the break"

    monkeypatch.setattr(s._db, "get_spot_files",
                        lambda cid: [{"file_path": str(spot),
                                      "is_active": 1}])
    s._do_scheduler_spot_due(7, _policy_exempt=True)
    assert s._playback_kind == "spot"
    assert s._tease_waiting_for_break is False
    nxt = s._pop_next_teased_song()
    assert nxt is not None and nxt["id"] == song["id"]


def test_montage_end_releases_the_pins(idle_studio):
    s = idle_studio(_Eng())
    s._tease_waiting_for_break = True
    s._pending_spots = []
    s._teased_songs = []
    s._on_stitcher_tease_done()
    assert s._tease_waiting_for_break is False


# ── scheduler thread reuses ONE connection (handle / memory leak) ──────


def test_qthread_reuses_one_db_connection(qapp):
    """PyQt gives every slot call on a QThread a fresh Python thread
    state, so threading.local was empty on every scheduler tick and a
    new SQLite connection was opened each second — ~3 leaked handles/s
    and ~14 MB/min for the life of the app."""
    import ctypes, sys, threading
    from PyQt6.QtCore import QEventLoop, QTimer
    from core.scheduler.engine import SchedulerEngine

    seen = []
    eng = SchedulerEngine(db=Database(), tick_interval_ms=100)
    orig = eng._check_active_clock_change

    def spy():
        seen.append((threading.get_ident(), id(Database()._conn())))
        orig()
    eng._check_active_clock_change = spy

    def handles():
        if sys.platform != "win32":
            return 0
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.GetProcessHandleCount.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        n = ctypes.c_ulong()
        k.GetProcessHandleCount(k.GetCurrentProcess(), ctypes.byref(n))
        return n.value

    def spin(ms):
        loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

    eng.start(); spin(400)
    h0 = handles(); n0 = len(seen)
    spin(2000)
    h1 = handles(); n1 = len(seen)
    eng.shutdown(); spin(500)
    ticks = n1 - n0
    assert ticks >= 10
    assert len({c for _, c in seen}) == 1, "one connection per thread"
    assert h1 - h0 < ticks, f"handles grew {h1 - h0} over {ticks} ticks"
