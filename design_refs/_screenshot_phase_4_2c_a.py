"""Phase 4.2c-A checkpoint screenshots — Edit Campaign feature.

Three scenarios:
    sidebar       — Library showing 5-button sidebar with Edit Campaign
    edit_dialog   — Edit Campaign dialog populated with FreshBurst data
    after_edit    — Library after editing FreshBurst priority High → Medium
"""

import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import QTimer, QRect
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
    "sidebar":     "phase_4_2c_a_01_sidebar.png",
    "edit_dialog": "phase_4_2c_a_02_edit_dialog.png",
    "after_edit":  "phase_4_2c_a_03_after_edit.png",
}


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "sidebar"
    out_name = SCENARIOS.get(scenario, "phase_4_2c_a_built.png")

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

    # Demo target: FreshBurst Cola — Summer (id=1, original priority='High')
    DEMO_ID = 1

    state = {"dialog": None}

    def _open_edit_dialog(screen, campaign_id: int):
        from ui.dialogs.add_campaign_dialog import AddCampaignDialog
        original_exec = AddCampaignDialog.exec

        def _spy_exec(self):
            state["dialog"] = self
            self.show()
            app.processEvents()
            return 1

        AddCampaignDialog.exec = _spy_exec
        try:
            screen._on_edit_campaign(campaign_id)
        finally:
            AddCampaignDialog.exec = original_exec
        return state["dialog"]

    def _drive(screen):
        if scenario == "sidebar":
            # Just show the Library — sidebar visible
            return

        if scenario == "edit_dialog":
            screen._select_campaign(DEMO_ID)
            _open_edit_dialog(screen, DEMO_ID)
            return

        if scenario == "after_edit":
            # Snapshot original priority so we can restore at end
            row = db.get_campaign(DEMO_ID)
            original_priority = row.get("priority") if row else None
            try:
                # Simulate user editing: change priority High → Medium
                screen._select_campaign(DEMO_ID)
                dlg = _open_edit_dialog(screen, DEMO_ID)
                # Set priority dropdown to Medium
                idx = dlg._priority_combo.findText("Medium")
                if idx >= 0:
                    dlg._priority_combo.setCurrentIndex(idx)
                # Click Save (Update Campaign)
                dlg._on_save()
                app.processEvents()
                # Library should now show Medium priority for this row
                screen._select_campaign(DEMO_ID)
                screen._refresh_detail_panel()
            finally:
                # Restore original priority so this scenario is idempotent
                if original_priority:
                    db.update_campaign(DEMO_ID, {"priority": original_priority})
            return

    def _capture():
        if hasattr(win, "_on_card_clicked"):
            win._on_card_clicked("spots")
        app.processEvents()
        screen = getattr(win, "spots_commercials", None)
        if screen is None:
            pix = win.grab()
            pix.save(out, "PNG")
            print(f"saved (fallback): {out}")
            app.quit()
            return

        _drive(screen)
        app.processEvents()
        screen.repaint()
        app.processEvents()

        # Composite — for edit_dialog scenario, overlay the dialog on Library
        if scenario == "edit_dialog" and state["dialog"] is not None:
            base = screen.grab(QRect(0, 0, 1440, 900))
            painter = QPainter(base)
            dlg_pix = state["dialog"].grab()
            x = (1440 - dlg_pix.width()) // 2
            y = max(50, (900 - dlg_pix.height()) // 2)
            painter.drawPixmap(x, y, dlg_pix)
            painter.end()
            pix = base
        else:
            pix = screen.grab(QRect(0, 0, 1440, 900))

        ok = pix.save(out, "PNG")
        print(f"saved: {out}  ({pix.width()}×{pix.height()})  ok={ok}")
        app.quit()

    QTimer.singleShot(900, _capture)
    rc = app.exec()
    bass_free()
    sys.exit(rc)


if __name__ == "__main__":
    main()
