"""
RadioAI — Windows structured-exception black box.

Why: the overnight on-air crashes (2026-07-04/05) are Qt6Core.dll
0xc0000409 — STATUS_STACK_BUFFER_OVERRUN, raised via __fastfail /
security-cookie checks. Python's ``faulthandler`` only hooks the C
signals (SIGSEGV/SIGABRT/SIGFPE), which these faults BYPASS, so
crash_dump.txt stayed empty.

A **vectored exception handler** (AddVectoredExceptionHandler) runs on
the faulting thread the instant a structured exception is raised —
before the OS unwinds and terminates. From there we dump every
thread's PYTHON stack via faulthandler, giving the real culprit line.

Best-effort + defensive: any failure to install is swallowed (a
diagnostic hook must never destabilise the broadcast app). The handler
only ACTS on the specific fatal codes we're hunting and always returns
CONTINUE_SEARCH so normal exception handling (and the crash itself) is
unchanged — we observe, we don't alter behaviour.
"""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes

log = logging.getLogger("CrashCatcher")

# Structured-exception codes worth a stack dump.
_FATAL_CODES = {
    0xC0000409,   # STATUS_STACK_BUFFER_OVERRUN (__fastfail / GS cookie)
    0xC0000005,   # ACCESS_VIOLATION
    0xC000001D,   # ILLEGAL_INSTRUCTION
    0xC0000374,   # HEAP_CORRUPTION
    0x80000003,   # BREAKPOINT (Qt qFatal on some builds)
}

EXCEPTION_CONTINUE_SEARCH = 0

_installed = False
_handler_ref = None          # keep the callback alive process-wide
_dump_file = None


class _EXCEPTION_RECORD(ctypes.Structure):
    pass


_EXCEPTION_RECORD._fields_ = [
    ("ExceptionCode", wintypes.DWORD),
    ("ExceptionFlags", wintypes.DWORD),
    ("ExceptionRecord", ctypes.POINTER(_EXCEPTION_RECORD)),
    ("ExceptionAddress", ctypes.c_void_p),
    ("NumberParameters", wintypes.DWORD),
    ("ExceptionInformation", ctypes.c_void_p * 15),
]


class _EXCEPTION_POINTERS(ctypes.Structure):
    _fields_ = [
        ("ExceptionRecord", ctypes.POINTER(_EXCEPTION_RECORD)),
        ("ContextRecord", ctypes.c_void_p),
    ]


_VEH = ctypes.WINFUNCTYPE(ctypes.c_long,
                          ctypes.POINTER(_EXCEPTION_POINTERS))


def install_windows_crash_catcher(dump_path: str = None) -> bool:
    """Arm the vectored handler. Idempotent, Windows-only."""
    global _installed, _handler_ref, _dump_file
    if _installed or os.name != "nt":
        return _installed
    if dump_path is None:
        try:
            from core.constants import LOG_PATH
            dump_path = os.path.join(LOG_PATH, "crash_dump.txt")
        except Exception:
            dump_path = "crash_dump.txt"

    def _on_exception(info_ptr):
        try:
            rec = info_ptr.contents.ExceptionRecord.contents
            code = int(rec.ExceptionCode) & 0xFFFFFFFF
            if code in _FATAL_CODES:
                import faulthandler
                from datetime import datetime
                with open(dump_path, "a", encoding="utf-8",
                          errors="replace") as f:
                    f.write(f"\n### VECTORED CATCH "
                            f"{datetime.now():%Y-%m-%d %H:%M:%S} "
                            f"code=0x{code:08X} "
                            f"addr=0x{rec.ExceptionAddress or 0:X} ###\n")
                    f.flush()
                    try:
                        faulthandler.dump_traceback(
                            file=f, all_threads=True)
                    except Exception:
                        pass
                    f.flush()
        except Exception:
            pass
        return EXCEPTION_CONTINUE_SEARCH      # never alter the outcome

    try:
        kernel32 = ctypes.windll.kernel32
        _handler_ref = _VEH(_on_exception)
        # first=1 → run before other handlers
        h = kernel32.AddVectoredExceptionHandler(1, _handler_ref)
        if not h:
            log.warning("AddVectoredExceptionHandler returned NULL")
            return False
        _dump_file = dump_path
        _installed = True
        return True
    except Exception as exc:
        log.warning(f"crash catcher install failed: {exc}")
        return False


def is_installed() -> bool:
    return _installed
