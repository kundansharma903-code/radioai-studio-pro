"""
core/crash_catcher.py — Windows structured-exception black box.

Pinned behaviour (after the 2026-07-04/05 Qt6Core 0xc0000409 crashes
faulthandler could not catch):
  • install is idempotent and Windows-only.
  • the fatal-code set includes 0xC0000409 (the actual crash code).
  • the handler is a pure observer — it returns CONTINUE_SEARCH so it
    never alters the crash outcome.
"""

from __future__ import annotations

from core import crash_catcher


def test_install_idempotent():
    assert crash_catcher.install_windows_crash_catcher() is True
    first = crash_catcher._handler_ref
    assert crash_catcher.install_windows_crash_catcher() is True
    assert crash_catcher._handler_ref is first     # not re-wrapped
    assert crash_catcher.is_installed()


def test_fatal_codes_cover_the_crash():
    assert 0xC0000409 in crash_catcher._FATAL_CODES   # the on-air crash
    assert 0xC0000005 in crash_catcher._FATAL_CODES   # access violation


def test_handler_returns_continue_search():
    # CONTINUE_SEARCH == 0 — observe, never swallow.
    assert crash_catcher.EXCEPTION_CONTINUE_SEARCH == 0
