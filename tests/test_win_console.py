"""
core/win_console.py — child-console-hiding patch tests.

Pinned behaviour (operator report 2026-07-03: black console flashes
whenever the Stitcher decoded parts via pydub→ffmpeg):
  • hide_child_console_windows() marks Popen.__init__ (is_patched()).
  • Idempotent — calling twice never double-wraps.
  • Children still spawn and run fine with output captured.
  • An explicit CREATE_NEW_CONSOLE request is left untouched
    (flag check only — we don't actually open a console in CI).
"""

from __future__ import annotations

import subprocess

from core import win_console


def test_patch_applies_and_is_idempotent():
    win_console.hide_child_console_windows()
    assert win_console.is_patched()
    first = subprocess.Popen.__init__
    win_console.hide_child_console_windows()   # second call: no-op
    assert subprocess.Popen.__init__ is first


def test_children_still_run_with_output_captured():
    win_console.hide_child_console_windows()
    res = subprocess.run(
        ["cmd", "/c", "echo radioai-no-window"],
        capture_output=True, text=True, timeout=30)
    assert res.returncode == 0
    assert "radioai-no-window" in res.stdout


def test_flag_policy():
    NO_WIN = subprocess.CREATE_NO_WINDOW
    NEW_CON = 0x00000010
    # bare spawn (pydub's case) → hidden
    assert win_console.effective_creationflags(0) == NO_WIN
    assert win_console.effective_creationflags(None) == NO_WIN
    # already hidden (aircheck encoder) → unchanged
    assert win_console.effective_creationflags(NO_WIN) == NO_WIN
    # explicit console request → respected, untouched
    assert win_console.effective_creationflags(NEW_CON) == NEW_CON


def test_pydub_spawn_path_covered():
    """pydub's utils.Popen is the exact call site that flashed — it
    resolves to subprocess.Popen, so the patched __init__ covers it."""
    import pydub.utils as pu
    win_console.hide_child_console_windows()
    assert pu.Popen.__init__ is subprocess.Popen.__init__
