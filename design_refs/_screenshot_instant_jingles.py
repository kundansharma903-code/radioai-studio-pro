"""Headless screenshot harness for the Instant Jingles screen.

Boots the full app, switches to InstantJingles, optionally drives a scenario
(right-click a pad, assign audio, stop all), and grabs a 1440×900 PNG.

Run from project root:
    py design_refs/_screenshot_instant_jingles.py [scenario]

Scenarios:
    default   — empty editor (default first load)            → 01_default.png
    edit      — right-click N28, editor populated            → 02_editor.png
    assigned  — pad N28 with a fake audio file               → 03_assigned.png
    stopped   — after Stop All click                         → 04_stopped.png
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


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "default"
    out_name = {
        "default":  "instant_jingles_01_default.png",
        "edit":     "instant_jingles_02_editor.png",
        "assigned": "instant_jingles_03_assigned.png",
        "stopped":  "instant_jingles_04_stopped.png",
    }.get(scenario, "instant_jingles_built.png")

    app = QApplication(sys.argv)
    _load_fonts()
    _load_qss(app)
    bass_init()

    db = Database()
    db.verify()

    from ui.main_window import MainWindow
    win = MainWindow(db=db, db_ok=True, song_count=0)
    win.show()

    out = os.path.join(ROOT, "design_refs", out_name)

    def _drive_scenario(ij):
        """Apply scenario-specific UI state. Runs in the Qt event loop."""
        if scenario == "default":
            return  # nothing extra — first pad already auto-selected

        # Find a target pad — N28 is row 1 col 3 → pad_index=3 in seed
        target_pad = next(
            (p for p in ij._pads if p.get("pad_index") == 3),
            None
        )
        if not target_pad:
            print("scenario: target pad not found")
            return

        if scenario == "edit":
            # Simulate a right-click on N28: select + populate the editor
            ij._select_pad(target_pad["id"])
            ij._refresh_editor()
            return

        if scenario == "assigned":
            # Wire a fake audio path so the pad shows file/duration in editor.
            # Pick any real song file from the songs library so duration probe
            # actually returns a value.
            row = db._conn().execute(
                "SELECT file_path FROM songs "
                "WHERE file_path IS NOT NULL AND file_path != '' "
                "LIMIT 1"
            ).fetchone()
            file_path = row["file_path"] if row else "C:/temp/fake.mp3"
            duration_ms = 2200  # 02.2s like the Figma reference
            try:
                db.assign_audio_to_pad(target_pad["id"], file_path, duration_ms)
            except Exception as e:
                print(f"assign failed: {e}")
            ij._load_pads(ij._selected_pallet_id)
            ij._select_pad(target_pad["id"])
            ij._refresh_editor()
            return

        if scenario == "stopped":
            # Pretend a couple of pads were playing, then Stop All
            ij._select_pad(target_pad["id"])
            ij._refresh_editor()
            ij._on_stop_all()
            return

    def _capture_and_quit():
        if hasattr(win, "_on_card_clicked"):
            win._on_card_clicked("instant_jingles")
        app.processEvents()
        ij = getattr(win, "instant_jingles", None)
        if ij is None:
            pix = win.grab()
        else:
            _drive_scenario(ij)
            app.processEvents()
            ij.repaint()
            app.processEvents()
            pix = ij.grab(QRect(0, 0, 1440, 900))
        ok = pix.save(out, "PNG")
        print(f"saved: {out}  ({pix.width()}×{pix.height()})  ok={ok}")
        app.quit()

    QTimer.singleShot(700, _capture_and_quit)
    rc = app.exec()
    bass_free()
    sys.exit(rc)


if __name__ == "__main__":
    main()
