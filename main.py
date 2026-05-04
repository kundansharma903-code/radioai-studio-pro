"""
RadioAI Studio Pro v2.0 — Entry Point
Startup sequence:
  1. setup_logging
  2. prevent_sleep (Windows)
  3. QApplication
  4. load style.qss
  5. BASS audio init
  6. Database.verify()
  7. Settings.load()
  8. MainWindow (1440×900)
  9. app.exec()
  10. AudioEngine.shutdown → bass_free → allow_sleep on exit
"""

import sys
import os
import logging

# Force UTF-8 on Windows terminals
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase

# ── Project root on sys.path ──────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core.logger import setup_logging, get_logger
from core.sleep_prevent import prevent_sleep, allow_sleep
from core.audio_engine import bass_init, bass_free
from core.database import Database
from core.settings import Settings

log = get_logger("main")


def load_fonts() -> int:
    """Register all .ttf files in assets/fonts/ with QFontDatabase.
    Must be called AFTER QApplication is created."""
    fonts_dir = os.path.join(_HERE, "assets", "fonts")
    if not os.path.isdir(fonts_dir):
        log.warning(f"fonts dir not found: {fonts_dir}")
        return 0
    loaded = 0
    for fname in sorted(os.listdir(fonts_dir)):
        if not fname.lower().endswith((".ttf", ".otf")):
            continue
        path = os.path.join(fonts_dir, fname)
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id == -1:
            log.error(f"Font load failed: {fname}")
        else:
            families = QFontDatabase.applicationFontFamilies(font_id)
            log.info(f"Font loaded: {fname} -> {families}")
            loaded += 1
    return loaded


def load_stylesheet(app: QApplication) -> bool:
    # Prefer premium.qss (built for Phase 2+); fall back to style.qss
    for name in ("premium.qss", "style.qss"):
        qss_path = os.path.join(_HERE, "assets", name)
        if os.path.exists(qss_path):
            try:
                with open(qss_path, encoding="utf-8") as f:
                    app.setStyleSheet(f.read())
                log.info(f"{name} loaded")
                return True
            except Exception as exc:
                log.error(f"Failed to load {name}: {exc}")
    log.warning("No QSS stylesheet found")
    return False


def main():
    # 1. Logging
    setup_logging(debug="--debug" in sys.argv)
    log.info("=" * 60)
    log.info("RadioAI Studio Pro v2.0 starting")
    log.info("=" * 60)

    # 2. Sleep prevention
    prevent_sleep()
    log.info("Sleep prevention active")

    # 3. QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("RadioAI Studio Pro")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("RadioAI")

    # High-DPI
    # (PyQt6 enables high-DPI by default — no extra flags needed)

    # 4a. Fonts (must be loaded BEFORE stylesheet so fontDatabase is ready)
    n_fonts = load_fonts()
    log.info(f"Fonts registered: {n_fonts}")

    # 4b. Stylesheet
    load_stylesheet(app)

    # 5. BASS audio engine
    if not bass_init():
        log.warning("BASS audio init failed — playback will be unavailable")
    else:
        log.info("BASS audio ready")

    # 6. Database
    db = Database()
    db_ok = db.verify()
    song_count = 0
    if db_ok:
        try:
            rows = db._conn().execute("SELECT COUNT(*) FROM songs").fetchone()
            song_count = rows[0] if rows else 0
        except Exception:
            pass
    else:
        log.error("Database verification failed — launching anyway")

    # 7. Settings
    settings = Settings()
    settings.load(db)

    # 8. Main window
    from ui.main_window import MainWindow
    window = MainWindow(db_ok=db_ok, song_count=song_count, db=db)
    if "--maximized" in sys.argv:
        window.showMaximized()
        log.info("Window shown maximized")
    else:
        window.show()
        log.info(
            f"Window shown — outer={window.width()}x{window.height()}  "
            f"client={window.centralWidget().width()}x{window.centralWidget().height()}"
        )

    # 9. Event loop
    exit_code = app.exec()

    # 10. Cleanup
    bass_free()
    allow_sleep()
    log.info(f"RadioAI Studio Pro exiting (code {exit_code})")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
