"""Phase 5-A checkpoint screenshot — Audio Cue Editor skeleton."""

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


def main():
    app = QApplication(sys.argv)
    _load_fonts()
    _load_qss(app)
    bass_init()

    db = Database()
    db.verify()
    db._ensure_song_cue_columns()

    from ui.main_window import MainWindow
    win = MainWindow(db=db, db_ok=True, song_count=0)
    win.show()

    out = os.path.join(ROOT, "screenshots", "audio_cue_editor_markers.png")

    state = {"dialog": None}

    def _open_cue_editor(library, song_id):
        from ui.dialogs.audio_cue_editor_dialog import AudioCueEditorDialog
        original_exec = AudioCueEditorDialog.exec
        def _spy_exec(self):
            state["dialog"] = self
            self.show()
            app.processEvents()
            return 1
        AudioCueEditorDialog.exec = _spy_exec
        try:
            library._open_cue_editor()  # uses self._selected_id
        finally:
            AudioCueEditorDialog.exec = original_exec
        return state["dialog"]

    def _capture():
        if hasattr(win, "_on_card_clicked"):
            win._on_card_clicked("songs")
        app.processEvents()
        library = getattr(win, "songs_library", None)
        if library is None:
            pix = win.grab()
            pix.save(out, "PNG")
            print(f"saved (fallback): {out}")
            app.quit()
            return

        # Pick the first available song so duration_ms / file_path / etc.
        # are deterministic. _all_songs is the loaded list.
        if library._all_songs:
            target = library._all_songs[0]
            library._select_song(target["id"])
            app.processEvents()
            _open_cue_editor(library, target["id"])
            app.processEvents()

        library.repaint()
        app.processEvents()

        # Composite dialog over Library
        if state["dialog"] is not None:
            base = library.grab(QRect(0, 0, 1440, 900))
            painter = QPainter(base)
            dlg_pix = state["dialog"].grab()
            x = (1440 - dlg_pix.width()) // 2
            y = max(50, (900 - dlg_pix.height()) // 2)
            painter.drawPixmap(x, y, dlg_pix)
            painter.end()
            pix = base
        else:
            pix = library.grab(QRect(0, 0, 1440, 900))

        ok = pix.save(out, "PNG")
        print(f"saved: {out}  ({pix.width()}×{pix.height()})  ok={ok}")
        app.quit()

    QTimer.singleShot(900, _capture)
    rc = app.exec()
    bass_free()
    sys.exit(rc)


if __name__ == "__main__":
    main()
