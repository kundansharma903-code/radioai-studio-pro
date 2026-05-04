"""Minimal smoke test — construct dialog, grab pixmap, save, exit."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force unbuffered stdout
sys.stdout.reconfigure(line_buffering=True)

from PyQt6.QtCore import QTimer, QRect
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase

import logging
logging.basicConfig(level=logging.INFO, force=True)

print("[1] starting", flush=True)
from core.audio_engine import bass_init
from core.database import Database

app = QApplication(sys.argv)
print("[2] QApplication created", flush=True)

# Load fonts
fonts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "assets", "fonts")
for fname in os.listdir(fonts_dir):
    if fname.lower().endswith(".ttf"):
        QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname))
print("[3] fonts loaded", flush=True)

bass_init()
print("[4] bass init", flush=True)
db = Database()
print("[5] db ready", flush=True)
db._ensure_campaign_schedule_columns()
print("[6] migration done", flush=True)

from ui.dialogs.spot_programming_dialog import SpotProgrammingDialog
print("[7] imported", flush=True)

dlg = SpotProgrammingDialog(db=db, campaign_id=1, campaign_name="Test")
print(f"[8] constructed: {dlg.size()}, grid={dlg._grid.size()}", flush=True)

dlg.show()
print("[9] shown", flush=True)
app.processEvents()
print("[10] events processed", flush=True)

pix = dlg.grab()
print(f"[11] grabbed: {pix.width()}x{pix.height()}", flush=True)

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "screenshots", "_spotprog_minimal.png")
ok = pix.save(out, "PNG")
print(f"[12] saved={ok} → {out}", flush=True)

app.quit()
print("[13] done", flush=True)
