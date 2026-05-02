"""RadioAI Studio Pro — Entry Point

Launch the main application window.
"""

import sys
import os
import atexit

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

from ui.main_window import MainWindow
from core.database import DatabaseManager


# ── Windows sleep prevention ────────────────────────────────────────────
# While RadioAI is running the system MUST NOT sleep, or scheduled breaks
# and the AI midnight scheduler will miss their triggers and audio will
# stop. We allow the display to turn off (screen lock is fine for an
# unattended broadcast PC), but the CPU/disk must stay awake.
#
# Flags:
#   ES_CONTINUOUS       = 0x80000000  → keep state until we clear it
#   ES_SYSTEM_REQUIRED  = 0x00000001  → don't sleep the system
#   ES_DISPLAY_REQUIRED = 0x00000002  → intentionally NOT set
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def prevent_sleep():
    """Tell Windows to keep the system awake while RadioAI is running."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
        )
    except Exception as e:
        print(f"[sleep-guard] could not arm SetThreadExecutionState: {e}")


def allow_sleep():
    """Restore Windows' normal sleep behaviour. Called on app exit."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
    except Exception:
        pass


def main():
    # High-DPI support
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

    # Arm the sleep guard as the very first thing and make sure it's
    # released on any exit path (normal quit, crash, Ctrl+C).
    prevent_sleep()
    atexit.register(allow_sleep)

    app = QApplication(sys.argv)
    app.setApplicationName("RadioAI Studio Pro")
    app.setOrganizationName("RadioAI")
    app.aboutToQuit.connect(allow_sleep)

    # Set app icon if available
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icons", "radioai_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Initialize database
    DatabaseManager()

    # Create and show main window
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
