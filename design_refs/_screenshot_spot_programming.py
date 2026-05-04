"""Phase E checkpoint screenshots for the Spot Programming dialog."""

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
    "default":     "spots_programming_default.png",
    "drag_select": "spots_programming_drag_select.png",
    "with_breaks": "spots_programming_with_breaks.png",
    "after_save":  "spots_programming_after_save.png",
}


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "default"
    out_name = SCENARIOS.get(scenario, "spots_programming_default.png")

    app = QApplication(sys.argv)
    _load_fonts()
    _load_qss(app)
    bass_init()

    db = Database()
    db.verify()
    # Ensure schema is up to date
    db._ensure_campaign_schedule_columns()

    from ui.main_window import MainWindow
    win = MainWindow(db=db, db_ok=True, song_count=0)
    win.show()

    out = os.path.join(ROOT, "screenshots", out_name)

    # Use FreshBurst Cola — Summer (campaign id=1) as the demo target
    DEMO_CAMPAIGN_ID = 1

    state = {"dialog": None}

    def _open_dialog(parent_widget, with_breaks=False):
        from ui.dialogs.spot_programming_dialog import SpotProgrammingDialog
        original_exec = SpotProgrammingDialog.exec

        def _spy_exec(self):
            state["dialog"] = self
            self.show()
            app.processEvents()
            return 1

        SpotProgrammingDialog.exec = _spy_exec
        try:
            dlg = SpotProgrammingDialog(
                db=db,
                campaign_id=DEMO_CAMPAIGN_ID,
                campaign_name="FreshBurst Cola — Summer",
                parent=parent_widget,
            )
            dlg.show()
            app.processEvents()
            state["dialog"] = dlg
        finally:
            SpotProgrammingDialog.exec = original_exec
        return state["dialog"]

    def _drive(screen):
        # Clear any existing schedule on this demo campaign to start clean
        # (except for the with_breaks / after_save scenarios where we
        # populate it ourselves)
        if scenario == "default":
            try:
                db.update_break_schedule(DEMO_CAMPAIGN_ID, [])
            except Exception:
                pass
            _open_dialog(screen)
            return

        if scenario == "drag_select":
            try:
                db.update_break_schedule(DEMO_CAMPAIGN_ID, [])
            except Exception:
                pass
            dlg = _open_dialog(screen)
            # Simulate a drag-select rectangle in the grid:
            # Mon col, slots 36..42 (06:00..07:00) AND Tue col, slots 36..42
            # Direct manipulation of grid state for screenshot purposes
            grid = dlg._grid
            for d in (0, 1):
                for s in range(36, 43):
                    grid._selected.add((d, s))
            grid._drag_start = (0, 36)
            grid._drag_end = (1, 42)
            grid.update()
            # Scroll the grid so the selection is visible (scroll to ~6am area)
            from ui.dialogs.spot_programming_dialog import HEADER_H, CELL_H
            target_y = HEADER_H + 36 * CELL_H - 100
            dlg._scroll.verticalScrollBar().setValue(max(0, target_y))
            dlg._count_display.set_count(grid.selected_count())
            return

        if scenario in ("with_breaks", "after_save"):
            # Pre-populate via Apply button to test full flow
            dlg = _open_dialog(screen)
            grid = dlg._grid
            # Add breaks of varying priorities
            from ui.dialogs.spot_programming_dialog import _time_to_slot
            preset_data = [
                # day, time, priority
                (0, "06:00", "High"), (0, "09:00", "High"),
                (0, "12:00", "Medium"), (0, "17:00", "High"),
                (1, "06:00", "High"), (1, "12:00", "Medium"),
                (1, "17:00", "High"),
                (2, "08:00", "Medium"), (2, "13:00", "Low"),
                (3, "07:00", "Medium"), (3, "18:00", "High"),
                (4, "06:00", "High"), (4, "12:00", "Medium"),
                (4, "17:30", "High"),
                (5, "10:00", "Low"),
                (6, "11:00", "Low"),
            ]
            breaks = {}
            for (d, t, p) in preset_data:
                slot = _time_to_slot(t)
                if slot is not None:
                    breaks[(d, slot)] = {"priority": p}
            grid.set_breaks(breaks)
            # Scroll to the first break (~06:00 = slot 36)
            from ui.dialogs.spot_programming_dialog import HEADER_H, CELL_H
            target_y = HEADER_H + 36 * CELL_H - 100
            dlg._scroll.verticalScrollBar().setValue(max(0, target_y))
            dlg._count_display.set_count(len(breaks))

            if scenario == "after_save":
                # Click Apply Schedule, capture the LIBRARY (dialog closes)
                dlg._on_apply()
                # Switch screen back to the Library so detail panel
                # weekly grid reflects the saved data
                screen._select_campaign(DEMO_CAMPAIGN_ID)
                screen._refresh_detail_panel()
                state["dialog"] = None
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

        # For after_save we want the library, not the dialog (dialog closed)
        if scenario == "after_save" or state["dialog"] is None:
            pix = screen.grab(QRect(0, 0, 1440, 900))
        else:
            # Composite dialog over library
            base = screen.grab(QRect(0, 0, 1440, 900))
            painter = QPainter(base)
            dlg_pix = state["dialog"].grab()
            x = (1440 - dlg_pix.width()) // 2
            y = max(50, (900 - dlg_pix.height()) // 2)
            painter.drawPixmap(x, y, dlg_pix)
            painter.end()
            pix = base
        ok = pix.save(out, "PNG")
        print(f"saved: {out}  ({pix.width()}×{pix.height()})  ok={ok}")
        app.quit()

    QTimer.singleShot(900, _capture)
    rc = app.exec()
    bass_free()
    sys.exit(rc)


if __name__ == "__main__":
    main()
