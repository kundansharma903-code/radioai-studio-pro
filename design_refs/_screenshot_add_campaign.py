"""Screenshot harness for the Add Campaign dialog (Figma 100:2).

Scenarios:
    empty   — dialog as it opens (defaults populated, save disabled)  → 06_empty
    filled  — dialog with sample data + 1 audio file queued           → 07_filled
    saved   — Library after Save (new campaign in row + selected)     → 08_saved
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
    "empty":   "spots_06_dialog_empty.png",
    "filled":  "spots_07_dialog_filled.png",
    "saved":   "spots_08_after_save.png",
    "savedv2": "spots_library_after_save_v2.png",
}


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "empty"
    out_name = SCENARIOS.get(scenario, "spots_dialog_built.png")

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

    # State holder across closures
    state = {"dialog": None, "saved_id": None}

    def _open_dialog_via_real_flow(screen):
        """Mimic the real user click on '+ Add Campaign' — same code path,
        same signal connections. Intercepts the dialog's exec() to grab a
        reference for screenshot driving."""
        from ui.dialogs.add_campaign_dialog import AddCampaignDialog
        original_exec = AddCampaignDialog.exec

        def _spy_exec(self):
            state["dialog"] = self
            self.show()
            app.processEvents()
            return 1   # accepted-ish; we drive the result manually below

        AddCampaignDialog.exec = _spy_exec
        try:
            screen._on_add_campaign()   # real entry point, real signal wiring
        finally:
            AddCampaignDialog.exec = original_exec
        return state["dialog"]

    def _drive(screen):
        if scenario == "empty":
            _open_dialog_via_real_flow(screen)
            return

        if scenario == "filled":
            dlg = _open_dialog_via_real_flow(screen)
            dlg._title_input.setText("AcmeCorp Holiday Push")
            dlg._on_title_changed("AcmeCorp Holiday Push")
            dlg._ad_company_input.setText("AcmeCorp Marketing")
            dlg._client_input.setText("AcmeCorp")
            dlg._media_shop_input.setText("ZenithAds Pvt Ltd")
            dlg._cost_input.setText("25,000.00")
            dlg._end_date_input.setText("31 Dec 2026")
            dlg._on_type_selected("Sponsor")
            if dlg._files_panel:
                dlg._files_panel.add_file(
                    "C:/Audio/AcmeCorp_Holiday_30sec.mp3")
            dlg._comments_input.setPlainText(
                "End-of-year sponsorship push for AcmeCorp's flagship "
                "product line. Run during prime time slots.")
            dlg.repaint()
            app.processEvents()
            return

        if scenario in ("saved", "savedv2"):
            # Open via real flow (signal already connected), fill,
            # then call _on_save() — which emits campaign_saved →
            # screen._on_campaign_saved → reload + select.
            dlg = _open_dialog_via_real_flow(screen)
            dlg._title_input.setText("AcmeCorp Holiday Push")
            dlg._on_title_changed("AcmeCorp Holiday Push")
            dlg._on_type_selected("Sponsor")
            dlg._end_date_input.setText("31 Dec 2026")
            dlg.campaign_saved.connect(
                lambda cid: state.update(saved_id=cid))
            dlg._on_save()
            app.processEvents()
            return

    def _capture():
        try:
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

            print("[harness] driving scenario...")
            _drive(screen)
            print("[harness] drive complete, processing events...")
            app.processEvents()
        except Exception as ex:
            import traceback
            print(f"[harness] EXCEPTION in _capture: {ex}")
            traceback.print_exc()
            app.quit()
            return

        # Pick the right thing to grab. For 'saved' / 'savedv2' the library
        # is the subject (dialog has closed); for others the dialog is.
        is_library_shot = scenario in ("saved", "savedv2")
        target = (state["dialog"] if not is_library_shot and state["dialog"]
                  else screen)
        target.repaint()
        app.processEvents()
        if target is screen:
            pix = target.grab(QRect(0, 0, 1440, 900))
        else:
            # Dialog grab — its frame size may be smaller than the design.
            # Render the WHOLE main window underneath and overlay.
            from PyQt6.QtGui import QPixmap
            base = screen.grab(QRect(0, 0, 1440, 900))
            from PyQt6.QtGui import QPainter as _QP
            painter = _QP(base)
            dlg = target
            dlg_pix = dlg.grab()
            # Center the dialog over the screen
            x = (1440 - dlg_pix.width()) // 2
            y = (900 - dlg_pix.height()) // 2
            painter.drawPixmap(x, y, dlg_pix)
            painter.end()
            pix = base
        ok = pix.save(out, "PNG")
        print(f"saved: {out}  ({pix.width()}×{pix.height()})  ok={ok}")
        if state.get("saved_id"):
            print(f"campaign saved id={state['saved_id']}")
        app.quit()

    QTimer.singleShot(800, _capture)
    rc = app.exec()
    bass_free()
    sys.exit(rc)


if __name__ == "__main__":
    main()
