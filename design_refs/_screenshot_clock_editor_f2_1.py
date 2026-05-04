"""Phase F2.1 checkpoint screenshot — Clock Editor skeleton."""

import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import QTimer, QRect
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication

import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s")

from core.audio_engine import bass_init, bass_free
from core.database import Database


def _load_fonts():
    fonts_dir = os.path.join(ROOT, "assets", "fonts")
    if not os.path.isdir(fonts_dir):
        return
    for fname in os.listdir(fonts_dir):
        if fname.lower().endswith(".ttf"):
            QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname))


def _load_qss(app):
    qss = os.path.join(ROOT, "assets", "premium.qss")
    if os.path.exists(qss):
        with open(qss, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())


def main():
    app = QApplication(sys.argv)
    _load_fonts()
    _load_qss(app)
    bass_init()

    db = Database()
    db.verify()

    from ui.main_window import MainWindow
    win = MainWindow(db=db, db_ok=True, song_count=395)
    win.show()

    out = os.path.join(ROOT, "screenshots", "clock_editor_f2_1.png")

    def _capture():
        # Trigger Scheduling card → navigates to Clock Editor
        win._on_card_clicked("scheduling")
        app.processEvents()
        if hasattr(win, "clock_editor"):
            pix = win.clock_editor.grab(QRect(0, 0, 1440, 900))
            ok = pix.save(out, "PNG")
            print(f"saved: {out}  ({pix.width()}×{pix.height()})  ok={ok}")
        else:
            print("no clock_editor attribute")
        app.quit()

    QTimer.singleShot(900, _capture)
    rc = app.exec()
    bass_free()
    sys.exit(rc)


if __name__ == "__main__":
    main()
