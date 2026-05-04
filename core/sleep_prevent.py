"""
RadioAI Studio Pro — Windows Sleep Prevention
Keeps the system awake during broadcast so the AI midnight
trigger always fires and audio never stops.
Screen CAN turn off; system CANNOT sleep.
"""

import sys
import ctypes

# Windows API flags
_ES_CONTINUOUS       = 0x80000000
_ES_SYSTEM_REQUIRED  = 0x00000001


def prevent_sleep() -> None:
    """Prevent Windows from sleeping. Call at app startup."""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
        )


def allow_sleep() -> None:
    """Re-allow sleep. Call at app shutdown."""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS
        )
