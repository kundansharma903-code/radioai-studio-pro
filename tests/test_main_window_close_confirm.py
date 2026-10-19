"""
Closing the window while on air asks first (QA ⚠28, operator 2026-10-19).

A title-bar X / WM_CLOSE used to stop the station instantly. Now, when a
deck is playing or AUTO (the scheduler) is running, the operator must
confirm; Enter and Esc both keep the station on air. Idle → closes as
before. Windows shutdown / logoff → closes without asking.
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QCloseEvent

from core import dialogs


@pytest.fixture
def mw(qapp, qtbot, monkeypatch):
    from ui import main_window as mw_mod
    monkeypatch.setattr(mw_mod.MainWindow, "_apply_startup_auto_mode",
                        lambda self: None)
    from core.database import Database
    w = mw_mod.MainWindow(db=Database())
    qtbot.addWidget(w)
    cleanups: list = []
    monkeypatch.setattr(w, "_cleanup_engine", lambda: cleanups.append(1))
    asked: list = []

    def _confirm(answer):
        def _c(*a, **k):
            asked.append(k)
            return answer
        monkeypatch.setattr(dialogs, "confirm", _c)
    yield w, cleanups, asked, _confirm
    w._session_ending = True                 # let teardown close freely
    w.studio._playback_cid = None
    # The recorder above replaced the real cleanup: run it now, or the
    # window's QThreads outlive it → Qt fail-fast 0xC0000409.
    type(w)._cleanup_engine(w)


def _close(w) -> QCloseEvent:
    ev = QCloseEvent()
    w.closeEvent(ev)
    return ev


def test_idle_station_closes_without_asking(mw):
    w, cleanups, asked, confirm = mw
    confirm(False)
    assert not w._station_is_on_air()
    ev = _close(w)
    assert ev.isAccepted() and cleanups == [1] and asked == []


def test_playing_deck_cancel_keeps_station_on_air(mw):
    w, cleanups, asked, confirm = mw
    confirm(False)                           # Keep On Air / Esc / Enter
    w.studio._playback_cid = 11
    ev = _close(w)
    assert not ev.isAccepted()
    assert cleanups == []                    # nothing torn down
    assert asked and asked[0].get("default_no") is True
    assert asked[0].get("danger") is True


def test_playing_deck_confirm_stops_and_exits(mw):
    w, cleanups, asked, confirm = mw
    confirm(True)
    w.studio._playback_cid = 11
    ev = _close(w)
    assert ev.isAccepted() and cleanups == [1]


def test_auto_running_counts_as_on_air(mw, monkeypatch):
    w, cleanups, asked, confirm = mw
    confirm(False)
    monkeypatch.setattr(w._scheduler, "is_running", lambda: True)
    ev = _close(w)
    assert not ev.isAccepted() and asked


def test_windows_shutdown_closes_without_asking(mw):
    w, cleanups, asked, confirm = mw
    confirm(False)
    w.studio._playback_cid = 11
    w._on_session_ending()
    ev = _close(w)
    assert ev.isAccepted() and cleanups == [1] and asked == []


def test_confirm_default_no_puts_enter_on_cancel(qapp, monkeypatch):
    """dialogs.confirm(default_no=True) → Enter / default = Cancel."""
    from PyQt6.QtWidgets import QDialog
    seen = {}

    def _exec(self):
        seen["default"] = self._default_btn_idx
        seen["cancel"] = self._cancel_btn_idx
        return 0
    monkeypatch.setattr(QDialog, "exec", _exec)
    assert dialogs.confirm(None, "T", "x", default_no=True) is False
    assert seen == {"default": 1, "cancel": 1}
    dialogs.confirm(None, "T", "x")
    assert seen["default"] == 0              # unchanged for other callers
