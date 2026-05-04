"""
RadioAI Studio Pro — Mass Import Songs Dialog
Figma node 112:2 (1000×700).

Bulk-import songs from a folder. Built on BaseDialog so it adapts to
small screens with a scrollable middle zone.

Pipeline:
  1. Browse → folder picker
  2. Scan  → threaded walk (mutagen ID3 read per file)
  3. Review → checkbox table with status pills (Ready / No Tags / Error)
  4. Import → threaded insert via db.add_song(), with progress bar
"""

import logging
import os
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import (
    Qt, QRectF, QThread, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPainterPath, QFont, QCursor, QLinearGradient,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox,
    QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox, QScrollArea,
)

from ui.widgets._tokens import (
    inter, mono, rgba,
    TEXT_PRI, TEXT_SEC, TEXT_MUTED, TEXT_DIM,
    CYAN, CYAN_LIGHT, GREEN, GREEN_LIGHT, AMBER, AMBER_LIGHT,
    PURPLE, PURPLE_LIGHT, RED, RED_LIGHT,
)
from ui.dialogs.base_dialog import BaseDialog

log = logging.getLogger("MassImportDialog")

INPUT_BG = "#0a0c18"
INPUT_BORDER = "#1c1f38"


# ════════════════════════════════════════════════════════════════════════════
# Threaded folder scanner
# ════════════════════════════════════════════════════════════════════════════

class _ScanWorker(QThread):
    """Walks a folder, reads ID3 tags via mutagen, emits per-file results."""

    file_found = pyqtSignal(dict)
    finished_scan = pyqtSignal(int)

    def __init__(self, folder: str, include_subfolders: bool, formats: List[str], parent=None):
        super().__init__(parent)
        self._folder = folder
        self._include_sub = include_subfolders
        self._formats = [f.lower() for f in formats]
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        files = []
        try:
            if self._include_sub:
                for root, _dirs, fnames in os.walk(self._folder):
                    for f in fnames:
                        if Path(f).suffix.lower() in self._formats:
                            files.append(os.path.join(root, f))
            else:
                for f in os.listdir(self._folder):
                    full = os.path.join(self._folder, f)
                    if os.path.isfile(full) and Path(f).suffix.lower() in self._formats:
                        files.append(full)
        except Exception as exc:
            log.error(f"folder walk failed: {exc}")
            self.finished_scan.emit(0)
            return

        for path in files:
            if self._cancelled:
                break
            self.file_found.emit(self._read_tags(path))

        self.finished_scan.emit(len(files))

    @staticmethod
    def _read_tags(path: str) -> dict:
        """Read ID3 tags via mutagen. Always returns a dict with status."""
        result = {
            "path":     path,
            "filename": os.path.basename(path),
            "artist":   None,
            "title":    None,
            "album":    None,
            "year":     None,
            "bpm":      None,
            "duration_sec": 0,
            "status":   "Error",
        }
        try:
            from mutagen import File as MF
            mf = MF(path)
            if mf is None:
                return result

            # Duration
            if hasattr(mf, "info") and mf.info and hasattr(mf.info, "length"):
                result["duration_sec"] = float(mf.info.length or 0)

            # Tags — handle ID3 (TPE1/TIT2/...) and Vorbis-style ('artist'/'title')
            tags = getattr(mf, "tags", None)
            artist = title = album = year = bpm = None
            if tags is not None:
                def _get(*keys):
                    for k in keys:
                        try:
                            v = tags.get(k) if hasattr(tags, "get") else tags[k] if k in tags else None
                        except Exception:
                            v = None
                        if v:
                            if isinstance(v, list) and v:
                                v = v[0]
                            try:
                                v = str(v).strip()
                            except Exception:
                                continue
                            if v:
                                return v
                    return None

                artist = _get("TPE1", "artist", "ARTIST", "©ART")
                title  = _get("TIT2", "title",  "TITLE",  "©nam")
                album  = _get("TALB", "album",  "ALBUM",  "©alb")
                year_str = _get("TDRC", "date", "TYER", "©day")
                if year_str:
                    try:
                        year = int(str(year_str)[:4])
                    except Exception:
                        year = None
                bpm_str = _get("TBPM", "bpm", "BPM", "tmpo")
                if bpm_str:
                    try:
                        bpm = int(float(bpm_str))
                    except Exception:
                        bpm = None

            result["artist"] = artist
            result["title"]  = title
            result["album"]  = album
            result["year"]   = year
            result["bpm"]    = bpm

            if artist and title:
                result["status"] = "Ready"
            else:
                result["status"] = "No Tags"
        except Exception as exc:
            result["status"] = "Error"
            result["error_message"] = str(exc)
        return result


# ════════════════════════════════════════════════════════════════════════════
# Threaded importer
# ════════════════════════════════════════════════════════════════════════════

class _ImportWorker(QThread):
    """Inserts each selected file as a song row, optionally skipping duplicates."""

    progress = pyqtSignal(int, int)  # (current, total)
    file_done = pyqtSignal(dict)     # song result {path, ok: bool, skipped: bool}
    finished_import = pyqtSignal(int, int, int)  # (added, skipped, errors)

    def __init__(self, db, files: List[dict], defaults: dict,
                 skip_duplicates: bool = True, parent=None):
        super().__init__(parent)
        self._db = db
        self._files = files
        self._defaults = defaults
        self._skip_dups = skip_duplicates
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        added = skipped = errors = 0
        total = len(self._files)
        for i, f in enumerate(self._files, 1):
            if self._cancelled:
                break
            try:
                artist = (f.get("artist") or "").strip()
                title  = (f.get("title") or os.path.splitext(f.get("filename", ""))[0]).strip()
                if not artist:
                    artist = "Unknown Artist"

                if self._skip_dups and self._db.song_exists(artist, title):
                    skipped += 1
                    self.file_done.emit({"path": f["path"], "ok": False, "skipped": True})
                else:
                    duration_ms = int(float(f.get("duration_sec") or 0) * 1000)
                    song = {
                        "title":       title,
                        "artist":      artist,
                        "album":       f.get("album"),
                        "year":        f.get("year") or self._defaults.get("year"),
                        "bpm":         f.get("bpm"),
                        "duration_ms": duration_ms,
                        "file_path":   f.get("path"),
                        "category_id": self._defaults.get("category_id"),
                        "is_enabled":  1 if self._defaults.get("enabled", True) else 0,
                    }
                    self._db.add_song(song)
                    added += 1
                    self.file_done.emit({"path": f["path"], "ok": True, "skipped": False})
            except Exception as exc:
                errors += 1
                log.error(f"import failed for {f.get('path')}: {exc}")
                self.file_done.emit({"path": f.get("path"), "ok": False, "skipped": False, "error": str(exc)})

            self.progress.emit(i, total)

        self.finished_import.emit(added, skipped, errors)


# ════════════════════════════════════════════════════════════════════════════
# Reusable section header strip
# ════════════════════════════════════════════════════════════════════════════

class _StepHeader(QFrame):
    """Section header strip with colored left bar + uppercase label."""

    def __init__(self, text: str, accent_color: str = GREEN, parent=None):
        super().__init__(parent)
        self._text = text.upper()
        self._accent = QColor(accent_color)
        self.setFixedHeight(24)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), 24)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        p.setClipPath(path)
        p.fillRect(rect, QColor("#131626"))
        p.fillRect(0, 0, 3, 24, self._accent)
        p.setClipping(False)
        p.setPen(self._accent)
        p.setFont(inter(10, QFont.Weight.DemiBold, letter_spacing=0.8))
        p.drawText(10, 0, self.width() - 14, 24,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._text)


# ════════════════════════════════════════════════════════════════════════════
# Header logo (32x32 green with download arrow)
# ════════════════════════════════════════════════════════════════════════════

class _ImportHeaderIcon(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, 28, 28), 6, 6)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 28, 28), QColor("#052e16"))
        p.setClipping(False)
        bc = QColor(GREEN); bc.setAlphaF(0.50)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, 27, 27), 6, 6)
        # Download arrow ⬇
        p.setPen(QColor(GREEN))
        p.setFont(inter(15, QFont.Weight.Bold))
        p.drawText(QRectF(0, 0, 28, 28), Qt.AlignmentFlag.AlignCenter, "⬇")


# ════════════════════════════════════════════════════════════════════════════
# Status counter pill (header)
# ════════════════════════════════════════════════════════════════════════════

class _StatusCounter(QFrame):

    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = QColor(color)
        self._value = 0
        self.setFixedSize(94, 24)

    def set_value(self, n: int):
        self._value = n
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 94, 24)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)
        p.fillRect(rect, QColor("#131626"))
        # Left bar
        p.fillRect(0, 0, 2, 24, self._color)
        p.setClipping(False)
        p.setPen(self._color)
        p.setFont(inter(10, QFont.Weight.DemiBold))
        p.drawText(10, 0, 80, 24,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f"{self._value} {self._label}")


# ════════════════════════════════════════════════════════════════════════════
# Custom paint checkbox (small, used in filter row + table rows)
# ════════════════════════════════════════════════════════════════════════════

class _Checkbox(QPushButton):

    toggled_state = pyqtSignal(bool)

    def __init__(self, color: str = GREEN, size: int = 14, parent=None):
        super().__init__("", parent)
        self._color = QColor(color)
        self._checked = False
        self._size = size
        self.setFixedSize(size, size)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFlat(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.clicked.connect(self._toggle)

    def isChecked(self): return self._checked

    def setChecked(self, c: bool):
        self._checked = c
        self.update()

    def _toggle(self):
        self._checked = not self._checked
        self.update()
        self.toggled_state.emit(self._checked)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self._size, self._size)
        path = QPainterPath()
        path.addRoundedRect(rect, 2, 2)
        p.setClipPath(path)
        if self._checked:
            tint = QColor(self._color); tint.setAlphaF(0.20)
            p.fillRect(rect, tint)
            p.setClipping(False)
            bc = QColor(self._color)
            p.setPen(QPen(bc, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, self._size - 1, self._size - 1), 2, 2)
            p.setPen(self._color)
            p.setFont(inter(max(7, self._size - 6), QFont.Weight.Bold))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "✓")
        else:
            p.fillRect(rect, QColor("#252848"))


# ════════════════════════════════════════════════════════════════════════════
# Filter checkbox row (chip-style) — bigger surface for hit-testing
# ════════════════════════════════════════════════════════════════════════════

class _FilterChip(QFrame):

    toggled_state = pyqtSignal(bool)

    def __init__(self, label: str, width: int = 80, checked: bool = True,
                 color: str = GREEN, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = QColor(color)
        self._checked = checked
        self.setFixedSize(width, 24)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def isChecked(self): return self._checked

    def setChecked(self, c: bool):
        self._checked = c
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.update()
            self.toggled_state.emit(self._checked)
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), 24)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        p.setClipPath(path)
        p.fillRect(rect, QColor("#131626"))
        p.setClipping(False)
        bc = QColor(self._color) if self._checked else QColor(INPUT_BORDER)
        if self._checked:
            bc.setAlphaF(0.50)
        p.setPen(QPen(bc, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, 23), 4, 4)
        # Inner check box square
        if self._checked:
            tint = QColor(self._color); tint.setAlphaF(0.20)
            p.setBrush(tint)
            box_bc = QColor(self._color)
            p.setPen(QPen(box_bc, 1))
            p.drawRoundedRect(QRectF(8, 6, 12, 12), 2, 2)
            p.setPen(self._color)
            p.setFont(inter(8, QFont.Weight.Bold))
            p.drawText(QRectF(8, 6, 12, 12), Qt.AlignmentFlag.AlignCenter, "✓")
        else:
            p.setBrush(QColor("#252848"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(8, 6, 12, 12), 2, 2)
        # Label
        p.setPen(QColor(TEXT_SEC) if self._checked else QColor(TEXT_MUTED))
        p.setFont(inter(9))
        p.drawText(26, 0, self.width() - 30, 24,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._label)


# ════════════════════════════════════════════════════════════════════════════
# Status pill (Ready / No Tags / Error)
# ════════════════════════════════════════════════════════════════════════════

_STATUS_COLORS = {
    "Ready":   (GREEN,  "#052e16"),
    "No Tags": (AMBER,  "#2d1a00"),
    "Error":   (RED,    "#1f0a12"),
}


class _StatusPill(QLabel):

    def __init__(self, status: str, parent=None):
        super().__init__(status, parent)
        fg, bg = _STATUS_COLORS.get(status, (TEXT_MUTED, "#1c1f38"))
        self.setFont(inter(8, QFont.Weight.DemiBold))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(70, 16)
        self.setStyleSheet(
            f"QLabel {{ background: {bg}; color: {fg}; border-radius: 3px; }}"
        )


# ════════════════════════════════════════════════════════════════════════════
# File row (700×30)
# ════════════════════════════════════════════════════════════════════════════

class _FileRow(QFrame):

    checkbox_changed = pyqtSignal(bool)

    def __init__(self, file_data: dict, row_index: int, parent=None):
        super().__init__(parent)
        self._data = file_data
        self._row_index = row_index
        self.setFixedSize(700, 30)

        # Background alternation
        self._alt = bool(row_index % 2)

        # Checkbox at x=25
        can_check = (file_data.get("status") == "Ready")
        self._cb = _Checkbox(GREEN, size=12, parent=self)
        self._cb.move(25, 9)
        self._cb.setChecked(can_check)
        self._cb.setEnabled(can_check)
        self._cb.toggled_state.connect(self.checkbox_changed.emit)

    def is_selected(self) -> bool:
        return self._cb.isChecked()

    def set_selected(self, sel: bool):
        if self._cb.isEnabled():
            self._cb.setChecked(sel)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, 700, 30)
        bg = QColor("#0a0c18") if self._alt else QColor("#131626")
        p.fillRect(rect, bg)

        d = self._data
        # Filename column at x=45
        p.setPen(QColor(TEXT_SEC))
        p.setFont(inter(10))
        p.drawText(45, 0, 230, 30,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   d.get("filename", ""))
        # Artist at x=279
        artist = d.get("artist") or ("— Not found" if d.get("status") == "No Tags" else "")
        p.setPen(QColor(TEXT_MUTED) if not d.get("artist") else QColor(TEXT_PRI))
        p.drawText(279, 0, 155, 30,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   artist)
        # Title at x=439
        title = d.get("title") or ("— Not found" if d.get("status") == "No Tags" else "")
        p.setPen(QColor(TEXT_MUTED) if not d.get("title") else QColor(TEXT_PRI))
        p.drawText(439, 0, 130, 30,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   title)
        # Duration at x=574
        dur_s = float(d.get("duration_sec") or 0)
        if dur_s > 0:
            dur_str = f"{int(dur_s) // 60}:{int(dur_s) % 60:02d}"
        else:
            dur_str = "—"
        p.setPen(QColor(TEXT_SEC))
        p.drawText(574, 0, 60, 30,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   dur_str)

        # Status pill at x=635 — paint inline (avoid child widget overhead)
        status = d.get("status") or "Error"
        fg_hex, bg_hex = _STATUS_COLORS.get(status, (TEXT_MUTED, "#1c1f38"))
        pill_bg = QColor(bg_hex)
        p.setBrush(pill_bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(635, 7, 60, 16), 3, 3)
        p.setPen(QColor(fg_hex))
        p.setFont(inter(8, QFont.Weight.DemiBold))
        p.drawText(QRectF(635, 7, 60, 16), Qt.AlignmentFlag.AlignCenter, status)


# ════════════════════════════════════════════════════════════════════════════
# Main dialog
# ════════════════════════════════════════════════════════════════════════════

class MassImportDialog(BaseDialog):

    songs_imported = pyqtSignal(int)  # count of newly added songs

    HEADER_H = 52
    FOOTER_H = 52

    def __init__(self, parent=None, db=None):
        self._db = db
        self._files: List[dict] = []
        self._row_widgets: List[_FileRow] = []
        self._scan_worker: Optional[_ScanWorker] = None
        self._import_worker: Optional[_ImportWorker] = None

        # Refs filled during build
        self._ctr_selected: Optional[_StatusCounter] = None
        self._ctr_ready:    Optional[_StatusCounter] = None
        self._ctr_errors:   Optional[_StatusCounter] = None
        self._path_input:   Optional[QLineEdit] = None
        self._filter_subs:  Optional[_FilterChip] = None
        self._filter_mp3:   Optional[_FilterChip] = None
        self._filter_wav:   Optional[_FilterChip] = None
        self._filter_flac:  Optional[_FilterChip] = None
        self._stats_label:  Optional[QLabel] = None
        self._table_layout: Optional[QVBoxLayout] = None
        self._empty_box:    Optional[QFrame] = None
        # Right column refs
        self._cat_combo:   Optional[QComboBox] = None
        self._era_combo:   Optional[QComboBox] = None
        self._year_combo:  Optional[QComboBox] = None
        self._priority_combo: Optional[QComboBox] = None
        self._skip_dups_chk: Optional[_Checkbox] = None
        self._dup_match_combo: Optional[QComboBox] = None
        self._progress_fill: Optional[QFrame] = None
        self._progress_label: Optional[QLabel] = None
        # Footer ref
        self._import_btn: Optional[QPushButton] = None

        super().__init__(target_size=(1000, 700), parent=parent)

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0a0c18; "
            f"border-bottom: 1px solid #1c1f38; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(13, 10, 10, 10)
        h.setSpacing(10)

        h.addWidget(_ImportHeaderIcon())

        title_box = QWidget(); title_box.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(title_box); tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        title = QLabel("MASS IMPORT SONGS")
        title.setFont(inter(14, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT_PRI}; background: transparent;")
        sub = QLabel("Import multiple songs from a folder — auto-detect ID3 tags")
        sub.setFont(inter(9))
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        tv.addWidget(title); tv.addWidget(sub)
        h.addWidget(title_box)
        h.addStretch()

        # Status counters row
        self._ctr_selected = _StatusCounter("Selected", TEXT_MUTED)
        self._ctr_ready    = _StatusCounter("Ready",    GREEN)
        self._ctr_errors   = _StatusCounter("Errors",   RED)
        h.addWidget(self._ctr_selected)
        h.addWidget(self._ctr_ready)
        h.addWidget(self._ctr_errors)

        # Close ✕
        x = QPushButton("✕")
        x.setFixedSize(30, 30)
        x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x.setFont(inter(13, QFont.Weight.Bold))
        x.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {rgba(RED, 0.20)}; color: {RED_LIGHT}; }}"
        )
        x.clicked.connect(self._on_close)
        h.addWidget(x)
        return f

    # ── Content ───────────────────────────────────────────────────────────

    def _build_content(self) -> QWidget:
        c = QFrame()
        c.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(c)
        outer.setContentsMargins(15, 10, 17, 10)
        outer.setSpacing(8)
        outer.addWidget(self._build_left_column(), stretch=70)
        outer.addWidget(self._build_right_column(), stretch=27)
        return c

    # ── LEFT COLUMN ───────────────────────────────────────────────────────

    def _build_left_column(self) -> QWidget:
        col = QWidget(); col.setStyleSheet("background: transparent;")
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # STEP 1 — SELECT FOLDER
        v.addWidget(_StepHeader("STEP 1 — SELECT FOLDER", accent_color=GREEN))

        # Path row
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self._path_input = QLineEdit()
        self._path_input.setReadOnly(True)
        self._path_input.setFixedHeight(36)
        self._path_input.setFont(inter(11))
        self._path_input.setPlaceholderText(r"C:\Music\Songs\  — No folder selected")
        self._path_input.setStyleSheet(
            f"QLineEdit {{ background: #070812; color: {TEXT_PRI}; "
            f"border: 1px solid {INPUT_BORDER}; border-radius: 6px; "
            f"padding: 0 11px; }}"
        )
        path_row.addWidget(self._path_input, stretch=1)

        browse_btn = QPushButton("📁  Browse")
        browse_btn.setFixedSize(100, 36)
        browse_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        browse_btn.setFont(inter(11, QFont.Weight.DemiBold))
        browse_btn.setStyleSheet(
            f"QPushButton {{ background: #052e16; color: {GREEN}; "
            f"border: 1px solid {rgba(GREEN, 0.40)}; border-left: 2px solid {GREEN}; "
            f"border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {rgba(GREEN, 0.25)}; }}"
        )
        browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(browse_btn)

        scan_btn = QPushButton("🔍  Scan")
        scan_btn.setFixedSize(96, 36)
        scan_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        scan_btn.setFont(inter(11, QFont.Weight.DemiBold))
        scan_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 {PURPLE_LIGHT}, stop:1 {PURPLE}); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:0,y2:1, stop:0 #c4b5fd, stop:1 {PURPLE_LIGHT}); }}"
            f"QPushButton:disabled {{ background: #252848; color: {TEXT_MUTED}; }}"
        )
        scan_btn.clicked.connect(self._on_scan)
        path_row.addWidget(scan_btn)
        v.addLayout(path_row)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._filter_subs = _FilterChip("Include subfolders", width=180, checked=True, color=GREEN)
        self._filter_mp3  = _FilterChip("MP3",  width=80, checked=True, color=GREEN)
        self._filter_wav  = _FilterChip("WAV",  width=80, checked=False, color=GREEN)
        self._filter_flac = _FilterChip("FLAC", width=80, checked=False, color=GREEN)
        filter_row.addWidget(self._filter_subs)
        filter_row.addWidget(self._filter_mp3)
        filter_row.addWidget(self._filter_wav)
        filter_row.addWidget(self._filter_flac)
        helper = QLabel("Auto-detect ID3 tags (Artist, Title, Duration)")
        helper.setFont(inter(9))
        helper.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        filter_row.addWidget(helper)
        filter_row.addStretch()
        v.addLayout(filter_row)

        # STEP 2 — REVIEW FILES
        v.addSpacing(4)
        v.addWidget(_StepHeader("STEP 2 — REVIEW FILES", accent_color=PURPLE_LIGHT))

        # Table header
        thdr = QFrame()
        thdr.setFixedHeight(28)
        thdr.setStyleSheet(f"QFrame {{ background: #131626; }}")
        # Using absolute children for column labels
        for x, text in [(45, "FILENAME"), (279, "ARTIST (from ID3)"),
                         (439, "TITLE (from ID3)"), (574, "DURATION"), (635, "STATUS")]:
            l = QLabel(text, thdr)
            l.setGeometry(x, 0, 200, 28)
            l.setFont(inter(9, QFont.Weight.DemiBold, letter_spacing=0.3))
            l.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(thdr)

        # Table body — scrollable list of _FileRow widgets
        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setFixedHeight(180)
        list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: {rgba('#ffffff', 0.02)}; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {rgba(PURPLE_LIGHT, 0.5)}; "
            f"border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        list_widget = QWidget()
        list_widget.setStyleSheet("background: transparent;")
        self._table_layout = QVBoxLayout(list_widget)
        self._table_layout.setContentsMargins(0, 0, 0, 0)
        self._table_layout.setSpacing(0)
        # Empty-state placeholder lives in the list_widget so it disappears when rows added
        self._empty_box = QFrame()
        self._empty_box.setFixedHeight(60)
        self._empty_box.setStyleSheet(
            f"QFrame {{ background: #070812; border: 1px solid {rgba('#1c1f38', 0.3)}; "
            f"border-radius: 6px; }}"
        )
        ev = QVBoxLayout(self._empty_box); ev.setContentsMargins(0, 0, 0, 0); ev.setSpacing(0)
        empty_lbl = QLabel("📁  Select a folder above to scan for audio files")
        empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lbl.setFont(inter(11))
        empty_lbl.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        ev.addWidget(empty_lbl)
        self._table_layout.addWidget(self._empty_box)
        self._table_layout.addStretch()
        list_scroll.setWidget(list_widget)
        v.addWidget(list_scroll)

        # Bottom action row: Select All / Deselect All / stats
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        sel_all = QPushButton("☑  Select All")
        sel_all.setFixedSize(110, 26)
        sel_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        sel_all.setFont(inter(10, QFont.Weight.Medium))
        sel_all.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        sel_all.clicked.connect(self._on_select_all)
        action_row.addWidget(sel_all)

        desel_all = QPushButton("☐  Deselect All")
        desel_all.setFixedSize(120, 26)
        desel_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        desel_all.setFont(inter(10, QFont.Weight.Medium))
        desel_all.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        desel_all.clicked.connect(self._on_deselect_all)
        action_row.addWidget(desel_all)

        self._stats_label = QLabel("0 files found")
        self._stats_label.setFont(inter(10))
        self._stats_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        action_row.addWidget(self._stats_label)
        action_row.addStretch()
        v.addLayout(action_row)

        v.addStretch()
        return col

    # ── RIGHT COLUMN ──────────────────────────────────────────────────────

    def _build_right_column(self) -> QWidget:
        col = QWidget(); col.setStyleSheet("background: transparent;")
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # STEP 3
        v.addWidget(_StepHeader("STEP 3 — DEFAULT SETTINGS", accent_color=AMBER))

        helper = QLabel("Apply to ALL imported songs:")
        helper.setFont(inter(9, QFont.Weight.Medium))
        helper.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        v.addWidget(helper)

        # Default Category
        l = QLabel("Default Category")
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        v.addWidget(l)
        self._cat_combo = self._make_combo(["Select category..."])
        # Populate from DB
        try:
            cats = self._db.get_categories()
            for c in cats:
                self._cat_combo.addItem(c["name"], c["id"])
        except Exception as exc:
            log.error(f"category load failed: {exc}")
        v.addWidget(self._cat_combo)

        # Era + Year row
        row = QHBoxLayout(); row.setSpacing(8)
        era_col = QWidget(); era_col.setStyleSheet("background: transparent;")
        ev = QVBoxLayout(era_col); ev.setContentsMargins(0, 0, 0, 0); ev.setSpacing(4)
        ev.addWidget(self._sub_label("Default Era"))
        self._era_combo = self._make_combo(["Select...", "60s", "70s", "80s", "90s", "2000s", "2010s", "2020s"])
        ev.addWidget(self._era_combo)
        row.addWidget(era_col, stretch=1)
        from datetime import datetime as _dt
        cur_y = _dt.now().year
        yr_col = QWidget(); yr_col.setStyleSheet("background: transparent;")
        yv = QVBoxLayout(yr_col); yv.setContentsMargins(0, 0, 0, 0); yv.setSpacing(4)
        yv.addWidget(self._sub_label("Year"))
        self._year_combo = self._make_combo(["Select..."] + [str(y) for y in range(cur_y, 1949, -1)])
        self._year_combo.setCurrentText(str(cur_y))
        yv.addWidget(self._year_combo)
        row.addWidget(yr_col, stretch=1)
        v.addLayout(row)

        # Priority + Enabled row
        row = QHBoxLayout(); row.setSpacing(8)
        pr_col = QWidget(); pr_col.setStyleSheet("background: transparent;")
        pv = QVBoxLayout(pr_col); pv.setContentsMargins(0, 0, 0, 0); pv.setSpacing(4)
        pv.addWidget(self._sub_label("Priority"))
        self._priority_combo = self._make_combo([str(i) for i in range(1, 10)])
        pv.addWidget(self._priority_combo)
        row.addWidget(pr_col, stretch=1)
        # Enabled toggle pill
        en_col = QWidget(); en_col.setStyleSheet("background: transparent;")
        env = QVBoxLayout(en_col); env.setContentsMargins(0, 0, 0, 0); env.setSpacing(4)
        env.addWidget(self._sub_label("Enabled"))
        en_pill = QFrame()
        en_pill.setFixedHeight(28)
        en_pill.setStyleSheet(
            f"QFrame {{ background: #052e16; "
            f"border: 1px solid {rgba(GREEN, 0.30)}; border-left: 2px solid {GREEN}; "
            f"border-radius: 6px; }}"
        )
        en_v = QHBoxLayout(en_pill); en_v.setContentsMargins(10, 0, 10, 0); en_v.setSpacing(0)
        en_lbl = QLabel("✓ Yes (Enabled)")
        en_lbl.setFont(inter(10, QFont.Weight.DemiBold))
        en_lbl.setStyleSheet(f"color: {GREEN}; background: transparent;")
        en_v.addWidget(en_lbl)
        env.addWidget(en_pill)
        row.addWidget(en_col, stretch=1)
        v.addLayout(row)

        # DUPLICATE HANDLING section
        v.addSpacing(2)
        v.addWidget(_StepHeader("DUPLICATE HANDLING", accent_color=CYAN))

        # Skip duplicates toggle
        skip_pill = QFrame()
        skip_pill.setFixedHeight(28)
        skip_pill.setStyleSheet(
            f"QFrame {{ background: #083344; "
            f"border: 1px solid {rgba(CYAN, 0.20)}; border-left: 2px solid {CYAN}; "
            f"border-radius: 6px; }}"
        )
        sp_h = QHBoxLayout(skip_pill); sp_h.setContentsMargins(8, 0, 8, 0); sp_h.setSpacing(8)
        self._skip_dups_chk = _Checkbox(CYAN, size=14)
        self._skip_dups_chk.setChecked(True)
        sp_h.addWidget(self._skip_dups_chk)
        sp_lbl = QLabel("Skip duplicate songs")
        sp_lbl.setFont(inter(10, QFont.Weight.Medium))
        sp_lbl.setStyleSheet(f"color: {CYAN}; background: transparent;")
        sp_h.addWidget(sp_lbl); sp_h.addStretch()
        v.addWidget(skip_pill)

        d_helper = QLabel("Duplicate check based on:")
        d_helper.setFont(inter(9))
        d_helper.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(d_helper)
        self._dup_match_combo = self._make_combo(["Artist + Title match", "File path", "Filename"])
        v.addWidget(self._dup_match_combo)

        # ID3 TAG READING checklist
        v.addSpacing(2)
        v.addWidget(_StepHeader("ID3 TAG READING", accent_color=PURPLE_LIGHT))
        id3_box = QFrame()
        id3_box.setFixedHeight(80)
        id3_box.setStyleSheet(
            f"QFrame {{ background: #131626; "
            f"border: 1px solid {INPUT_BORDER}; border-left: 2px solid {PURPLE}; "
            f"border-radius: 8px; }}"
        )
        id3_grid = QHBoxLayout(id3_box)
        id3_grid.setContentsMargins(10, 8, 10, 8); id3_grid.setSpacing(8)
        left_list = QVBoxLayout(); left_list.setSpacing(2); left_list.setContentsMargins(0, 0, 0, 0)
        right_list = QVBoxLayout(); right_list.setSpacing(2); right_list.setContentsMargins(0, 0, 0, 0)
        for txt in ["✓ Artist name", "✓ Duration", "✓ Year"]:
            l = QLabel(txt); l.setFont(inter(9))
            l.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")
            left_list.addWidget(l)
        for txt in ["✓ Song title", "✓ Album", "✓ BPM (if tagged)"]:
            l = QLabel(txt); l.setFont(inter(9))
            l.setStyleSheet(f"color: {PURPLE_LIGHT}; background: transparent;")
            right_list.addWidget(l)
        id3_grid.addLayout(left_list, stretch=1)
        id3_grid.addLayout(right_list, stretch=1)
        v.addWidget(id3_box)

        # IMPORT PROGRESS section
        v.addSpacing(2)
        v.addWidget(_StepHeader("IMPORT PROGRESS", accent_color=GREEN))

        # Progress track
        track = QFrame()
        track.setFixedHeight(16)
        track.setStyleSheet(
            f"QFrame {{ background: #1c1f38; border-radius: 8px; }}"
        )
        # Inner fill widget (width 0 initially, grows)
        self._progress_fill = QFrame(track)
        self._progress_fill.setGeometry(0, 0, 0, 16)
        self._progress_fill.setStyleSheet(
            f"QFrame {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {GREEN}, stop:1 {CYAN}); "
            f"border-radius: 8px; }}"
        )
        v.addWidget(track)

        self._progress_label = QLabel("Ready to import — 0%")
        self._progress_label.setFont(inter(9))
        self._progress_label.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        v.addWidget(self._progress_label)

        v.addStretch()
        return col

    def _sub_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setFont(inter(9, QFont.Weight.Medium))
        l.setStyleSheet(f"color: {TEXT_SEC}; background: transparent;")
        return l

    def _make_combo(self, items: list, height: int = 28) -> QComboBox:
        c = QComboBox(); c.addItems(items); c.setFixedHeight(height); c.setFont(inter(11))
        c.setStyleSheet(
            f"QComboBox {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
            f"border: 1px solid {INPUT_BORDER}; border-radius: 6px; "
            f"padding: 0 24px 0 11px; }}"
            f"QComboBox:focus {{ border-color: {CYAN}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox::down-arrow {{ image: none; width: 0; height: 0; "
            f"border-left: 4px solid transparent; border-right: 4px solid transparent; "
            f"border-top: 5px solid {TEXT_MUTED}; margin-right: 6px; }}"
            f"QComboBox QAbstractItemView {{ background: {INPUT_BG}; color: {TEXT_PRI}; "
            f"border: 1px solid {INPUT_BORDER}; border-radius: 5px; "
            f"selection-background-color: {rgba(CYAN, 0.20)}; selection-color: {CYAN_LIGHT}; "
            f"outline: none; padding: 4px; }}"
        )
        return c

    # ── Footer ────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame {{ background: #0a0c18; border-top: 1px solid #1c1f38; }}"
        )
        h = QHBoxLayout(f)
        h.setContentsMargins(15, 11, 15, 11); h.setSpacing(10)

        warn = QLabel(
            "*  Songs with errors will be skipped. "
            "Songs without ID3 tags will need manual edit after import."
        )
        warn.setFont(inter(9))
        warn.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        h.addWidget(warn)
        h.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setFixedSize(90, 30)
        cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel.setFont(inter(11, QFont.Weight.Medium))
        cancel.setStyleSheet(
            f"QPushButton {{ background: #1c1f38; color: {TEXT_SEC}; "
            f"border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: #252848; color: {TEXT_PRI}; }}"
        )
        cancel.clicked.connect(self._on_close)
        h.addWidget(cancel)

        self._import_btn = QPushButton("⬇  Import Selected (0)")
        self._import_btn.setFixedSize(180, 30)
        self._import_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._import_btn.setFont(inter(11, QFont.Weight.DemiBold))
        self._import_btn.setEnabled(False)
        self._import_btn.setStyleSheet(
            f"QPushButton {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {GREEN}, stop:1 {CYAN}); "
            f"color: white; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {GREEN_LIGHT}, stop:1 {CYAN_LIGHT}); }}"
            f"QPushButton:disabled {{ background: #252848; color: {TEXT_MUTED}; }}"
        )
        self._import_btn.clicked.connect(self._on_import)
        h.addWidget(self._import_btn)
        return f

    # ── Behavior ──────────────────────────────────────────────────────────

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Music Folder", os.path.expanduser("~"),
        )
        if folder:
            self._path_input.setText(folder)
            # Clear table from previous scan
            self._clear_table()

    def _on_scan(self):
        folder = self._path_input.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, "No folder",
                                    "Click Browse first to select a folder, then Scan.")
            return

        # Cancel prior scan if running
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self._scan_worker.wait()

        # Build format list from chips
        formats = []
        if self._filter_mp3.isChecked():  formats.append(".mp3")
        if self._filter_wav.isChecked():  formats.append(".wav")
        if self._filter_flac.isChecked(): formats.append(".flac")
        if not formats:
            QMessageBox.information(self, "No formats",
                                    "Tick at least one audio format (MP3 / WAV / FLAC).")
            return

        self._clear_table()

        worker = _ScanWorker(folder, self._filter_subs.isChecked(), formats)
        worker.file_found.connect(self._on_file_found)
        worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker = worker
        worker.start()

        if self._stats_label:
            self._stats_label.setText("Scanning...")

    def _on_file_found(self, file_data: dict):
        self._files.append(file_data)
        # Hide empty box on first row
        if self._empty_box and self._empty_box.isVisible():
            self._empty_box.hide()
        row = _FileRow(file_data, len(self._row_widgets))
        row.checkbox_changed.connect(self._update_counters)
        self._table_layout.insertWidget(self._table_layout.count() - 1, row)
        self._row_widgets.append(row)
        self._update_counters()

    def _on_scan_finished(self, total: int):
        self._update_counters()
        if total == 0:
            QMessageBox.information(self, "No files",
                                    "No matching audio files found in that folder.")

    def _clear_table(self):
        self._files.clear()
        for w in self._row_widgets:
            w.setParent(None); w.deleteLater()
        self._row_widgets.clear()
        if self._empty_box:
            self._empty_box.show()
        self._update_counters()

    def _on_select_all(self):
        for r in self._row_widgets:
            r.set_selected(True)
        self._update_counters()

    def _on_deselect_all(self):
        for r in self._row_widgets:
            r.set_selected(False)
        self._update_counters()

    def _update_counters(self):
        ready = sum(1 for f in self._files if f.get("status") == "Ready")
        errors = sum(1 for f in self._files if f.get("status") == "Error")
        no_tags = sum(1 for f in self._files if f.get("status") == "No Tags")
        selected = sum(1 for r in self._row_widgets if r.is_selected())

        if self._ctr_selected: self._ctr_selected.set_value(selected)
        if self._ctr_ready:    self._ctr_ready.set_value(ready)
        if self._ctr_errors:   self._ctr_errors.set_value(errors)

        total = len(self._files)
        if self._stats_label:
            if total == 0:
                self._stats_label.setText("0 files found")
            else:
                self._stats_label.setText(
                    f"{total} file{'s' if total != 1 else ''} found  •  "
                    f"{ready} ready  •  {no_tags} need{'s' if no_tags == 1 else ''} tags  •  {errors} error{'s' if errors != 1 else ''}"
                )

        if self._import_btn:
            self._import_btn.setEnabled(selected > 0 and not (self._import_worker and self._import_worker.isRunning()))
            self._import_btn.setText(f"⬇  Import Selected ({selected})")

    def _on_import(self):
        # Collect selected files (must be Ready ones — checkbox only enabled for those)
        selected = []
        for i, r in enumerate(self._row_widgets):
            if r.is_selected():
                selected.append(self._files[i])
        if not selected:
            return

        # Collect default settings
        cat_id = self._cat_combo.currentData() if self._cat_combo.currentIndex() > 0 else None
        year_str = self._year_combo.currentText()
        try:
            year = int(year_str)
        except (ValueError, TypeError):
            year = None
        defaults = {
            "category_id": cat_id,
            "year":        year,
            "enabled":     True,
        }

        # Disable UI during import
        if self._import_btn:
            self._import_btn.setEnabled(False)
            self._import_btn.setText(f"⏳  Importing 0/{len(selected)}...")

        worker = _ImportWorker(self._db, selected, defaults,
                               skip_duplicates=self._skip_dups_chk.isChecked())
        worker.progress.connect(self._on_import_progress)
        worker.finished_import.connect(self._on_import_finished)
        self._import_worker = worker
        worker.start()

    def _on_import_progress(self, current: int, total: int):
        pct = int(current / total * 100) if total else 0
        if self._progress_fill:
            track_w = self._progress_fill.parent().width()
            self._progress_fill.setFixedWidth(int(track_w * pct / 100))
        if self._progress_label:
            self._progress_label.setText(f"Importing — {pct}% ({current}/{total})")
        if self._import_btn:
            self._import_btn.setText(f"⏳  Importing {current}/{total}...")

    def _on_import_finished(self, added: int, skipped: int, errors: int):
        if self._progress_label:
            self._progress_label.setText(
                f"Done — {added} added  •  {skipped} skipped  •  {errors} errors"
            )
        if self._import_btn:
            self._import_btn.setEnabled(True)
            self._import_btn.setText("✓  Done")

        log.info(f"Import complete: {added} added, {skipped} skipped, {errors} errors")
        self.songs_imported.emit(added)

        # Show summary and close after a moment
        msg = (
            f"Import complete.\n\n"
            f"  • {added} song{'s' if added != 1 else ''} added\n"
            f"  • {skipped} duplicate{'s' if skipped != 1 else ''} skipped\n"
            f"  • {errors} error{'s' if errors != 1 else ''}"
        )
        QMessageBox.information(self, "Import complete", msg)
        self.accept()

    def _on_close(self):
        # Cancel any running workers cleanly
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self._scan_worker.wait(2000)
        if self._import_worker and self._import_worker.isRunning():
            self._import_worker.cancel()
            self._import_worker.wait(2000)
        self.reject()
