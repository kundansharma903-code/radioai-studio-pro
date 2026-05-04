"""Screenshot harness for the Campaign Date Picker dialog (Figma 101:2)."""

import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import QTimer, QRect, QDate
from PyQt6.QtGui import QFontDatabase, QPainter
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


# Scenario picks which dialog state to render.
SCENARIOS = {
    "expire":  ("expire", "spots_09_datepicker_expire.png"),
    "start":   ("start",  "spots_10_datepicker_start.png"),
}


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "expire"
    mode, out_name = SCENARIOS.get(scenario, SCENARIOS["expire"])

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

    state = {"dialog": None}

    def _capture():
        if hasattr(win, "_on_card_clicked"):
            win._on_card_clicked("spots")
        app.processEvents()
        screen = getattr(win, "spots_commercials", None)

        from ui.dialogs.campaign_date_picker_dialog import CampaignDatePickerDialog
        # Date matching the Figma reference: April 27 selected
        initial = QDate(2026, 4, 27)
        min_date = QDate(2026, 4, 10)
        dlg = CampaignDatePickerDialog(
            mode=mode, min_date=min_date, initial=initial,
            parent=screen if screen else win)
        # Force the view month to April 2026 so the screenshot matches Figma
        dlg._view_month = QDate(2026, 4, 1)
        dlg._refresh()
        dlg.show()
        app.processEvents()
        state["dialog"] = dlg

        dlg.repaint()
        app.processEvents()

        # Composite the dialog over the library so the modal feel is preserved
        base = (screen if screen else win).grab(QRect(0, 0, 1440, 900))
        painter = QPainter(base)
        dlg_pix = dlg.grab()
        x = (1440 - dlg_pix.width()) // 2
        y = (900 - dlg_pix.height()) // 2
        painter.drawPixmap(x, y, dlg_pix)
        painter.end()
        ok = base.save(out, "PNG")
        print(f"saved: {out}  ({base.width()}×{base.height()})  ok={ok}")
        app.quit()

    QTimer.singleShot(700, _capture)
    rc = app.exec()
    bass_free()
    sys.exit(rc)


if __name__ == "__main__":
    main()
