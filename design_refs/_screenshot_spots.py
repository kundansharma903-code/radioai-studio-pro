"""Screenshot harness for Spots & Commercials (Figma 35:2).

Scenarios:
    default   — first row auto-selected, Tab 1 active     → 01_default
    rowclick  — selects a different campaign              → 02_rowclick
    tabschedule — Tab 2 (Break Schedule) active           → 03_tab_schedule
    tabreports  — Tab 3 (Play Reports) active             → 04_tab_reports
    breadcrumb  — clicked back to Control Panel           → 05_breadcrumb
"""

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


SCENARIOS = {
    "default":     "spots_01_default.png",
    "rowclick":    "spots_02_rowclick.png",
    "tabschedule": "spots_03_tab_schedule.png",
    "tabreports":  "spots_04_tab_reports.png",
    "breadcrumb":  "spots_05_breadcrumb.png",
}


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "default"
    out_name = SCENARIOS.get(scenario, "spots_commercials_built.png")

    app = QApplication(sys.argv)
    _load_fonts()
    _load_qss(app)
    bass_init()

    db = Database()
    db.verify()

    from ui.main_window import MainWindow
    win = MainWindow(db=db, db_ok=True, song_count=0)
    win.show()

    out = os.path.join(ROOT, "screenshots", out_name)

    def _drive(screen):
        if scenario == "default":
            return  # first row auto-selected
        if scenario == "rowclick":
            # Pick a different campaign — id 1 (FreshBurst Cola — Summer)
            screen._select_campaign(1)
        elif scenario == "tabschedule":
            screen._switch_tab(1)
        elif scenario == "tabreports":
            screen._switch_tab(2)
        elif scenario == "breadcrumb":
            # Already on Spots — emit breadcrumb back to Control Panel
            screen.breadcrumb_clicked.emit("control_panel")

    def _capture():
        if hasattr(win, "_on_card_clicked"):
            win._on_card_clicked("spots")
        app.processEvents()
        screen = getattr(win, "spots_commercials", None)
        if screen is None:
            pix = win.grab()
        else:
            _drive(screen)
            app.processEvents()
            # For breadcrumb scenario, grab the control panel instead
            if scenario == "breadcrumb":
                cp = getattr(win, "control_panel", None)
                target = cp if cp is not None else screen
            else:
                target = screen
            target.repaint()
            app.processEvents()
            pix = target.grab(QRect(0, 0, 1440, 900))
        ok = pix.save(out, "PNG")
        print(f"saved: {out}  ({pix.width()}×{pix.height()})  ok={ok}")
        app.quit()

    QTimer.singleShot(700, _capture)
    rc = app.exec()
    bass_free()
    sys.exit(rc)


if __name__ == "__main__":
    main()
