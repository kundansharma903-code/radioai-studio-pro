"""Phase D checkpoint screenshots for the Date Picker dialog.

Three scenarios per the user's checkpoint request:
    default     → Add Campaign open + picker open (Start Date), no manual select
    today_selected → after clicking 'Today' quick-select, dialog stays open
    after_ok    → after OK, picker closed, Add Campaign Start Date populated

All output saved to E:\\RadioAI_v2\\screenshots with the exact names the
checkpoint asked for.
"""

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


SCENARIOS = {
    "default":         "spots_datepicker_default.png",
    "today_selected":  "spots_datepicker_today_selected.png",
    "after_ok":        "spots_datepicker_after_ok.png",
}


def _composite(base_widget, overlays: list):
    """Stack widgets bottom-up onto a single 1440×900 pixmap. Each overlay
    is centered horizontally + at 1/4 from the top (matches BaseDialog placement)."""
    base = base_widget.grab(QRect(0, 0, 1440, 900))
    painter = QPainter(base)
    for w in overlays:
        if w is None:
            continue
        pix = w.grab()
        x = (1440 - pix.width()) // 2
        y = max(50, (900 - pix.height()) // 2)
        painter.drawPixmap(x, y, pix)
    painter.end()
    return base


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "default"
    out_name = SCENARIOS.get(scenario, "spots_datepicker_default.png")

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

    state = {"add": None, "picker": None}

    def _open_add_campaign(screen):
        """Mimic the user clicking '+ Add Campaign'."""
        from ui.dialogs.add_campaign_dialog import AddCampaignDialog
        original_exec = AddCampaignDialog.exec

        def _spy_exec(self):
            state["add"] = self
            self.show()
            app.processEvents()
            return 1

        AddCampaignDialog.exec = _spy_exec
        try:
            screen._on_add_campaign()
        finally:
            AddCampaignDialog.exec = original_exec
        return state["add"]

    def _open_picker(add_dlg, mode="start"):
        """Mimic the user clicking the '...' button on Start/Expire Date."""
        from ui.dialogs.campaign_date_picker_dialog import CampaignDatePickerDialog
        original_exec = CampaignDatePickerDialog.exec

        def _spy_exec(self):
            state["picker"] = self
            self.show()
            app.processEvents()
            return 1

        CampaignDatePickerDialog.exec = _spy_exec
        try:
            add_dlg._stub_picker(
                "Start Date" if mode == "start" else "Expire Date")
        finally:
            CampaignDatePickerDialog.exec = original_exec
        return state["picker"]

    def _capture():
        if hasattr(win, "_on_card_clicked"):
            win._on_card_clicked("spots")
        app.processEvents()
        screen = getattr(win, "spots_commercials", None) or win

        add_dlg = _open_add_campaign(screen)
        app.processEvents()

        # Set Start Date to May 15 so the picker opens with a non-today
        # selection. This makes the difference between 'default' and
        # 'today_selected' visible — otherwise both look identical because
        # AddCampaignDialog's defaults pre-select today.
        if add_dlg._start_date_input:
            add_dlg._start_date_input.setText("15 May 2026")

        if scenario == "after_ok":
            picker = _open_picker(add_dlg, mode="start")
            app.processEvents()
            picker._on_day_picked(QDate(2026, 5, 22))
            picker._on_ok()
            app.processEvents()
            pix = _composite(screen, [add_dlg])
        else:
            picker = _open_picker(add_dlg, mode="start")
            app.processEvents()
            if scenario == "today_selected":
                picker._pick_today()
                app.processEvents()
            picker.repaint()
            app.processEvents()
            pix = _composite(screen, [add_dlg, picker])

        ok = pix.save(out, "PNG")
        print(f"saved: {out}  ({pix.width()}×{pix.height()})  ok={ok}")
        if scenario == "after_ok" and add_dlg._start_date_input:
            print(f"start_date input value: {add_dlg._start_date_input.text()!r}")
        app.quit()

    QTimer.singleShot(900, _capture)
    rc = app.exec()
    bass_free()
    sys.exit(rc)


if __name__ == "__main__":
    main()
