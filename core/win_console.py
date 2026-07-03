"""
RadioAI — hide child-process console windows (Windows GUI app).

Root cause (operator report 2026-07-03: "stitcher start hote hi 2-3
black screens, jaise python script run ho rahi ho"): pydub decodes
every part via bare ``subprocess.Popen(ffmpeg …)`` with no
``creationflags`` — and in the frozen WINDOWED exe (no parent console)
Windows gives each child its own console window, which flashes on
screen. The Stitcher decodes opening + hooks + separator + closing +
export = several ffmpeg/ffprobe spawns = several flashes. Same story
for the hook scanner's pydub use and any other library that shells out.

Fix: patch ``subprocess.Popen.__init__`` ONCE, process-wide, to OR in
``CREATE_NO_WINDOW`` — unless the caller explicitly requested a real
console (``CREATE_NEW_CONSOLE``). Callers that already pass
``CREATE_NO_WINDOW`` (aircheck's encoder) are unaffected — OR-ing the
same bit is a no-op.

Called once from main.py, right after logging setup, before any engine
can spawn a child.
"""

from __future__ import annotations

import os
import subprocess

_CREATE_NEW_CONSOLE = 0x00000010
_patched = False


def effective_creationflags(flags: int) -> int:
    """The flag policy, kept pure for tests: OR in CREATE_NO_WINDOW
    unless the caller explicitly asked for a real console."""
    flags = int(flags or 0)
    if flags & _CREATE_NEW_CONSOLE:
        return flags
    return flags | subprocess.CREATE_NO_WINDOW


def hide_child_console_windows() -> None:
    """Idempotent, Windows-only. Safe under pytest re-imports."""
    global _patched
    if _patched or os.name != "nt":
        return
    _patched = True

    orig_init = subprocess.Popen.__init__

    def _no_window_init(self, *args, **kwargs):
        kwargs["creationflags"] = effective_creationflags(
            kwargs.get("creationflags", 0))
        orig_init(self, *args, **kwargs)

    _no_window_init._radioai_no_window = True          # test marker
    subprocess.Popen.__init__ = _no_window_init


def is_patched() -> bool:
    return bool(getattr(subprocess.Popen.__init__,
                        "_radioai_no_window", False))
